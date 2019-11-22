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


MODULE = "analytics"
BASE_CONFIGS_PATH = "/etc/contrail"

ANALYTICS_CONFIGS_PATH = BASE_CONFIGS_PATH + "/analytics"
ANALYTICS_ALARM_CONFIGS_PATH = BASE_CONFIGS_PATH + "/analytics_alarm"
ANALYTICS_SNMP_CONFIGS_PATH = BASE_CONFIGS_PATH + "/analytics_snmp"
REDIS_CONFIGS_PATH = BASE_CONFIGS_PATH + "/redis"

IMAGES = {
    '5.0': [
        "contrail-node-init",
        "contrail-nodemgr",
        "contrail-analytics-api",
        "contrail-analytics-collector",
        "contrail-analytics-query-engine",
        "contrail-analytics-alarm-gen",
        "contrail-analytics-snmp-collector",
        "contrail-analytics-topology",
        "contrail-external-redis",
    ],
    '5.1': [
        "contrail-node-init",
        "contrail-nodemgr",
        "contrail-analytics-api",
        "contrail-analytics-collector",
        "contrail-analytics-alarm-gen",
        "contrail-analytics-snmp-collector",
        "contrail-analytics-snmp-topology",
        "contrail-external-redis",
    ],
}  

SERVICES = {
    '5.0': {
        "analytics": [
            "snmp-collector",
            "query-engine",
            "api",
            "alarm-gen",
            "nodemgr",
            "collector",
            "topology",
        ]
    },
    '5.1': {
        "analytics": [
            "api",
            "nodemgr",
            "collector",
        ],
        "analytics-alarm": [
            "alarm-gen",
            "nodemgr",
            "kafka",
        ],
        "analytics-snmp": [
            "snmp-collector",
            "nodemgr",
            "topology",
        ],
    },
}


def controller_ctx():
    """Get the ipaddress of all contrail control nodes"""
    auth_mode = config.get("auth_mode")
    if auth_mode is None:
        # NOTE: auth_mode must be transmitted by controller
        return {}

    controller_ip_list = []
    controller_data_ip_list = []
    for rid in relation_ids("contrail-analytics"):
        for unit in related_units(rid):
            utype = relation_get('unit-type', unit, rid)
            if utype == "controller":
                ip = relation_get("private-address", unit, rid)
                if ip:
                    controller_ip_list.append(ip)
                data_ip = relation_get("data-address", unit, rid)
                if data_ip or ip:
                    controller_data_ip_list.append(data_ip if data_ip else ip)
    sort_key = lambda ip: struct.unpack("!L", inet_aton(ip))[0]
    controller_ip_list = sorted(controller_ip_list, key=sort_key)
    controller_data_ip_list = sorted(controller_data_ip_list, key=sort_key)

    return {
        "auth_mode": auth_mode,
        "controller_servers": controller_ip_list,
        "control_servers": controller_data_ip_list,
    }


def analytics_ctx():
    """Get the ipaddress of all analytics control nodes"""
    analytics_ip_list = []
    for rid in relation_ids("analytics-cluster"):
        for unit in related_units(rid):
            ip = relation_get("private-address", unit, rid)
            if ip:
                analytics_ip_list.append(ip)
    # add it's own ip address
    analytics_ip_list.append(common_utils.get_ip())
    sort_key = lambda ip: struct.unpack("!L", inet_aton(ip))[0]
    analytics_ip_list = sorted(analytics_ip_list, key=sort_key)
    return {"analytics_servers": analytics_ip_list}


def analyticsdb_ctx():
    """Get the ipaddress of all contrail analyticsdb nodes"""
    analyticsdb_ip_list = []
    for rid in relation_ids("contrail-analyticsdb"):
        for unit in related_units(rid):
            ip = relation_get("private-address", unit, rid)
            if ip:
                analyticsdb_ip_list.append(ip)

    sort_key = lambda ip: struct.unpack("!L", inet_aton(ip))[0]
    analyticsdb_ip_list = sorted(analyticsdb_ip_list, key=sort_key)
    return {"analyticsdb_servers": analyticsdb_ip_list}


def get_context():
    ctx = {}
    ctx["module"] = MODULE
    ctx["log_level"] = config.get("log-level", "SYS_NOTICE")
    ctx["ssl_enabled"] = config.get("ssl_enabled", False)
    ctx["container_registry"] = config.get("docker-registry")
    ctx["contrail_version_tag"] = config.get("image-tag")
    ctx.update(common_utils.json_loads(config.get("orchestrator_info"), dict()))
    ctx["config_analytics_ssl_available"] = config.get("config_analytics_ssl_available", False)
    ctx["logging"] = docker_utils.render_logging()

    ctx.update(controller_ctx())
    ctx.update(analytics_ctx())
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
    if not ctx.get("analyticsdb_servers"):
        missing_relations.append("contrail-analyticsdb")
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
    changed |= common_utils.render_and_log(cver + "/analytics.env",
        BASE_CONFIGS_PATH + "/common_analytics.env", ctx)

    changed |= common_utils.render_and_log(cver + "/analytics.yaml",
        ANALYTICS_CONFIGS_PATH + "/docker-compose.yaml", ctx)
    docker_utils.compose_run(ANALYTICS_CONFIGS_PATH + "/docker-compose.yaml", changed)

    if cver == '5.1':
        changed |= common_utils.render_and_log(cver + "/analytics-alarm.yaml",
            ANALYTICS_ALARM_CONFIGS_PATH + "/docker-compose.yaml", ctx)
        docker_utils.compose_run(ANALYTICS_ALARM_CONFIGS_PATH + "/docker-compose.yaml", changed)

        changed |= common_utils.render_and_log(cver + "/analytics-snmp.yaml",
            ANALYTICS_SNMP_CONFIGS_PATH + "/docker-compose.yaml", ctx)
        docker_utils.compose_run(ANALYTICS_SNMP_CONFIGS_PATH + "/docker-compose.yaml", changed)

    # redis is a common service that needs own synchronized env
    changed = common_utils.render_and_log("redis.env",
        BASE_CONFIGS_PATH + "/redis.env", ctx)
    changed |= common_utils.render_and_log("redis.yaml",
        REDIS_CONFIGS_PATH + "/docker-compose.yaml", ctx)
    docker_utils.compose_run(REDIS_CONFIGS_PATH + "/docker-compose.yaml", changed)

    common_utils.update_services_status(MODULE, SERVICES[cver])
