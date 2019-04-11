#!/usr/bin/env python

import json
import sys
import uuid
import yaml
from socket import gethostbyname, gethostname

from subprocess import check_output
from charmhelpers.core.hookenv import (
    Hooks,
    UnregisteredHookError,
    config,
    log,
    is_leader,
    leader_get,
    leader_set,
    relation_get,
    relation_ids,
    relation_set,
    relation_id,
    related_units,
    status_set,
    remote_unit,
    local_unit,
    ERROR,
    WARNING,
    open_port,
    close_port,
)

from charmhelpers.fetch import (
    apt_install,
    apt_upgrade,
    apt_update
)
from charmhelpers.contrib.network.ip import (
    format_ipv6_addr,
)

from contrail_controller_utils import (
    update_charm_status,
    CONTAINER_NAME,
    get_analytics_list,
    get_controller_ips,
    RABBITMQ_USER,
    RABBITMQ_VHOST,
)
from common_utils import (
    get_ip,
    fix_hostname,
    json_loads,
    update_certificates,
)
from docker_utils import (
    add_docker_repo,
    apply_docker_insecure,
    docker_login,
    DOCKER_PACKAGES,
    is_container_launched,
)

PACKAGES = []

hooks = Hooks()
config = config()


@hooks.hook("install.real")
def install():
    status_set("maintenance", "Installing...")

    # TODO: try to remove this call
    fix_hostname()

    apt_upgrade(fatal=True, dist=True)
    add_docker_repo()
    apt_update(fatal=False)
    apt_install(PACKAGES + DOCKER_PACKAGES, fatal=True)

    apply_docker_insecure()
    docker_login()

    update_charm_status()


@hooks.hook("leader-elected")
def leader_elected():
    if not leader_get("db_user"):
        user = "controller"
        password = uuid.uuid4().hex
        leader_set(db_user=user, db_password=password)

    if not leader_get("rabbitmq_password_int"):
        password = uuid.uuid4().hex
        leader_set(rabbitmq_password_int=password)
        update_northbound_relations()

    ip_list = json_loads(leader_get("controller_ip_list"),list())
    ips = get_controller_ips()
    if not ip_list:
        ip_list = ips.values()
        log("IP_LIST: {}    IPS: {}".format(str(ip_list), str(ips)))
        leader_set(controller_ip_list=json.dumps(ip_list),
                   controller_ips=json.dumps(ips))
        # TODO: pass this list to all south/north relations
    else:
        current_ip_list = ips.values()
        dead_ips = set(ip_list).difference(current_ip_list)
        new_ips = set(current_ip_list).difference(ip_list)
        if new_ips:
            log("There are a new controllers that are not in the list: "
                + str(new_ips), level=ERROR)
        if dead_ips:
            log("There are a dead controllers that are in the list: "
                + str(dead_ips), level=ERROR)

    update_charm_status()


@hooks.hook("leader-settings-changed")
def leader_settings_changed():
    update_charm_status()


@hooks.hook("controller-cluster-relation-joined")
def cluster_joined():
    settings = {"unit-address": get_ip()}
    relation_set(relation_settings=settings)
    update_charm_status()


@hooks.hook("controller-cluster-relation-changed")
def cluster_changed():
    if not is_leader():
        return
    data = relation_get()
    ip = data.get("unit-address")
    if not ip:
        log("There is no unit-address in the relation")
        return
    unit = remote_unit()
    _address_changed(unit, ip)
    update_charm_status()


def _address_changed(unit, ip):
    ip_list = json_loads(leader_get("controller_ip_list"), list())
    ips = json_loads(leader_get("controller_ips"), dict())
    if ip in ip_list:
        return
    old_ip = ips.get(unit)
    if old_ip:
        index = ip_list.index(old_ip)
        ip_list[index] = ip
        ips[unit] = ip
    else:
        ip_list.append(ip)
        ips[unit] = ip

    log("IP_LIST: {}    IPS: {}".format(str(ip_list), str(ips)))
    leader_set(controller_ip_list=json.dumps(ip_list),
               controller_ips=json.dumps(ips))


