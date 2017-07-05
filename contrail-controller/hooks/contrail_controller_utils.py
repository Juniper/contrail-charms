from socket import inet_aton
import struct

import apt_pkg

from charmhelpers.core.hookenv import (
    config,
    related_units,
    relation_ids,
    relation_get,
    status_set,
    leader_get,
    log,
    open_port,
    local_unit,
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


CONTAINER_NAME = "contrail-controller"
CONFIG_NAME = "controller"
SERVICES_TO_CHECK = ["contrail-control", "contrail-api", "contrail-webui"]


def get_controller_ips():
    controller_ips = dict()
    for rid in relation_ids("controller-cluster"):
        for unit in related_units(rid):
            ip = relation_get("unit-address", unit, rid)
            controller_ips[unit] = ip
    # add it's own ip address
    controller_ips[local_unit()] = get_ip()
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
    ctx["auth_mode"] = config.get("auth-mode")
    ctx["cloud_admin_role"] = config.get("cloud-admin-role")
    ctx["global_read_only_role"] = config.get("global-read-only-role")
    ctx.update(json_loads(config.get("orchestrator_info"), dict()))

    ssl_ca = decode_cert("ssl_ca")
    ctx["ssl_ca"] = ssl_ca
    ctx["ssl_cert"] = decode_cert("ssl_cert")
    ctx["ssl_key"] = decode_cert("ssl_key")
    ctx["ssl_enabled"] = (ssl_ca is not None and len(ssl_ca) > 0)

    ctx["db_user"] = leader_get("db_user")
    ctx["db_password"] = leader_get("db_password")

    ctx["rabbitmq_user"] = leader_get("rabbitmq_user")
    ctx["rabbitmq_password"] = leader_get("rabbitmq_password")
    ctx["rabbitmq_vhost"] = leader_get("rabbitmq_vhost")

    ips = json_loads(leader_get("controller_ip_list"), list())
    ctx["controller_servers"] = ips
    ctx["config_seeds"] = ips
    ctx["analytics_servers"] = get_analytics_list()
    log("CTX: " + str(ctx))
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

    render("controller.conf", "/etc/contrailctl/controller.conf", ctx)


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
        missing_relations.append("contrail-controller-cluster")
    if not ctx.get("analytics_servers"):
        missing_relations.append("contrail-analytics")
    if get_ip() not in ctx.get("controller_servers"):
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

    render_config(ctx)
    for port in ("8082", "8080", "8143"):
        open_port(port, "TCP")

    run_container(CONTAINER_NAME, "contrail-control")
