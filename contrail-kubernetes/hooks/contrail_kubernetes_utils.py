import apt_pkg
import os

from charmhelpers.core.hookenv import (
    config,
)
from charmhelpers.core.templating import render

apt_pkg.init()
config = config()


def write_configs():
    ctx = _get_context()

    os.makedirs('/opt/cni/bin')
    os.makedirs('/etc/cni/net.d')
    os.makedirs('/var/lib/contrail/ports/vm')
    os.makedirs('/var/log/contrail/cni/')

    render("kube_cni.conf", "/etc/etc/10-contrail.conf",
           ctx, "root", "contrail", 0o440)


def _get_context():
    ctx = {}

    ip = config.get("api_vip")
    if not ip:
        ip = config.get("api_ip")
    ctx["api_server"] = ip
    ctx["api_port"] = config.get("api_port")

    return ctx