@hooks.hook("controller-cluster-relation-departed")
def cluster_departed():
    if not is_leader():
        return
    unit = remote_unit()
    ips = json_loads(leader_get("controller_ips"), dict())
    if unit not in ips:
        return
    old_ip = ips.pop(unit)
    ip_list = json_loads(leader_get("controller_ip_list"), list())
    ip_list.remove(old_ip)

    log("IP_LIST: {}    IPS: {}".format(str(ip_list), str(ips)))
    leader_set(controller_ip_list=json.dumps(ip_list),
               controller_ips=json.dumps(ips))
    update_charm_status()


@hooks.hook("config-changed")
def config_changed():
    auth_mode = config.get("auth-mode")
    if auth_mode not in ("rbac", "cloud-admin", "no-auth"):
        raise Exception("Config is invalid. auth-mode must one of: "
                        "rbac, cloud-admin, no-auth.")

    if config.changed("control-network"):
        ip = get_ip()
        settings = {"private-address": ip}
        rnames = ("contrail-controller",
                  "contrail-analytics", "contrail-analyticsdb",
                  "http-services", "https-services")
        for rname in rnames:
            for rid in relation_ids(rname):
                relation_set(relation_id=rid, relation_settings=settings)
        settings = {"unit-address": ip}
        for rid in relation_ids("controller-cluster"):
            relation_set(relation_id=rid, relation_settings=settings)
        if is_leader():
            _address_changed(local_unit(), ip)

    if config.changed("docker-registry"):
        apply_docker_insecure()
    if config.changed("docker-user") or config.changed("docker-password"):
        docker_login()

    update_charm_status()
    _notify_proxy_services()

    if not is_leader():
        return

    update_northbound_relations()
    update_southbound_relations()


def update_northbound_relations(rid=None):
    settings = {
        "api-vip": config.get("vip"),
        "auth-mode": config.get("auth-mode"),
        "auth-info": config.get("auth_info"),
        "orchestrator-info": config.get("orchestrator_info"),
        "ssl-enabled": config.get("ssl_enabled", False),
        "rabbitmq_user": RABBITMQ_USER,
        "rabbitmq_vhost": RABBITMQ_VHOST,
        "configdb_cassandra_user": leader_get("db_user"),
        "configdb_cassandra_password": leader_get("db_password"),
    }
    if config.get("use-external-rabbitmq"):
        settings["rabbitmq_password"] = config.get("rabbitmq_password")
        settings["rabbitmq_hosts"] = config.get("rabbitmq_hosts")
    else:
        settings["rabbitmq_password"] = leader_get("rabbitmq_password_int")
        settings["rabbitmq_hosts"] = None

    if rid:
        relation_set(relation_id=rid, relation_settings=settings)
        return

    for rid in relation_ids("contrail-analytics"):
        relation_set(relation_id=rid, relation_settings=settings)
    for rid in relation_ids("contrail-analyticsdb"):
        relation_set(relation_id=rid, relation_settings=settings)


def update_southbound_relations(rid=None):
    settings = {
        "api-vip": config.get("vip"),
        "analytics-server": json.dumps(get_analytics_list()),
        "auth-mode": config.get("auth-mode"),
        "auth-info": config.get("auth_info"),
        "orchestrator-info": config.get("orchestrator_info"),
        "agents-info": config.get("agents-info")
    }
    for rid in ([rid] if rid else relation_ids("contrail-controller")):
        relation_set(relation_id=rid, relation_settings=settings)


@hooks.hook("contrail-controller-relation-joined")
def contrail_controller_joined():
    settings = {"private-address": get_ip(), "port": 8082}
    relation_set(relation_settings=settings)
    if is_leader():
        update_southbound_relations(rid=relation_id())


@hooks.hook("contrail-controller-relation-changed")
def contrail_controller_changed():
    data = relation_get()
    if "orchestrator-info" in data:
        config["orchestrator_info"] = data["orchestrator-info"]
    # TODO: set error if orchestrator is changed and container was started
    # with another orchestrator
    if is_leader():
        if "dpdk" in data:
            # remote unit is an agent
            address = data["private-address"]
            flags = json_loads(config.get("agents-info"), dict())
            flags[address] = data["dpdk"]
            config["agents-info"] = json.dumps(flags)
            config.save()
        update_southbound_relations()
        update_northbound_relations()
    update_charm_status()


