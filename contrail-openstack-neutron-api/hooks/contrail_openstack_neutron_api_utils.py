from base64 import b64decode
import os
import json
from subprocess import CalledProcessError, check_output

import apt_pkg

from charmhelpers.core.hookenv import (
    config,
    related_units,
    relation_get,
    relation_ids,
    application_version_set,
    status_set,
    log,
    ERROR,
)
from charmhelpers.core.host import (
    write_file,
    service_running,
)
from charmhelpers.core.templating import render

apt_pkg.init()
config = config()


def set_status():
    version = dpkg_version("neutron-plugin-contrail")
    application_version_set(version)
    if service_running("neutron-server"):
        status_set("active", "Unit is ready")
    else:
        status_set("waiting", "neutron server is not running")


def dpkg_version(pkg):
    try:
        return check_output(
            ["dpkg-query", "-f", "${Version}\\n", "-W", pkg]).rstrip()
    except CalledProcessError:
        return None


def contrail_api_ctx():
    ip = config.get("api_ip")
    port = config.get("api_port")
    api_vip = config.get("api_vip")
    if api_vip:
        ip = api_vip
    return (ip, port) if ip and port else (None, None)


def identity_admin_ctx():
    auth_info = config.get("auth_info")
    return (json.loads(auth_info) if auth_info else {})


def decode_cert(key):
    val = config.get(key)
    if not val:
        return None
    try:
        return b64decode(val)
    except Exception as e:
        log("Couldn't decode certificate from config['{}']: {}".format(
            key, str(e)), level=ERROR)
    return None


def get_context():
    ctx = {}
    ctx.update(contrail_api_ctx())
    ssl_ca = decode_cert("ssl_ca")
    ctx["ssl_ca"] = ssl_ca
    ctx["ssl_enabled"] = (ssl_ca is not None and len(ssl_ca) > 0)
    log("CTX: " + str(ctx))

    ctx.update(identity_admin_ctx())
    return ctx


def _save_file(path, data):
    if data:
        fdir = os.path.dirname(path)
        if not os.path.exists(fdir):
            os.makedirs(fdir)
        write_file(path, data, perms=0o444)
    elif os.path.exists(path):
        os.remove(path)


def write_plugin_config():
    ctx = get_context()

    # NOTE: store files in the same paths as in tepmlates
    ssl_ca = ctx["ssl_ca"]
    _save_file("/etc/contrail/ssl/certs/ca-cert.pem", ssl_ca)

    render("ContrailPlugin.ini",
           "/etc/neutron/plugins/opencontrail/ContrailPlugin.ini",
           ctx, "root", "neutron", 0o440)
