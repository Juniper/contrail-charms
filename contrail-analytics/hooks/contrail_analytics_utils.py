from socket import inet_aton
import struct

import apt_pkg

from charmhelpers.core.hookenv import (
    config,
    related_units,
    relation_get,
    relation_ids,
    status_set,
    open_port,
    log,
)
from charmhelpers.core.templating import render
import common_utils
import docker_utils


apt_pkg.init()
config = config()


BASE_CONFIGS_PATH = "/etc/contrail"

ANALYTICS_CONFIGS_PATH = BASE_CONFIGS_PATH + "/analytics"
ANALYTICS_IMAGES = [
    "contrail-node-init",
    "contrail-nodemgr",
    "contrail-analytics-api",
    "contrail-analytics-collector",
    "contrail-analytics-query-engine",
    "contrail-analytics-alarm-gen",
    "contrail-analytics-snmp-collector",
    "contrail-analytics-topology",
]

REDIS_CONFIGS_PATH = BASE_CONFIGS_PATH + "/redis"
REDIS_IMAGES = [
    "contrail-external-redis",
]


def controller_ctx():
    """Get the ipaddress of all contrail control nodes"""
    auth_mode = config.get("auth_mode")
    if auth_mode is None:
        # NOTE: auth_mode must be transmitted by controller
        return {}

    controller_ip_list = []
    for rid in relation_ids("contrail-analytics"):
        for unit in related_units(rid):
            utype = relation_get('unit-type', unit, rid)
            if utype == "controller":
                ip = relation_get("private-address", unit, rid)
                controller_ip_list.append(ip)
    sort_key = lambda ip: struct.unpack("!L", inet_aton(ip))[0]
    controller_ip_list = sorted(controller_ip_list, key=sort_key)
    return {
        "auth_mode": auth_mode,
        "controller_servers": controller_ip_list,
    }


def analytics_ctx():
    """Get the ipaddress of all analytics control nodes"""
    analytics_ip_list = []
    for rid in relation_ids("analytics-cluster"):
        for unit in related_units(rid):
            ip = relation_get("private-address", unit, rid)
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
            analyticsdb_ip_list.append(ip)

    sort_key = lambda ip: struct.unpack("!L", inet_aton(ip))[0]
    analyticsdb_ip_list = sorted(analyticsdb_ip_list, key=sort_key)
    return {"analyticsdb_servers": analyticsdb_ip_list}


def get_context():
    ctx = {}
    ctx["log_level"] = config.get("log-level", "SYS_NOTICE")
    ctx["ssl_enabled"] = config.get("ssl_enabled", False)
    ctx["container_registry"] = config.get("docker-registry")
    ctx["contrail_version_tag"] = config.get("image-tag")
    ctx.update(common_utils.json_loads(config.get("orchestrator_info"), dict()))

    ctx.update(controller_ctx())
    ctx.update(analytics_ctx())
    ctx.update(analyticsdb_ctx())
    log("CTX: {}".format(ctx))
    ctx.update(common_utils.json_loads(config.get("auth_info"), dict()))
    return ctx


def render_config(ctx):
    render("analytics.env",
        BASE_CONFIGS_PATH + "/common-analytics.env", ctx)

    render("analytics.yaml",
        ANALYTICS_CONFIGS_PATH + "/docker-compose.yaml", ctx)

    # redis is a common service that needs own synchronized env
    render("redis.env",
        BASE_CONFIGS_PATH + "/redis.env", ctx)
    render("redis.yaml",
        REDIS_CONFIGS_PATH + "/docker-compose.yaml", ctx)

    # apply_keystone_ca


def update_charm_status():
    registry = config.get('docker-registry')
    tag = config.get('image-tag')
    for image in ANALYTICS_IMAGES + REDIS_IMAGES:
        try:
            docker_utils.docker_pull(registry, image, tag)
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
    if not ctx.get("keystone_ip"):
        status_set('blocked',
                   'Missing auth info in relation with contrail-controller.')
        return
    # TODO: what should happens if relation departed?

    render_config(ctx)
    open_port(8081, "TCP")

    docker_utils.docker_compose_run(ANALYTICS_CONFIGS_PATH + "/docker-compose.yaml")
    docker_utils.docker_compose_run(REDIS_CONFIGS_PATH + "/docker-compose.yaml")
    status_set("active", "Unit is ready")