@hooks.hook("contrail-controller-relation-departed")
def contrail_controller_departed():
    # while we have at least one openstack unit on the remote end
    # then we can suggest that orchestrator is still openstack
    for rid in relation_ids("contrail-controller"):
        for unit in related_units(rid):
            utype = relation_get('unit-type', unit, rid)
            if utype == "openstack":
                return

    config.pop("orchestrator_info", None)
    if is_leader():
        update_northbound_relations()
    if is_container_launched(CONTAINER_NAME):
        status_set(
            "blocked",
            "Container is present but cloud orchestrator was disappeared. "
            "Please kill container by yourself or restore cloud orchestrator.")


@hooks.hook("contrail-analytics-relation-joined")
def analytics_joined():
    settings = {"private-address": get_ip(), 'unit-type': 'controller'}
    relation_set(relation_settings=settings)
    if is_leader():
        update_northbound_relations(rid=relation_id())
        update_southbound_relations()
    update_charm_status()


@hooks.hook("contrail-analytics-relation-changed")
@hooks.hook("contrail-analytics-relation-departed")
def analytics_changed_departed():
    update_charm_status()
    if is_leader():
        update_southbound_relations()


@hooks.hook("contrail-analyticsdb-relation-joined")
def analyticsdb_joined():
    settings = {"private-address": get_ip(), 'unit-type': 'controller'}
    relation_set(relation_settings=settings)
    if is_leader():
        update_northbound_relations(rid=relation_id())


@hooks.hook("contrail-auth-relation-changed")
def contrail_auth_changed():
    auth_info = relation_get("auth-info")
    if auth_info is not None:
        config["auth_info"] = auth_info
    else:
        config.pop("auth_info", None)

    if is_leader():
        update_northbound_relations()
        update_southbound_relations()
    update_charm_status()


@hooks.hook("contrail-auth-relation-departed")
def contrail_auth_departed():
    units = [unit for rid in relation_ids("contrail-auth")
                  for unit in related_units(rid)]
    if units:
        return
    config.pop("auth_info", None)

    if is_leader():
        update_northbound_relations()
        update_southbound_relations()
    update_charm_status()


@hooks.hook("update-status")
def update_status():
    update_charm_status(update_config=False)


@hooks.hook("upgrade-charm")
def upgrade_charm():
    # NOTE: old image can not be deleted if container is running.
    # TODO: so think about killing the container

    # clear cached version of image
    config.pop("version_with_build", None)
    config.pop("version", None)
    config.save()

    # NOTE: this hook can be fired when either resource changed or charm code
    # changed. so if code was changed then we may need to update config
    update_charm_status()


def _http_services(vip):
    name = local_unit().replace("/", "-")
    addr = get_ip()
    return [
        {"service_name": "contrail-webui-http",
         "service_host": vip,
         "service_port": 8080,
         "service_options": [
            "timeout client 86400000",
            "mode http",
            "balance roundrobin",
            "cookie SERVERID insert indirect nocache",
            "timeout server 30000",
            "timeout connect 4000",
         ],
         "servers": [[name, addr, 8080,
            "cookie " + addr + " weight 1 maxconn 1024 check port 8082"]]},
        {"service_name": "contrail-api",
         "service_host": vip,
         "service_port": 8082,
         "service_options": [
            "timeout client 3m",
            "option nolinger",
            "timeout server 3m",
            "balance roundrobin",
         ],
         "servers": [[name, addr, 8082, "check inter 2000 rise 2 fall 3"]]}
    ]


@hooks.hook("http-services-relation-joined")
def http_services_joined(rel_id=None):
    vip = config.get("vip")
    if not vip:
        raise Exception("VIP must be set for allow relation to haproxy")
    relation_set(relation_id=rel_id,
                 services=yaml.dump(_http_services(str(vip))))


def _https_services(vip):
    name = local_unit().replace("/", "-")
    addr = get_ip()
    return [
        {"service_name": "contrail-webui-https",
         "service_host": vip,
         "service_port": 8143,
         "service_options": [
            "timeout client 86400000",
            "mode tcp",
            "balance roundrobin",
            "cookie SERVERID insert indirect nocache",
            "timeout server 30000",
            "timeout connect 4000",
         ],
         "servers": [[name, addr, 8143,
            "cookie " + addr + " weight 1 maxconn 1024 check port 8082"]]},
    ]


@hooks.hook("https-services-relation-joined")
def https_services_joined(rel_id=None):
    vip = config.get("vip")
    if not vip:
        raise Exception("VIP must be set for allow relation to haproxy")
    relation_set(relation_id=rel_id,
                 services=yaml.dump(_https_services(str(vip))))


