import functools
import os
import pwd
import shutil
import socket
from socket import gaierror, gethostbyname, gethostname, inet_aton
import struct
from subprocess import (
    CalledProcessError,
    check_call,
    check_output
)
from time import sleep, time

import apt_pkg
import yaml
import platform

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
    unit_get
)

from charmhelpers.core.host import service_restart, service_start

from charmhelpers.core.templating import render

apt_pkg.init()
config = config()


def dpkg_version(pkg):
    try:
        return check_output(["docker",
                              "exec",
                              "contrail-analytics",
                              "dpkg-query", "-f", "${Version}\\n", "-W", pkg]).rstrip()
    except CalledProcessError:
        return None


def fix_hostname():
    hostname = gethostname()
    try:
        gethostbyname(hostname)
    except gaierror:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 53))  # connecting to a UDP address doesn't send packets
        local_ip_address = s.getsockname()[0]
        check_call(["sed", "-E", "-i", "-e",
                    "/127.0.0.1[[:blank:]]+/a \\\n"+ local_ip_address+" " + hostname,
                    "/etc/hosts"])


def lb_ctx():
    lb_vip = None
    for rid in relation_ids("contrail-lb"):
        for unit in related_units(rid):
            lb_vip = gethostbyname(relation_get("private-address", unit, rid))
    return { "lb_vip": lb_vip}


def controller_ctx():
    """Get the ipaddress of all contrail control nodes"""
    controller_ip_list = [ gethostbyname(relation_get("private-address", unit, rid))
                               for rid in relation_ids("contrail-controller")
                               for unit in related_units(rid) ]
    controller_ip_list = sorted(controller_ip_list, key=lambda ip: struct.unpack("!L", inet_aton(ip))[0])
    return { "controller_servers": controller_ip_list }


def analytics_ctx():
    """Get the ipaddress of all analytics control nodes"""
    analytics_ip_list = [ gethostbyname(relation_get("private-address", unit, rid))
                                     for rid in relation_ids("analytics-cluster")
                                     for unit in related_units(rid) ]
    # add it's own ip address
    analytics_ip_list.append(gethostbyname(unit_get("private-address")))
    analytics_ip_list = sorted(analytics_ip_list, key=lambda ip: struct.unpack("!L", inet_aton(ip))[0])
    return { "analytics_servers": analytics_ip_list }


def analyticsdb_ctx():
    """Get the ipaddress of all contrail analyticsdb nodes"""
    analyticsdb_ip_list = [ gethostbyname(relation_get("private-address", unit, rid))
                            for rid in relation_ids("contrail-analyticsdb")
                            for unit in related_units(rid) ]
    analyticsdb_ip_list = sorted(analyticsdb_ip_list, key=lambda ip: struct.unpack("!L", inet_aton(ip))[0])
    return { "analyticsdb_servers": analyticsdb_ip_list }


def identity_admin_ctx():
    ctxs = [ { "keystone_ip": gethostbyname(hostname),
               "keystone_public_port": relation_get("service_port", unit, rid),
               "keystone_admin_user": relation_get("service_username", unit, rid),
               "keystone_admin_password": relation_get("service_password", unit, rid),
               "keystone_admin_tenant": relation_get("service_tenant_name", unit, rid),
               "keystone_auth_protocol": relation_get("service_protocol", unit, rid) }
             for rid in relation_ids("identity-admin")
             for unit, hostname in
             ((unit, relation_get("service_hostname", unit, rid)) for unit in related_units(rid))
             if hostname ]
    return ctxs[0] if ctxs else {}


def apply_analytics_config():
    cmd = '/usr/bin/docker exec contrail-analytics contrailctl config sync -c analytics'
    check_call(cmd, shell=True)


def launch_docker_image():
    image_id = None
    orchestrator = config.get("cloud_orchestrator")
    output =  check_output(["docker",
                            "images",
                            ])
    output = output.decode().split('\n')[:-1]
    for line in output:
        if "contrail-analytics" in line.split()[0]:
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
              "--name=contrail-analytics "
        if dist == "trusty":
            cmd = cmd + "--pid=host "
        cmd = cmd +"-itd "+ image_id
        check_call(cmd, shell=True)
    else:
        log("contrail-analytics docker image is not available")


def is_already_launched():
    cmd = 'docker ps | grep -w contrail-analytics'
    try:
        output =  check_output(cmd, shell=True)
        return True
    except CalledProcessError:
        return False


def write_analytics_config():
    """Render the configuration entries in the analytics.conf file"""
    ctx = {}
    ctx.update({"cloud_orchestrator": config.get("cloud_orchestrator")})
    ctx.update(controller_ctx())
    ctx.update(analytics_ctx())
    ctx.update(analyticsdb_ctx())
    ctx.update(lb_ctx())
    ctx.update(identity_admin_ctx())
    render("analytics.conf", "/etc/contrailctl/analytics.conf", ctx)
    if config_get("controller-ready") and config_get("lb-ready") \
      and config_get("identity-admin-ready") and config_get("analyticsdb-ready") \
      and config_get("analytics-ready"):
        if is_already_launched():
            apply_analytics_config()
        else:
            launch_docker_image()
