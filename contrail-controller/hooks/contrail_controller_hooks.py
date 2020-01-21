#!/usr/bin/env python3

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
from charmhelpers.contrib.charmsupport import nrpe

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
    for var_name in [("ip","unit-address","control-network"),
                     ("data_ip","data-address","data-network")]:
        ip_list = common_utils.json_loads(leader_get("controller_{}_list".format(var_name[0])), list())
        ips = utils.get_controller_ips(var_name[1], var_name[2])
        if not ip_list:
            ip_list = ips.values()
            log("{}_LIST: {}    {}S: {}".format(var_name[0].upper(), str(ip_list), var_name[0].upper(), str(ips)))
            settings = {
                "controller_{}_list".format(var_name[0]): json.dumps(list(ip_list)),
                "controller_{}s".format(var_name[0]): json.dumps(ips)
            }
            leader_set(settings=settings)
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
    ip = common_utils.get_ip()
    settings = {
        "unit-address": ip,
        "data-address": common_utils.get_ip(config_param="data-network", fallback=ip)
    }

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
    data_ip = data.get("data-address")
    if not ip or not data_ip:
        log("There is no unit-address or data-address in the relation")
        return

    if config.get('local-rabbitmq-hostname-resolution'):
        rabbit_hostname = data.get('rabbitmq-hostname')
        if ip and rabbit_hostname:
            utils.update_hosts_file(ip, rabbit_hostname)

    if not is_leader():
        return

    unit = remote_unit()
    _address_changed(unit, ip, 'ip')
    _address_changed(unit, data_ip, 'data_ip')
    utils.update_charm_status()


def _address_changed(unit, ip, var_name):
    ip_list = common_utils.json_loads(leader_get("controller_{}_list".format(var_name)), list())
    ips = common_utils.json_loads(leader_get("controller_{}s".format(var_name)), dict())
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

    log("{}_LIST: {}    {}S: {}".format(var_name.upper(), str(ip_list), var_name.upper(), str(ips)))
    settings = {
        "controller_{}_list".format(var_name): json.dumps(ip_list),
        "controller_{}s".format(var_name): json.dumps(ips)
    }
    leader_set(settings=settings)


@hooks.hook("controller-cluster-relation-departed")
def cluster_departed():
    if not is_leader():
        return
    unit = remote_unit()
    for var_name in ["ip", "data_ip"]:
        ips = common_utils.json_loads(leader_get("controller_{}s".format(var_name)), dict())
        if unit not in ips:
            return
        old_ip = ips.pop(unit)
        ip_list = common_utils.json_loads(leader_get("controller_{}_list".format(var_name)), list())
        ip_list.remove(old_ip)
        log("{}_LIST: {}    {}S: {}".format(var_name.upper(), str(ip_list), var_name.upper(), str(ips)))

        settings = {
            "controller_{}_list".format(var_name): json.dumps(ip_list),
            "controller_{}s".format(var_name): json.dumps(ips)
        }
        leader_set(settings=settings)

    utils.update_charm_status()


@hooks.hook("config-changed")
def config_changed():
    update_nrpe_config()
    auth_mode = config.get("auth-mode")
    if auth_mode not in ("rbac", "cloud-admin", "no-auth"):
        raise Exception("Config is invalid. auth-mode must one of: "
                        "rbac, cloud-admin, no-auth.")

    if config.changed("control-network") or config.changed("data-network"):
        ip = common_utils.get_ip()
        data_ip = common_utils.get_ip(config_param="data-network", fallback=ip)
        rel_settings = {"private-address": ip, "data-address": data_ip}
        cluster_settings = {"unit-address": ip, "data-address": data_ip}
        rnames = ("contrail-controller",
                  "contrail-analytics", "contrail-analyticsdb",
                  "http-services", "https-services")
        for rname in rnames:
            for rid in relation_ids(rname):
                relation_set(relation_id=rid, relation_settings=rel_settings)
        if config.get('local-rabbitmq-hostname-resolution'):
            cluster_settings.update({
                "rabbitmq-hostname": utils.get_contrail_rabbit_hostname(),
            })
            # this will also take care of updating the hostname in case
            # control-network changes to something different although
            # such host reconfiguration is unlikely
            utils.update_rabbitmq_cluster_hostnames()

        for rid in relation_ids("controller-cluster"):
            relation_set(relation_id=rid, relation_settings=cluster_settings)
        if is_leader():
            _address_changed(local_unit(), ip, 'ip')
            _address_changed(local_unit(), data_ip, 'data_ip')

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

    config["config_analytics_ssl_available"] = common_utils.is_config_analytics_ssl_available()
    config.save()

    docker_utils.config_changed()
    utils.update_charm_status()
    _notify_haproxy_services()

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
        "agents-info": config.get("agents-info"),
        "ssl-enabled": config.get("ssl_enabled") and config.get("config_analytics_ssl_available"),
        # base64 encoded ca-cert
        "ca-cert": config.get("ca_cert"),
    }

    settings.update(utils.get_cassandra_connection_details())
    settings.update(utils.get_rabbitmq_connection_details())
    settings.update(utils.get_zookeeper_connection_details())

    for rid in ([rid] if rid else relation_ids("contrail-controller")):
        relation_set(relation_id=rid, relation_settings=settings)