def _notify_proxy_services():
    vip = config.get("vip")
    func = close_port if vip else open_port
    for port in ["8082", "8080", "8143"]:
        try:
            func(port, "TCP")
        except Exception:
            pass
    for rid in relation_ids("http-services"):
        if related_units(rid):
            http_services_joined(rid)
    for rid in relation_ids("https-services"):
        if related_units(rid):
            https_services_joined(rid)


@hooks.hook('amqp-relation-joined')
def amqp_joined():
    relation_set(username=RABBITMQ_USER, vhost=RABBITMQ_VHOST)


@hooks.hook('amqp-relation-changed')
def amqp_changed():
    # collect information about connected RabbitMQ server
    password = relation_get("password")
    clustered = relation_get('clustered')
    if clustered:
        vip = relation_get('vip')
        vip = format_ipv6_addr(vip) or vip
        rabbitmq_host = vip
    else:
        host = relation_get('private-address')
        host = format_ipv6_addr(host) or host
        rabbitmq_host = host

    ssl_port = relation_get('ssl_port')
    if ssl_port:
        log("Underlayed software is not capable to use non-default port",
            level=ERROR)
        return 1
    ssl_ca = relation_get('ssl_ca')
    if ssl_ca:
        log("Charm can't setup ssl support but ssl ca found", level=WARNING)
    if relation_get('ha_queues') is not None:
        log("Charm can't setup HA queues but flag is found", level=WARNING)

    rabbitmq_hosts = []
    ha_vip_only = relation_get('ha-vip-only',) is not None
    # Used for active/active rabbitmq >= grizzly
    if ((not clustered or ha_vip_only) and len(related_units()) > 1):
        for unit in related_units():
            host = relation_get('private-address', unit=unit)
            host = format_ipv6_addr(host) or host
            rabbitmq_hosts.append(host)

    if not rabbitmq_hosts:
        rabbitmq_hosts.append(rabbitmq_host)
    rabbitmq_hosts = ','.join(sorted(rabbitmq_hosts))

    # Here we have:
    # password - password from RabbitMQ server for user passed in joined
    # rabbitmq_hosts - list of hosts with RabbitMQ servers
    config["rabbitmq_password"] = password
    config["rabbitmq_hosts"] = rabbitmq_hosts
    config.save()

    update_northbound_relations()
    update_charm_status()


@hooks.hook('tls-certificates-relation-joined')
def tls_certificates_relation_joined():
    cn = gethostname().split(".")[0]
    sans = [cn]
    sans_ips = []
    try:
        sans_ips.append(gethostbyname(cn))
    except:
        pass
    control_ip = get_ip()
    if control_ip not in sans_ips:
        sans_ips.append(control_ip)
    res = check_output(['getent', 'hosts', control_ip])
    control_name = res.split()[1].split('.')[0]
    if control_name not in sans:
        sans.append(control_name)
    sans_ips.append("127.0.0.1")
    sans.extend(sans_ips)
    settings = {
        'sans': json.dumps(sans),
        'common_name': cn,
        'certificate_name': cn
    }
    log("TLS_CTX: {}".format(settings))
    relation_set(relation_settings=settings)


@hooks.hook('tls-certificates-relation-changed')
def tls_certificates_relation_changed():
    unitname = local_unit().replace('/', '_')
    cert_name = '{0}.server.cert'.format(unitname)
    key_name = '{0}.server.key'.format(unitname)
    cert = relation_get(cert_name)
    key = relation_get(key_name)
    ca = relation_get('ca')

    if not cert or not key or not ca:
        log('tls-certificates relation data is not fully available')
        cert = key = ca = None

    _tls_changed(cert, key, ca)


@hooks.hook('tls-certificates-relation-departed')
def tls_certificates_relation_departed():
    _tls_changed(None, None, None)


def _tls_changed(cert, key, ca):
    changed = update_certificates(cert, key, ca)
    if not changed:
        return

    # save certs & notify relations
    config["ssl_enabled"] = (cert is not None and len(cert) > 0)
    config.save()
    update_northbound_relations()

    update_charm_status(force=True)


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log("Unknown hook {} - skipping.".format(e))


if __name__ == "__main__":
    main()
