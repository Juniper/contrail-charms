from socket import inet_aton, gethostname
import struct
import time

import apt_pkg

from charmhelpers.core.hookenv import (
    config,
    related_units,
    relation_ids,
    relation_get,
    status_set,
    status_get,
    leader_get,
    log,
    local_unit,
    ERROR,
)

from common_utils import (
    get_ip,
    check_run_prerequisites,
    run_container,
    json_loads,
    render_and_check,
    update_services_status
)

import docker_utils


apt_pkg.init()
config = config()


CONTAINER_NAME = "contrail-controller"
CONFIG_NAME = "controller"
SERVICES_TO_CHECK = ["contrail-control", "contrail-api", "contrail-webui"]
RABBITMQ_USER = "contrail"
RABBITMQ_VHOST = "contrail"


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
    ctx["log_level"] = config.get("log-level", "SYS_NOTICE")
    ctx["flow_export_rate"] = config.get("flow-export-rate")
    ctx["version"] = config.get("version", "4.0.0")
    ctx["auth_mode"] = config.get("auth-mode")
    ctx["cloud_admin_role"] = config.get("cloud-admin-role")
    ctx["global_read_only_role"] = config.get("global-read-only-role")
    ctx["configdb_minimum_diskgb"] = config.get("cassandra-minimum-diskgb")
    ctx.update(json_loads(config.get("orchestrator_info"), dict()))

    ctx["ssl_enabled"] = config.get("ssl_enabled", False)

    ctx["db_user"] = leader_get("db_user")
    ctx["db_password"] = leader_get("db_password")

    ctx["rabbitmq_user"] = RABBITMQ_USER
    ctx["rabbitmq_vhost"] = RABBITMQ_VHOST
    if config.get("use-external-rabbitmq"):
        ctx["rabbitmq_password"] = config.get("rabbitmq_password")
        ctx["rabbitmq_hosts"] = config.get("rabbitmq_hosts")
    else:
        ctx["rabbitmq_password"] = leader_get("rabbitmq_password_int")
        ctx["rabbitmq_hosts"] = None

    ips = json_loads(leader_get("controller_ip_list"), list())
    ctx["controller_servers"] = ips
    ctx["config_seeds"] = ips
    ctx["analytics_servers"] = get_analytics_list()
    log("CTX: " + str(ctx))
    ctx.update(json_loads(config.get("auth_info"), dict()))
    return ctx


def update_charm_status(update_config=True, force=False):

    def _render_config(ctx=None, do_check=True):
        if not ctx:
            ctx = get_context()
        changed = render_and_check(
            ctx, "controller.conf",
            "/etc/contrailctl/controller.conf", do_check)
        return (force or changed)

    update_config_func = _render_config if update_config else None
    result = check_run_prerequisites(CONTAINER_NAME, CONFIG_NAME,
                                     update_config_func, SERVICES_TO_CHECK)

    # hack for 4.1 due to fat containers do not call provision_control
    _, message = status_get()
    identity = json_loads(config.get("auth_info"), dict())
    if (identity and 'contrail-control' in message
            and '(No BGP configuration for self)' in message):
        try:
            ip = get_ip()
            bgp_asn = '64512'
            # register control node to config api server (no auth)
            cmd = [
                '/usr/share/contrail-utils/provision_control.py',
                '--api_server_ip', ip, '--router_asn', bgp_asn,
                '--admin_user', identity.get("keystone_admin_user"),
                '--admin_password', identity.get("keystone_admin_password"),
                '--admin_tenant_name', identity.get("keystone_admin_tenant")]
            docker_utils.docker_exec(CONTAINER_NAME, cmd, shell=True)
            # register control node as a BGP speaker without md5 (no auth)
            cmd = [
                '/usr/share/contrail-utils/provision_control.py',
                '--api_server_ip', ip, '--router_asn', bgp_asn,
                '--host_name', gethostname(), '--host_ip', ip, '--oper', 'add',
                '--admin_user', identity.get("keystone_admin_user"),
                '--admin_password', identity.get("keystone_admin_password"),
                '--admin_tenant_name', identity.get("keystone_admin_tenant")]
            docker_utils.docker_exec(CONTAINER_NAME, cmd, shell=True)
            # wait a bit
            time.sleep(8)
            update_services_status(CONTAINER_NAME, SERVICES_TO_CHECK)
        except Exception as e:
            log("Can't provision control: {}".format(e), level=ERROR)
    # hack for contrail-api that is started at inapropriate moment to keystone
    if (identity and 'contrail-api' in message
            and '(Generic Connection:Keystone[] connection down)' in message):
        try:
            cmd = ['systemctl', 'restart', 'contrail-api']
            docker_utils.docker_exec(CONTAINER_NAME, cmd, shell=True)
            # wait a bit
            time.sleep(8)
            update_services_status(CONTAINER_NAME, SERVICES_TO_CHECK)
        except Exception as e:
            log("Can't restart contrail-api: {}".format(e), level=ERROR)

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
    if not ctx.get("rabbitmq_password"):
        status_set('blocked',
                   'Missing RabbitMQ info in external relations.')
        return
    if not ctx.get("keystone_ip"):
        status_set('blocked',
                   'Missing auth info in relation with contrail-auth.')
        return
    # TODO: what should happens if relation departed?

    _render_config(ctx, do_check=False)
    run_container(CONTAINER_NAME, ctx.get("cloud_orchestrator"))
