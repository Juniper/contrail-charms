from socket import gethostbyname, inet_aton
import struct
import time

import apt_pkg
import yaml
import platform
import six

from charmhelpers.core.hookenv import (
    config,
    related_units,
    relation_get,
    relation_ids,
    unit_get,
    status_set,
    application_version_set,
)
from charmhelpers.core.templating import render

from docker_utils import (
    is_container_launched,
    is_container_present,
    apply_config_in_container,
    launch_docker_image,
    dpkg_version,
    get_docker_image_id
)

apt_pkg.init()
config = config()


CONTAINER_NAME = "contrail-analytics"
CONFIG_NAME = "analytics"


def lb_ctx():
    for rid in relation_ids("contrail-controller"):
        for unit in related_units(rid):
            return {"lb_vip": gethostbyname(relation_get("private-address", unit, rid))}
    return {}


def controller_ctx():
    """Get the ipaddress of all contrail control nodes"""
    mt = config.get("multi_tenancy")
    if mt is None:
        return {}
    controller_ip_list = [gethostbyname(relation_get("private-address", unit, rid))
                          for rid in relation_ids("contrail-controller")
                          for unit in related_units(rid)]
    controller_ip_list = sorted(controller_ip_list, key=lambda ip: struct.unpack("!L", inet_aton(ip))[0])
    return {
        "multi_tenancy": yaml.load(mt) if isinstance(mt, six.string_types) else mt,
        "controller_servers": controller_ip_list,
    }


def analytics_ctx():
    """Get the ipaddress of all analytics control nodes"""
    analytics_ip_list = [ gethostbyname(relation_get("private-address", unit, rid))
                          for rid in relation_ids("analytics-cluster")
                          for unit in related_units(rid) ]
    # add it's own ip address
    analytics_ip_list.append(gethostbyname(unit_get("private-address")))
    analytics_ip_list = sorted(analytics_ip_list, key=lambda ip: struct.unpack("!L", inet_aton(ip))[0])
    return {"analytics_servers": analytics_ip_list}


def analyticsdb_ctx():
    """Get the ipaddress of all contrail analyticsdb nodes"""
    analyticsdb_ip_list = [gethostbyname(relation_get("private-address", unit, rid))
                           for rid in relation_ids("contrail-analyticsdb")
                           for unit in related_units(rid)]
    analyticsdb_ip_list = sorted(analyticsdb_ip_list, key=lambda ip: struct.unpack("!L", inet_aton(ip))[0])
    return {"analyticsdb_servers": analyticsdb_ip_list}


def identity_admin_ctx():
    ctxs = [{"keystone_ip": gethostbyname(hostname),
             "keystone_public_port": relation_get("service_port", unit, rid),
             "keystone_admin_user": relation_get("service_username", unit, rid),
             "keystone_admin_password": relation_get("service_password", unit, rid),
             "keystone_admin_tenant": relation_get("service_tenant_name", unit, rid),
             "keystone_auth_protocol": relation_get("service_protocol", unit, rid)}
            for rid in relation_ids("identity-admin")
            for unit, hostname in
            ((unit, relation_get("service_hostname", unit, rid)) for unit in related_units(rid))
            if hostname]
    return ctxs[0] if ctxs else {}


def get_context():
    ctx = {}
    ctx.update({"cloud_orchestrator": config.get("cloud_orchestrator")})
    ctx.update(controller_ctx())
    ctx.update(analytics_ctx())
    ctx.update(analyticsdb_ctx())
    ctx.update(lb_ctx())
    ctx.update(identity_admin_ctx())
    return ctx


def render_config(ctx=None):
    if not ctx:
        ctx = get_context()
    render("analytics.conf", "/etc/contrailctl/analytics.conf", ctx)


def update_charm_status(update_config=True):
    if is_container_launched(CONTAINER_NAME):
        status_set("active", "Unit ready")
        if update_config:
            render_config()
            apply_config_in_container(CONTAINER_NAME, CONFIG_NAME)
        return

    if is_container_present(CONTAINER_NAME):
        status_set(
            "error",
            "Container is present but is not running. Run or remove it.")
        return

    image_id = get_docker_image_id(CONTAINER_NAME)
    if not image_id:
        status_set('waiting', 'Awaiting for container resource')
        return

    ctx = get_context()
    missing_relations = []
    if not ctx.get("controller_servers"):
        missing_relations.append("contrail-controller")
    if not ctx.get("analyticsdb_servers"):
        missing_relations.append("contrail-analyticsdb")
    if not ctx.get("keystone_ip"):
        missing_relations.append("identity")
    if missing_relations:
        status_set('waiting',
                   'Missing relations: ' + ', '.join(missing_relations))
        return
    # TODO: what should happens if relation departed?

    render_config(ctx)
    args = []
    if platform.linux_distribution()[2].strip() == "trusty":
        args.append("--pid=host")
    launch_docker_image(CONTAINER_NAME, args)
    # TODO: find a way to do not use 'sleep'
    time.sleep(5)

    version = dpkg_version(CONTAINER_NAME, "contrail-analytics")
    application_version_set(version)
    status_set("active", "Unit ready")
