from socket import inet_aton
import struct

import apt_pkg

from charmhelpers.core.hookenv import (
    config,
    related_units,
    relation_get,
    relation_ids,
    status_set,
    leader_get,
    log,
)

from common_utils import (
    get_ip,
    check_run_prerequisites,
    run_container,
    json_loads,
    render_and_check,
)


apt_pkg.init()
config = config()


CONTAINER_NAME = "contrail-analyticsdb"
CONFIG_NAME = "analyticsdb"
SERVICES_TO_CHECK = ["contrail-database"]


def servers_ctx():
    controller_ip_list = []
    analytics_ip_list = []
    for rid in relation_ids("contrail-analyticsdb"):
        for unit in related_units(rid):
            ip = relation_get("private-address", unit, rid)
            if unit.startswith("contrail-controller"):
                controller_ip_list.append(ip)
            if unit.startswith("contrail-analytics"):
                analytics_ip_list.append(ip)

    sort_key = lambda ip: struct.unpack("!L", inet_aton(ip))[0]
    controller_ip_list = sorted(controller_ip_list, key=sort_key)
    analytics_ip_list = sorted(analytics_ip_list, key=sort_key)
    return {
        "controller_servers": controller_ip_list,
        "analytics_servers": analytics_ip_list}


def analyticsdb_ctx():
    """Get the ipaddres of all analyticsdb nodes"""
    analyticsdb_ip_list = [
        relation_get("private-address", unit, rid)
        for rid in relation_ids("analyticsdb-cluster")
        for unit in related_units(rid)]
    # add it's own ip address
    analyticsdb_ip_list.append(get_ip())
    sort_key = lambda ip: struct.unpack("!L", inet_aton(ip))[0]
    analyticsdb_ip_list = sorted(analyticsdb_ip_list, key=sort_key)
    return {"analyticsdb_servers": analyticsdb_ip_list}


def get_context():
    ctx = {}
    ctx["log_level"] = config.get("log-level", "SYS_NOTICE")
    ctx["version"] = config.get("version", "4.0.0")
    ctx.update(json_loads(config.get("orchestrator_info"), dict()))

    ctx["ssl_enabled"] = config.get("ssl_enabled", False)
    ctx["db_user"] = leader_get("db_user")
    ctx["db_password"] = leader_get("db_password")
    ctx["analyticsdb_minimum_diskgb"] = config.get("cassandra-minimum-diskgb")

    ctx.update(servers_ctx())
    ctx.update(analyticsdb_ctx())
    log("CTX: {}".format(ctx))
    ctx.update(json_loads(config.get("auth_info"), dict()))
    return ctx


def render_config(ctx=None, do_check=True):
    if not ctx:
        ctx = get_context()

    return render_and_check(ctx, "analyticsdb.conf",
                            "/etc/contrailctl/analyticsdb.conf", do_check)


def update_charm_status(update_config=True):
    update_config_func = render_config if update_config else None
    result = check_run_prerequisites(CONTAINER_NAME, CONFIG_NAME,
                                     update_config_func, SERVICES_TO_CHECK)
    if not result:
        return

    ctx = get_context()
    missing_relations = []
    if not ctx.get("db_user"):
        # NOTE: Charms don't allow to deploy cassandra in AllowAll mode
        missing_relations.append("contrail-analyticsdb-cluster")
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
    if not ctx.get("keystone_ip"):
        status_set('blocked',
                   'Missing auth info in relation with contrail-controller.')
        return
    # TODO: what should happens if relation departed?

    render_config(ctx, do_check=False)
    run_container(CONTAINER_NAME)
