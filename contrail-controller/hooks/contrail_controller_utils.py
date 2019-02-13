from socket import inet_aton
import struct

from charmhelpers.core.hookenv import (
    config,
    related_units,
    relation_ids,
    relation_get,
    status_set,
    leader_get,
    log,
    local_unit,
)
from charmhelpers.core.templating import render
import common_utils
import docker_utils

config = config()

BASE_CONFIGS_PATH = "/etc/contrail"

CONFIG_API_CONFIGS_PATH = BASE_CONFIGS_PATH + "/config_api"
CONFIG_DATABASE_CONFIGS_PATH = BASE_CONFIGS_PATH + "/config_database"
CONTROL_CONFIGS_PATH = BASE_CONFIGS_PATH + "/control"
WEBUI_CONFIGS_PATH = BASE_CONFIGS_PATH + "/webui"
REDIS_CONFIGS_PATH = BASE_CONFIGS_PATH + "/redis"

IMAGES = [
    "contrail-node-init",
    "contrail-nodemgr",
    "contrail-controller-config-api",
    "contrail-controller-config-svcmonitor",
    "contrail-controller-config-schema",
    "contrail-controller-config-devicemgr",
    "contrail-controller-control-control",
    "contrail-controller-control-named",
    "contrail-controller-control-dns",
    "contrail-controller-webui-web",
    "contrail-controller-webui-job",
    "contrail-external-cassandra",
    "contrail-external-zookeeper",
    "contrail-external-rabbitmq",
    "contrail-external-redis",
]

SERVICES = {
    "control": [
        "control",
        "nodemgr",
        "named",
        "dns",
    ],
    "config-database": [
        "nodemgr",
        "zookeeper",
        "rabbitmq",
        "cassandra",
    ],
    "webui": [
        "web",
        "job",
    ],
    "config": [
        "svc-monitor",
        "nodemgr",
        "device-manager",
        "api",
        "schema",
    ],
}


def get_controller_ips():
    controller_ips = dict()
    for rid in relation_ids("controller-cluster"):
        for unit in related_units(rid):
            ip = relation_get("unit-address", unit, rid)
            controller_ips[unit] = ip
    # add it's own ip address
    controller_ips[local_unit()] = common_utils.get_ip()
    return controller_ips


def get_analytics_list():
    analytics_ip_list = []
    for rid in relation_ids("contrail-analytics"):
        for unit in related_units(rid):
            ip = relation_get("private-address", unit, rid)
            analytics_ip_list.append(ip)
    sort_key = lambda ip: struct.unpack("!L", inet_aton(ip))[0]
    analytics_ip_list = sorted(analytics_ip_list, key=sort_key)
    return analytics_ip_list


def get_context():
    ctx = {}
    ctx["log_level"] = config.get("log-level", "SYS_NOTICE")
    ctx["flow_export_rate"] = config.get("flow-export-rate")
    ctx["auth_mode"] = config.get("auth-mode")
    ctx["cloud_admin_role"] = config.get("cloud-admin-role")
    ctx["global_read_only_role"] = config.get("global-read-only-role")
    ctx["configdb_minimum_diskgb"] = config.get("cassandra-minimum-diskgb")
    ctx["jvm_extra_opts"] = config.get("cassandra-jvm-extra-opts")
    ctx["container_registry"] = config.get("docker-registry")
    ctx["contrail_version_tag"] = config.get("image-tag")
    ctx.update(common_utils.json_loads(config.get("orchestrator_info"), dict()))

    ctx["ssl_enabled"] = config.get("ssl_enabled", False)

    ips = common_utils.json_loads(leader_get("controller_ip_list"), list())
    ctx["controller_servers"] = ips
    ctx["analytics_servers"] = get_analytics_list()
    log("CTX: " + str(ctx))
    ctx.update(common_utils.json_loads(config.get("auth_info"), dict()))
    return ctx


def update_charm_status():
    tag = config.get('image-tag')
    for image in IMAGES:
        try:
            docker_utils.pull(image, tag)
        except Exception as e:
            log("Can't load image {}".format(e))
            status_set('blocked',
                       'Image could not be pulled: {}:{}'.format(image, tag))
            return

    ctx = get_context()
    missing_relations = []
    if not ctx.get("analytics_servers"):
        missing_relations.append("contrail-analytics")
    if common_utils.get_ip() not in ctx.get("controller_servers"):
        missing_relations.append("contrail-cluster")
    if missing_relations:
        status_set('blocked',
                   'Missing relations: ' + ', '.join(missing_relations))
        return
    if not ctx.get("cloud_orchestrator"):
        status_set('blocked',
                   'Missing cloud orchestrator info in relations.')
        return
    if not ctx.get("keystone_ip"):
        status_set('blocked',
                   'Missing auth info in relation with contrail-auth.')
        return
    # TODO: what should happens if relation departed?

    changed = common_utils.apply_keystone_ca(ctx)
    changed |= common_utils.render_and_log("config.env",
        BASE_CONFIGS_PATH + "/common_config.env", ctx)

    service_changed = common_utils.render_and_log("config-api.yaml",
        CONFIG_API_CONFIGS_PATH + "/docker-compose.yaml", ctx)
    if changed or service_changed:
        docker_utils.compose_run(CONFIG_API_CONFIGS_PATH + "/docker-compose.yaml")

    service_changed = common_utils.render_and_log("config-database.yaml",
        CONFIG_DATABASE_CONFIGS_PATH + "/docker-compose.yaml", ctx)
    if changed or service_changed:
        docker_utils.compose_run(CONFIG_DATABASE_CONFIGS_PATH + "/docker-compose.yaml")

    service_changed = common_utils.render_and_log("control.yaml",
        CONTROL_CONFIGS_PATH + "/docker-compose.yaml", ctx)
    if changed or service_changed:
        docker_utils.compose_run(CONTROL_CONFIGS_PATH + "/docker-compose.yaml")

    service_changed = common_utils.render_and_log("webui.yaml",
        WEBUI_CONFIGS_PATH + "/docker-compose.yaml", ctx)
    if changed or service_changed:
        docker_utils.compose_run(WEBUI_CONFIGS_PATH + "/docker-compose.yaml")

    # redis is a common service that needs own synchronized env
    changed = common_utils.render_and_log("redis.env",
        BASE_CONFIGS_PATH + "/redis.env", ctx)
    changed |= common_utils.render_and_log("redis.yaml",
        REDIS_CONFIGS_PATH + "/docker-compose.yaml", ctx)
    if changed:
        docker_utils.compose_run(REDIS_CONFIGS_PATH + "/docker-compose.yaml")

    common_utils.update_services_status(SERVICES)
