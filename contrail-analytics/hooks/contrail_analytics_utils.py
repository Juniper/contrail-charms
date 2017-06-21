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
)
from charmhelpers.core.templating import render

from common_utils import (
    get_ip,
    decode_cert,
    save_file,
    check_run_prerequisites,
    run_container,
    json_loads,
)

apt_pkg.init()
config = config()


CONTAINER_NAME = "contrail-analytics"
CONFIG_NAME = "analytics"
SERVICES_TO_CHECK = ["contrail-collector", "contrail-analytics-api"]


def controller_ctx():
    """Get the ipaddress of all contrail control nodes"""
    auth_mode = config.get("auth_mode")
    if auth_mode is None:
        # NOTE: auth_mode must be transmitted by controller
        return {}

    controller_ip_list = []
    for rid in relation_ids("contrail-analytics"):
        for unit in related_units(rid):
            if unit.startswith("contrail-controller"):
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
    analytics_ip_list.append(get_ip())
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
    ctx.update(json_loads(config.get("orchestrator_info"), dict()))

    ssl_ca = decode_cert("ssl_ca")
    ctx["ssl_ca"] = ssl_ca
    ctx["ssl_cert"] = decode_cert("ssl_cert")
    ctx["ssl_key"] = decode_cert("ssl_key")
    ctx["ssl_enabled"] = (ssl_ca is not None and len(ssl_ca) > 0)

    ctx["db_user"] = config.get("db_user")
    ctx["db_password"] = config.get("db_password")

    ctx["rabbitmq_user"] = config.get("rabbitmq_user")
    ctx["rabbitmq_password"] = config.get("rabbitmq_password")
    ctx["rabbitmq_vhost"] = config.get("rabbitmq_vhost")

    ctx.update(controller_ctx())
    ctx.update(analytics_ctx())
    ctx.update(analyticsdb_ctx())
    ctx.update(json_loads(config.get("auth_info"), dict()))
    return ctx


def render_config(ctx=None):
    if not ctx:
        ctx = get_context()

    # NOTE: store files in default paths cause no way to pass this path to
    # some of components (sandesh)
    ssl_ca = ctx["ssl_ca"]
    save_file("/etc/contrailctl/ssl/ca-cert.pem", ssl_ca)
    ssl_cert = ctx["ssl_cert"]
    save_file("/etc/contrailctl/ssl/server.pem", ssl_cert)
    ssl_key = ctx["ssl_key"]
    save_file("/etc/contrailctl/ssl/server-privkey.pem", ssl_key)

    render("analytics.conf", "/etc/contrailctl/analytics.conf", ctx)


def update_charm_status(update_config=True):
    update_config_func = render_config if update_config else None
    result = check_run_prerequisites(CONTAINER_NAME, CONFIG_NAME,
                                     update_config_func, SERVICES_TO_CHECK)
    if not result:
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
    if not ctx.get("db_user"):
        # NOTE: Charms don't allow to deploy cassandra in AllowAll mode
        status_set('blocked',
                   'Missing DB user/password info in '
                   'relation with contrail-controller.')
    if not ctx.get("rabbitmq_user"):
        # NOTE: Charms don't allow to deploy rabbitmq with guest access
        status_set('blocked',
                   'Missing rabbitmq user/password info in '
                   'relation with contrail-controller.')
    # TODO: what should happens if relation departed?

    render_config(ctx)
    open_port(8081, "TCP")

    run_container(CONTAINER_NAME, "contrail-analytics")
