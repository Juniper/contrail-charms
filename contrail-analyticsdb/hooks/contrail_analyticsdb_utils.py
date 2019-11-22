from socket import inet_aton
import struct

from charmhelpers.core.hookenv import (
    config,
    related_units,
    relation_get,
    relation_ids,
    status_set,
    log,
)
from charmhelpers.core.templating import render
import common_utils
import docker_utils


config = config()


MODULE = "analyticsdb"
BASE_CONFIGS_PATH = "/etc/contrail"

CONFIGS_PATH = BASE_CONFIGS_PATH + "/analytics_database"
IMAGES = {
    '5.0': [
        "contrail-node-init",
        "contrail-nodemgr",
        "contrail-external-kafka",
        "contrail-external-cassandra",
        "contrail-external-zookeeper",
    ],
    '5.1': [
        "contrail-node-init",
        "contrail-nodemgr",
        "contrail-analytics-query-engine",
        "contrail-external-cassandra",
    ],
}
SERVICES = {
    '5.0': {
        "database": [
            "kafka",
            "nodemgr",
            "zookeeper",
            "cassandra"
        ]
    },
    '5.1': {
        "database": [
            "query-engine",
            "nodemgr",
            "cassandra"
        ]
    }
}


def servers_ctx():
    controller_ip_list = []
    controller_data_ip_list = []
    analytics_ip_list = []
    for rid in relation_ids("contrail-analyticsdb"):
        for unit in related_units(rid):
            utype = relation_get("unit-type", unit, rid)
            ip = relation_get("private-address", unit, rid)
            if not ip:
                continue
            if utype == "controller":
                controller_ip_list.append(ip)
                data_ip = relation_get("data-address", unit, rid)
                if data_ip or ip:
                    controller_data_ip_list.append(data_ip if data_ip else ip)
            if utype == "analytics":
                analytics_ip_list.append(ip)

    sort_key = lambda ip: struct.unpack("!L", inet_aton(ip))[0]
    controller_ip_list = sorted(controller_ip_list, key=sort_key)
    controller_data_ip_list = sorted(controller_data_ip_list, key=sort_key)
    analytics_ip_list = sorted(analytics_ip_list, key=sort_key)
    return {
        "controller_servers": controller_ip_list,
        "control_servers": controller_data_ip_list,
        "analytics_servers": analytics_ip_list}


def analyticsdb_ctx():
    """Get the ipaddres of all analyticsdb nodes"""
    analyticsdb_ip_list = list()
    for rid in relation_ids("analyticsdb-cluster"):
        for unit in related_units(rid):
            ip = relation_get("private-address", unit, rid)
            if ip:
                analyticsdb_ip_list.append(ip)
    # add it's own ip address
    analyticsdb_ip_list.append(common_utils.get_ip())
    sort_key = lambda ip: struct.unpack("!L", inet_aton(ip))[0]
    analyticsdb_ip_list = sorted(analyticsdb_ip_list, key=sort_key)
    return {"analyticsdb_servers": analyticsdb_ip_list}


def get_context():
    ctx = {}
    ctx["module"] = MODULE
    ctx["log_level"] = config.get("log-level", "SYS_NOTICE")
    ctx["ssl_enabled"] = config.get("ssl_enabled", False)
    ctx["analyticsdb_minimum_diskgb"] = config.get("cassandra-minimum-diskgb")
    ctx["jvm_extra_opts"] = config.get("cassandra-jvm-extra-opts")
    ctx["container_registry"] = config.get("docker-registry")
    ctx["contrail_version_tag"] = config.get("image-tag")
    ctx["config_analytics_ssl_available"] = config.get("config_analytics_ssl_available", False)
    ctx["logging"] = docker_utils.render_logging()
    ctx.update(common_utils.json_loads(config.get("orchestrator_info"), dict()))

    ctx.update(servers_ctx())
    ctx.update(analyticsdb_ctx())
    log("CTX: {}".format(ctx))
    ctx.update(common_utils.json_loads(config.get("auth_info"), dict()))
    return ctx


def update_charm_status():
    tag = config.get('image-tag')
    cver = '5.1'
    if '5.0' in tag:
        cver = '5.0'

    for image in IMAGES[cver]:
        try:
            docker_utils.pull(image, tag)
        except Exception as e:
            log("Can't load image {}".format(e))
            status_set('blocked',
                       'Image could not be pulled: {}:{}'.format(image, tag))
            return

    ctx = get_context()
    missing_relations = []
    if not ctx.get("controller_servers"):
        missing_relations.append("contrail-controller")
    if not ctx.get("analytics_servers"):
        missing_relations.append("contrail-analytics")
    if missing_relations:
        status_set('blocked',
                   'Missing relations: ' + ', '.join(missing_relations))
        return
    if not ctx.get("cloud_orchestrator"):
        status_set('blocked',
                   'Missing cloud_orchestrator info in relation '
                   'with contrail-controller.')
        return
    if ctx.get("cloud_orchestrator") == "openstack" and not ctx.get("keystone_ip"):
        status_set('blocked',
                   'Missing auth info in relation with contrail-controller.')
        return
    # TODO: what should happens if relation departed?

    changed = common_utils.apply_keystone_ca(MODULE, ctx)
    changed |= common_utils.render_and_log(cver + "/analytics-database.env",
        BASE_CONFIGS_PATH + "/common_analyticsdb.env", ctx)
    changed |= common_utils.render_and_log(cver + "/analytics-database.yaml",
        CONFIGS_PATH + "/docker-compose.yaml", ctx)
    docker_utils.compose_run(CONFIGS_PATH + "/docker-compose.yaml", changed)

    common_utils.update_services_status(MODULE, SERVICES[cver])
