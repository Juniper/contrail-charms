from socket import gethostbyname
from subprocess import CalledProcessError, check_output

import apt_pkg
from apt_pkg import version_compare

from charmhelpers.core.hookenv import (
    related_units,
    relation_get,
    relation_ids
)

from charmhelpers.core.templating import render

apt_pkg.init()

def dpkg_version(pkg):
    try:
        return check_output(["dpkg-query", "-f", "${Version}\\n", "-W", pkg]).rstrip()
    except CalledProcessError:
        return None

CONTRAIL_VERSION = dpkg_version("python-contrail")
OPENSTACK_VERSION = dpkg_version("neutron-server")

def contrail_api_ctx():
    ctxs = [ { "api_server": vip if vip \
                 else gethostbyname(relation_get("private-address", unit, rid)),
               "api_port": port }
             for rid in relation_ids("contrail-api")
             for unit, port, vip in
             ((unit, relation_get("port", unit, rid), relation_get("vip", unit, rid))
              for unit in related_units(rid))
             if port ]
    return ctxs[0] if ctxs else {}

def identity_admin_ctx():
    ctxs = [ { "auth_host": gethostbyname(hostname),
               "auth_port": relation_get("service_port", unit, rid),
               "admin_user": relation_get("service_username", unit, rid),
               "admin_password": relation_get("service_password", unit, rid),
               "admin_tenant_name": relation_get("service_tenant_name", unit, rid) }
             for rid in relation_ids("identity-admin")
             for unit, hostname in
             ((unit, relation_get("service_hostname", unit, rid)) for unit in related_units(rid))
             if hostname ]
    return ctxs[0] if ctxs else {}

def write_plugin_config():
    ctx = {}
    ctx.update(contrail_api_ctx())
    ctx.update(identity_admin_ctx())
    if version_compare(OPENSTACK_VERSION, "1:2015.1~") >= 0:
        ctx["authtoken"] = True
    if version_compare(OPENSTACK_VERSION, "2:7.0.0") >= 0:
        ctx["authtoken_creds"] = True
    render("ContrailPlugin.ini",
           "/etc/neutron/plugins/opencontrail/ContrailPlugin.ini",
           ctx, "root", "neutron", 0o440)
