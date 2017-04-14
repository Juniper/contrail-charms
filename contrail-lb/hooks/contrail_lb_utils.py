import functools
import os
import pwd
import shutil
import platform
from socket import gethostbyname, inet_aton
import struct
from subprocess import (
    CalledProcessError,
    check_call,
    check_output
)
from time import sleep, time

import apt_pkg
import yaml

try:
    import netaddr
    import netifaces
except ImportError:
    pass

from charmhelpers.core.hookenv import (
    config,
    log,
    related_units,
    relation_get,
    relation_ids,
    relation_type,
    remote_unit,
    related_units
)

from charmhelpers.core.host import service_restart, service_start

from charmhelpers.core.templating import render

apt_pkg.init()
config = config()


def is_already_launched():
    cmd = 'docker ps | grep contrail-lb'
    try:
        output =  check_output(cmd, shell=True)
        return True
    except CalledProcessError:
        return False


def dpkg_version():
    try:
        output=check_output(["docker",
                             "images"])
        output = output.decode().split('\n')[:-1]
        for line in output:
            if "contrail-lb" in line.split()[0]:
                tag = line.split()[1].strip()
        return tag
    except CalledProcessError:
        return None


def identity_admin_ctx():
    ctxs = [ { "auth_host": gethostbyname(hostname),
               "auth_port": relation_get("service_port", unit, rid),
               "admin_user": relation_get("service_username", unit, rid),
               "admin_password": relation_get("service_password", unit, rid),
               "admin_tenant_name": relation_get("service_tenant_name", unit, rid),
               "auth_region": relation_get("service_region", unit, rid) }
             for rid in relation_ids("identity-admin")
             for unit, hostname in
             ((unit, relation_get("service_hostname", unit, rid)) for unit in related_units(rid))
             if hostname ]
    return ctxs[0] if ctxs else {}


def launch_docker_image():
    image_id = None
    orchestrator = config.get("cloud_orchestrator")
    output =  check_output(["docker",
                            "images",
                            ])
    output = output.decode().split('\n')[:-1]
    for line in output:
        if "contrail-lb" in line.split()[0]:
            image_id = line.split()[2].strip()
    if image_id:
        dist = platform.linux_distribution()[2].strip()
        cmd = "/usr/bin/docker "+ \
              "run "+ \
              "--net=host "+ \
              "--cap-add=AUDIT_WRITE "+ \
              "--privileged "+ \
              "--env='CLOUD_ORCHESTRATOR=%s' "%(orchestrator)+ \
              "--volume=/etc/contrailctl:/etc/contrailctl "+ \
              "--name=contrail-lb "
        if dist == "trusty":
            cmd = cmd + "--pid=host "
        cmd = cmd +"-itd "+ image_id
        check_call(cmd, shell=True)
    else:
        log("contrail-lb docker image is not available")


def is_already_launched():
    cmd = 'docker ps | grep contrail-lb'
    try:
        output =  check_output(cmd, shell=True)
        return True
    except CalledProcessError:
        return False


def controller_ctx():
    """Get the ipaddres of all contrail control nodes"""
    controller_ip_list = [ gethostbyname(relation_get("private-address", unit, rid))
                               for rid in relation_ids("contrail-controller")
                               for unit in related_units(rid) ]
    controller_ip_list = sorted(controller_ip_list, key=lambda ip: struct.unpack("!L", inet_aton(ip))[0])
    return { "controller_servers": controller_ip_list }


def analytics_ctx():
    """Get the ipaddres of all contrail analytics nodes"""
    analytics_ip_list = [ gethostbyname(relation_get("private-address", unit, rid))
                               for rid in relation_ids("contrail-analytics")
                               for unit in related_units(rid) ]
    analytics_ip_list = sorted(analytics_ip_list, key=lambda ip: struct.unpack("!L", inet_aton(ip))[0])
    return { "analytics_servers": analytics_ip_list }


def apply_lb_config():
    cmd = '/usr/bin/docker exec contrail-lb contrailctl config sync -c lb -F'
    check_call(cmd, shell=True)


def write_lb_config():
    """Render the configuration entries in the lb.conf file"""
    ctx = {}
    ctx.update({"cloud_orchestrator": config.get("cloud_orchestrator")})
    ctx.update(controller_ctx())
    ctx.update(analytics_ctx())
    render("lb.conf", "/etc/contrailctl/lb.conf", ctx)
    if config.get("contrail-controller-ready") and config.get("contrail-analytics-ready"):
        if is_already_launched():
            apply_lb_config()
        else:
            launch_docker_image()
