import json
from socket import gethostbyname
from subprocess import CalledProcessError, check_output

import apt_pkg

from charmhelpers.core.hookenv import (
    config,
    related_units,
    relation_get,
    relation_ids,
    application_version_set,
    status_set,
)

from charmhelpers.core.templating import render

apt_pkg.init()
config = config()


def set_status():
    version = dpkg_version("neutron-plugin-contrail")
    application_version_set(version)
    cmd = 'service neutron-server status'
    out = check_output(cmd, shell=True)
    if 'running' in out.decode().split()[1].strip():
        status_set("active", "Unit is ready")
    else:
        status_set("waiting", "neutron server is not running")


def dpkg_version(pkg):
    try:
        return check_output(["dpkg-query",
                             "-f",
                             "${Version}\\n",
                             "-W",
                             pkg]).rstrip()
    except CalledProcessError:
        return None


def contrail_api_ctx():
    for rid in relation_ids("contrail-controller"):
        for unit in related_units(rid):
            port = relation_get("port", unit, rid)
            if not port:
                continue
            ip = gethostbyname(relation_get("private-address", unit, rid))
            return {"api_server": ip, "api_port": port}
    return {}


def identity_admin_ctx():
    auth_info = config.get("auth_info")
    return (json.loads(auth_info) if auth_info else {})


def write_plugin_config():
    ctx = {}
    ctx.update(contrail_api_ctx())
    ctx.update(identity_admin_ctx())
    render("ContrailPlugin.ini",
           "/etc/neutron/plugins/opencontrail/ContrailPlugin.ini",
           ctx, "root", "neutron", 0o440)
