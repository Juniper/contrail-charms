#!/usr/bin/env python

import json
import sys
import yaml
from socket import gethostbyname, gethostname, getfqdn

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
    open_port,
    close_port,
)

from charmhelpers.core.unitdata import kv

import contrail_controller_utils as utils
import common_utils
import docker_utils

hooks = Hooks()
config = config()


@hooks.hook("install.real")
def install():
    status_set("maintenance", "Installing...")

    # TODO: try to remove this call
    common_utils.fix_hostname()

    if config.get('local-rabbitmq-hostname-resolution'):
        utils.update_rabbitmq_cluster_hostnames()

    docker_utils.install()
    utils.update_charm_status()


@hooks.hook("leader-elected")
def leader_elected():
    ip_list = leader_get("controller_ip_list")
    ips = utils.get_controller_ips()
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

    utils.update_charm_status()


@hooks.hook("leader-settings-changed")
def leader_settings_changed():
    utils.update_charm_status()


@hooks.hook("controller-cluster-relation-joined")
def cluster_joined():
    settings = {"unit-address": common_utils.get_ip()}

    if config.get('local-rabbitmq-hostname-resolution'):
        settings.update({
            "rabbitmq-hostname": utils.get_contrail_rabbit_hostname(),
        })

        # a remote unit might have already set rabbitmq-hostname if
        # it came up before this unit was provisioned so the -changed
        # event will not fire for it and we have to handle it here
        data = relation_get()
        log("Joined the peer relation with {}: {}".format(
            remote_unit(), data))
        ip = data.get("unit-address")
        rabbit_hostname = data.get('rabbitmq-hostname')
        if ip and rabbit_hostname:
            utils.update_hosts_file(ip, rabbit_hostname)

    relation_set(relation_settings=settings)
    utils.update_charm_status()


@hooks.hook("controller-cluster-relation-changed")
def cluster_changed():
    data = relation_get()
    log("Peer relation changed with {}: {}".format(
        remote_unit(), data))
    ip = data.get("unit-address")

    if not ip:
        log("There is no unit-address in the relation")
        return

    if config.get('local-rabbitmq-hostname-resolution'):
        rabbit_hostname = data.get('rabbitmq-hostname')
        if ip and rabbit_hostname:
            utils.update_hosts_file(ip, rabbit_hostname)
    unit = remote_unit()

    if not is_leader():
        return

    _address_changed(unit, ip)
    utils.update_charm_status()


def _address_changed(unit, ip):
    ip_list = common_utils.json_loads(leader_get("controller_ip_list"), list())
    ips = common_utils.json_loads(leader_get("controller_ips"), dict())
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
    ips = common_utils.json_loads(leader_get("controller_ips"), dict())
    if unit not in ips:
        return
    old_ip = ips.pop(unit)
    ip_list = common_utils.json_loads(leader_get("controller_ip_list"), list())
    ip_list.remove(old_ip)

    log("IP_LIST: {}    IPS: {}".format(str(ip_list), str(ips)))
    leader_set(controller_ip_list=json.dumps(ip_list),
               controller_ips=json.dumps(ips))
    utils.update_charm_status()


@hooks.hook("config-changed")
def config_changed():
    auth_mode = config.get("auth-mode")
    if auth_mode not in ("rbac", "cloud-admin", "no-auth"):
        raise Exception("Config is invalid. auth-mode must one of: "
                        "rbac, cloud-admin, no-auth.")

    if config.changed("control-network"):
        ip = common_utils.get_ip()
        settings = {"private-address": ip}

        rnames = ("contrail-controller",
                  "contrail-analytics", "contrail-analyticsdb",
                  "http-services", "https-services")
        for rname in rnames:
            for rid in relation_ids(rname):
                relation_set(relation_id=rid, relation_settings=settings)
        settings = {"unit-address": ip}

        if config.get('local-rabbitmq-hostname-resolution'):
            settings.update({
                "rabbitmq-hostname": utils.get_contrail_rabbit_hostname(),
            })
            # this will also take care of updating the hostname in case
            # control-network changes to something different although
            # such host reconfiguration is unlikely
            utils.update_rabbitmq_cluster_hostnames()

        for rid in relation_ids("controller-cluster"):
            relation_set(relation_id=rid, relation_settings=settings)
        if is_leader():
            _address_changed(local_unit(), ip)

    if config.changed("local-rabbitmq-hostname-resolution"):
        if config.get("local-rabbitmq-hostname-resolution"):
            # enabling this option will trigger events on other units
            # so their hostnames will be added as -changed events fire
            # we just need to set our hostname
            utils.update_rabbitmq_cluster_hostnames()
        else:
            kvstore = kv()
            rabbitmq_hosts = kvstore.get(key='rabbitmq_hosts', default={})
            for ip, hostname in rabbitmq_hosts:
                utils.update_hosts_file(ip, hostname, remove_hostname=True)

    docker_utils.config_changed()
    utils.update_charm_status()
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
    }

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
        "analytics-server": json.dumps(utils.get_analytics_list()),
        "auth-mode": config.get("auth-mode"),
        "auth-info": config.get("auth_info"),
        "orchestrator-info": config.get("orchestrator_info"),
        "agents-info": config.get("agents-info")
    }
    for rid in ([rid] if rid else relation_ids("contrail-controller")):
        relation_set(relation_id=rid, relation_settings=settings)


@hooks.hook("contrail-controller-relation-joined")
def contrail_controller_joined():
    settings = {"private-address": common_utils.get_ip(), "port": 8082}
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
            flags = common_utils.json_loads(config.get("agents-info"), dict())
            flags[address] = data["dpdk"]
            config["agents-info"] = json.dumps(flags)
            config.save()
        update_southbound_relations()
        update_northbound_relations()
    utils.update_charm_status()


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


@hooks.hook("contrail-analytics-relation-joined")
def analytics_joined():
    settings = {"private-address": common_utils.get_ip(),
                'unit-type': 'controller'}
    relation_set(relation_settings=settings)
    if is_leader():
        update_northbound_relations(rid=relation_id())
        update_southbound_relations()
    utils.update_charm_status()


@hooks.hook("contrail-analytics-relation-changed")
@hooks.hook("contrail-analytics-relation-departed")
def analytics_changed_departed():
    utils.update_charm_status()
    if is_leader():
        update_southbound_relations()


@hooks.hook("contrail-analyticsdb-relation-joined")
def analyticsdb_joined():
    settings = {"private-address": common_utils.get_ip(),
                'unit-type': 'controller'}
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
    utils.update_charm_status()


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
    utils.update_charm_status()


@hooks.hook("update-status")
def update_status():
    utils.update_charm_status()


@hooks.hook("upgrade-charm")
def upgrade_charm():
    utils.update_charm_status()


def _http_services(vip):
    name = local_unit().replace("/", "-")
    addr = common_utils.get_ip()
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
    addr = common_utils.get_ip()
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


@hooks.hook('tls-certificates-relation-joined')
def tls_certificates_relation_joined():
    hostname = getfqdn()
    cn = hostname.split(".")[0]
    sans = [hostname]
    if hostname != cn:
        sans.append(cn)
    sans_ips = []
    try:
        sans_ips.append(gethostbyname(hostname))
    except:
        pass
    control_ip = common_utils.get_ip()
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
    changed = common_utils.update_certificates(cert, key, ca)
    if not changed:
        return

    # save certs & notify relations
    config["ssl_enabled"] = (cert is not None and len(cert) > 0)
    config.save()
    update_northbound_relations()

    utils.update_charm_status()


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log("Unknown hook {} - skipping.".format(e))


if __name__ == "__main__":
    main()