@hooks.hook("contrail-controller-relation-joined")
def contrail_controller_joined():
    ip = common_utils.get_ip()
    settings = {
        "private-address": ip,
        "data-address": common_utils.get_ip(config_param="data-network", fallback=ip),
        "port": 8082
    }
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
    # while we have at least one openstack/kubernetes unit on the remote end
    # then we can suggest that orchestrator is still defined
    for rid in relation_ids("contrail-controller"):
        for unit in related_units(rid):
            utype = relation_get('unit-type', unit, rid)
            if utype == "openstack" or utype == "kubernetes":
                return

    config.pop("orchestrator_info", None)
    if is_leader():
        update_northbound_relations()


@hooks.hook("contrail-analytics-relation-joined")
def analytics_joined():
    ip = common_utils.get_ip()
    settings = {"private-address": ip,
                "data-address": common_utils.get_ip(config_param="data-network", fallback=ip),
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
    ip = common_utils.get_ip()
    settings = {"private-address": ip,
                "data-address": common_utils.get_ip(config_param="data-network", fallback=ip),
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

    mode = config.get("haproxy-http-mode", "http")

    config_analytics_ssl_available = config.get("config_analytics_ssl_available", False)
    if config_analytics_ssl_available:
        servers = [[name, addr, 8082, "check inter 2000 rise 2 fall 3 ssl verify none"]]
    else:
        servers = [[name, addr, 8082, "check inter 2000 rise 2 fall 3"]]

    result = [
        {"service_name": "contrail-api",
         "service_host": vip,
         "service_port": 8082,
         "servers": servers}
    ]
    if mode == 'http':
        result[0]['service_options'] = [
            "timeout client 3m",
            "option nolinger",
            "timeout server 3m",
            "balance source"]
    else:
        result[0]['service_options'] = [
            "timeout client 86400000",
            "mode http",
            "balance source",
            "timeout server 30000",
            "timeout connect 4000",
            "hash-type consistent",
            "http-request set-header X-Forwarded-Proto https if { ssl_fc }",
            "http-request set-header X-Forwarded-Proto http if !{ ssl_fc }",
            "option httpchk GET /",
            "option forwardfor",
            "redirect scheme https code 301 if { hdr(host) -i " + str(vip) + " } !{ ssl_fc }",
            "rsprep ^Location:\\ http://(.*) Location:\\ https://\\1"]
        result[0]['crts'] = ["DEFAULT"]

    return result


@hooks.hook("http-services-relation-joined")
def http_services_joined(rel_id=None):
    vip = config.get("vip")
    if not vip:
        raise Exception("VIP must be set for allow relation to haproxy")
    relation_set(relation_id=rel_id,
                 services=yaml.dump(_http_services(str(vip))))


def _https_services_tcp(vip):
    name = local_unit().replace("/", "-")
    addr = common_utils.get_ip()
    return [
        {"service_name": "contrail-webui-https",
         "service_host": vip,
         "service_port": 8143,
         "service_options": [
            "timeout client 86400000",
            "mode tcp",
            "option tcplog",
            "balance source",
            "cookie SERVERID insert indirect nocache",
            "timeout server 30000",
            "timeout connect 4000",
         ],
         "servers": [[name, addr, 8143,
            "cookie " + addr + " weight 1 maxconn 1024 check port 8143"]]},
    ]


def _https_services_http(vip):
    name = local_unit().replace("/", "-")
    addr = common_utils.get_ip()
    return [
        {"service_name": "contrail-webui-https",
         "service_host": vip,
         "service_port": 8143,
         "crts": ["DEFAULT"],
         "service_options": [
            "timeout client 86400000",
            "mode http",
            "balance source",
            "timeout server 30000",
            "timeout connect 4000",
            "hash-type consistent",
            "http-request set-header X-Forwarded-Proto https if { ssl_fc }",
            "http-request set-header X-Forwarded-Proto http if !{ ssl_fc }",
            "option httpchk GET /",
            "option forwardfor",
            "redirect scheme https code 301 if { hdr(host) -i " + str(vip) + " } !{ ssl_fc }",
            "rsprep ^Location:\\ http://(.*) Location:\\ https://\\1",
         ],
         "servers": [[name, addr, 8143,
            "check fall 5 inter 2000 rise 2 ssl verify none"]]},
    ]


@hooks.hook("https-services-relation-joined")
def https_services_joined(rel_id=None):
    vip = config.get("vip")
    if not vip:
        raise Exception("VIP must be set for allow relation to haproxy")
    mode = config.get("haproxy-https-mode", "tcp")
    if mode == "tcp":
        data = _https_services_tcp(str(vip))
    elif mode == "http":
        data = _https_services_http(str(vip))
    else:
        raise Exception("Invalid haproxy-https-mode: {}. Possible values: tcp or http".format(mode))
    relation_set(relation_id=rel_id,
                 services=yaml.dump(data))


def _notify_haproxy_services():
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
    settings = common_utils.get_tls_settings(common_utils.get_ip())
    relation_set(relation_settings=settings)


@hooks.hook('tls-certificates-relation-changed')
def tls_certificates_relation_changed():
    if common_utils.tls_changed(utils.MODULE, relation_get()):
        update_southbound_relations()
        utils.update_charm_status()


@hooks.hook('tls-certificates-relation-departed')
def tls_certificates_relation_departed():
    if common_utils.tls_changed(utils.MODULE, None):
        update_southbound_relations()
        utils.update_charm_status()


@hooks.hook('nrpe-external-master-relation-changed')
def nrpe_external_master_relation_changed():
    update_nrpe_config()


@hooks.hook('contrail-issu-relation-changed')
def contrail_issu_relation_changed():
    ctx = {'old': relation_get()}
    ctx["new"] = utils.get_cassandra_connection_details()
    ctx["new"].update(utils.get_rabbitmq_connection_details())
    ctx["new"].update(utils.get_zookeeper_connection_details())

    common_utils.render_and_log("issu.conf", utils.BASE_CONFIGS_PATH + "/issu.conf", ctx)
    # TODO run docker


def update_nrpe_config():
    plugins_dir = '/usr/local/lib/nagios/plugins'
    nrpe_compat = nrpe.NRPE()
    component_ip = common_utils.get_ip()
    common_utils.rsync_nrpe_checks(plugins_dir)
    common_utils.add_nagios_to_sudoers()

    check_ui_cmd = 'check_http -H {} -p 8143 -S'.format(component_ip)
    nrpe_compat.add_check(
        shortname='check_contrail_web_ui',
        description='Check Contrail WebUI',
        check_cmd=check_ui_cmd
    )

    check_api_cmd = 'check_http -H {} -p 8082'.format(component_ip)
    nrpe_compat.add_check(
        shortname='check_contrail_api',
        description='Check Contrail API',
        check_cmd=check_api_cmd
    )

    ctl_status_shortname = 'check_contrail_status_' + utils.MODULE
    nrpe_compat.add_check(
        shortname=ctl_status_shortname,
        description='Check contrail-status',
        check_cmd=common_utils.contrail_status_cmd(utils.MODULE, plugins_dir)
    )

    nrpe_compat.write()


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log("Unknown hook {} - skipping.".format(e))


if __name__ == "__main__":
    main()
