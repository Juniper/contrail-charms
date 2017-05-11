import os
from socket import gaierror, gethostbyname, gethostname, inet_aton
import struct
from subprocess import check_call, check_output
import time

import apt_pkg
import json
import platform
import netifaces

from charmhelpers.core.hookenv import (
    config,
    related_units,
    relation_get,
    relation_ids,
    status_set,
    application_version_set,
)
from charmhelpers.core.host import write_file
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


def get_ip(iface=None):
    if not iface:
        if hasattr(netifaces, 'gateways'):
            iface = netifaces.gateways()['default'][netifaces.AF_INET][1]
        else:
            data = check_output("ip route | grep ^default", shell=True).split()
            iface = data[data.index('dev') + 1]
    ip = netifaces.ifaddresses(iface)[netifaces.AF_INET][0]['addr']
    return ip


def fix_hostname():
    hostname = gethostname()
    try:
        gethostbyname(hostname)
    except gaierror:
        ip = get_ip()
        check_call(["sed", "-E", "-i", "-e",
            ("/127.0.0.1[[:blank:]]+/a \\\n" + ip + " " + hostname),
            "/etc/hosts"])


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


def identity_admin_ctx():
    auth_info = config.get("auth_info")
    return (json.loads(auth_info) if auth_info else {})


def get_context():
    ctx = {}
    ctx["cloud_orchestrator"] = config.get("cloud_orchestrator")

    ssl_ca = config.get("ssl_ca")
    ctx["ssl_ca"] = ssl_ca
    ctx["ssl_cert"] = config.get("ssl_cert")
    ctx["ssl_key"] = config.get("ssl_key")
    ctx["ssl_enabled"] = (ssl_ca is not None and len(ssl_ca) > 0)

    ctx.update(servers_ctx())
    ctx.update(analyticsdb_ctx())
    ctx.update(identity_admin_ctx())
    return ctx


def _save_file(path, data):
    if data:
        fdir = os.path.dirname(path)
        if not os.path.exists(fdir):
            os.makedirs(fdir)
        write_file(path, data, perms=0o400)
    elif os.path.exists(path):
        os.remove(path)


def render_config(ctx=None):
    if not ctx:
        ctx = get_context()

    # NOTE: store files in default paths cause no way to pass this path to
    # some of components (sandesh)
    ssl_ca = ctx["ssl_ca"]
    _save_file("/etc/contrailctl/ssl/ca-cert.pem", ssl_ca)
    ssl_cert = ctx["ssl_cert"]
    _save_file("/etc/contrailctl/ssl/server.pem", ssl_cert)
    ssl_key = ctx["ssl_key"]
    _save_file("/etc/contrailctl/ssl/server-privkey.pem", ssl_key)

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
        status_set('blocked', 'Awaiting for container resource')
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
    if not ctx.get("keystone_ip"):
        status_set('blocked',
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
