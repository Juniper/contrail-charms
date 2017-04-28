import socket
from socket import gaierror, gethostbyname, gethostname, inet_aton
import struct
from subprocess import check_call
import time

import apt_pkg
import json
import platform


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


CONTAINER_NAME = "contrail-analyticsdb"
CONFIG_NAME = "analyticsdb"


def fix_hostname():
    hostname = gethostname()
    try:
        gethostbyname(hostname)
    except gaierror:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # connecting to a UDP address doesn't send packets
        s.connect(('8.8.8.8', 53))
        local_ip_address = s.getsockname()[0]
        check_call(["sed", "-E", "-i", "-e",
            ("/127.0.0.1[[:blank:]]+/a \\\n"
             + local_ip_address
             + " "
             + hostname),
            "/etc/hosts"])


def servers_ctx():
    controller_ip_list = []
    analytics_ip_list = []
    for rid in relation_ids("contrail-analyticsdb"):
        for unit in related_units(rid):
            ip = gethostbyname(relation_get("private-address", unit, rid))
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
        gethostbyname(relation_get("private-address", unit, rid))
        for rid in relation_ids("analyticsdb-cluster")
        for unit in related_units(rid)]
    # add it's own ip address
    analyticsdb_ip_list.append(gethostbyname(unit_get("private-address")))
    sort_key = lambda ip: struct.unpack("!L", inet_aton(ip))[0]
    analyticsdb_ip_list = sorted(analyticsdb_ip_list, key=sort_key)
    return {"analyticsdb_servers": analyticsdb_ip_list}


def identity_admin_ctx():
    auth_info = config.get("auth_info")
    return (json.loads(auth_info) if auth_info else {})


def get_context():
    ctx = {}
    ctx["cloud_orchestrator"] = config.get("cloud_orchestrator")
    ctx.update(servers_ctx())
    ctx.update(analyticsdb_ctx())
    ctx.update(identity_admin_ctx())
    if ctx.get("controller_servers"):
        ctx["lb_vip"] = ctx["controller_servers"][0]
    return ctx


def render_config(ctx=None):
    if not ctx:
        ctx = get_context()
    render("analyticsdb.conf", "/etc/contrailctl/analyticsdb.conf", ctx)


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
    if not ctx.get("analytics_servers"):
        missing_relations.append("contrail-analytics")
    if missing_relations:
        status_set('waiting',
                   'Missing relations: ' + ', '.join(missing_relations))
        return
    if not ctx.get("cloud_orchestrator"):
        status_set('waiting',
                   'Missing cloud_orchestrator info in relation '
                   'with contrail-controller.')
        return
    if not ctx.get("keystone_ip"):
        status_set('waiting',
                   'Missing auth info in relation with contrail-controller.')
        return
    # TODO: what should happens if relation departed?

    render_config(ctx)
    args = []
    if platform.linux_distribution()[2].strip() == "trusty":
        args.append("--pid=host")
    launch_docker_image(CONTAINER_NAME, args)
    # TODO: find a way to do not use 'sleep'
    time.sleep(5)

    version = dpkg_version(CONTAINER_NAME, "contrail-nodemgr")
    application_version_set(version)
    status_set("active", "Unit ready")
