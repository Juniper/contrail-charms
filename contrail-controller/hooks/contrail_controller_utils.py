import functools
import os
import pwd
import shutil
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
import platform
import json

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
    relation_get,
    unit_get,
    remote_unit,
    ERROR
)

from charmhelpers.core.host import service_restart, service_start

from charmhelpers.core.templating import render

apt_pkg.init()
config = config()


def dpkg_version(pkg):
    try:
        return check_output(["docker",
                              "exec",
                              "contrail-controller",
                              "dpkg-query", "-f", "${Version}\\n", "-W", pkg]).rstrip()
    except CalledProcessError:
        return None


def get_control_ip():
    return gethostbyname(unit_get("private-address"))


def is_already_launched():
    cmd = 'docker ps | grep contrail-controller'
    try:
        output =  check_output(cmd, shell=True)
        return True
    except CalledProcessError:
        return False


def controller_ctx():
    ctx = {}
    """Get the ipaddres of all contrail controller nodes"""
    controller_ip_list = [ gethostbyname(relation_get("private-address", unit, rid))
                                     for rid in relation_ids("controller-cluster")
                                     for unit in related_units(rid) ]
    # add it's own ip address
    controller_ip_list.append(gethostbyname(unit_get("private-address")))
    controller_ip_list = sorted(controller_ip_list, key=lambda ip: struct.unpack("!L", inet_aton(ip))[0])

    multi_tenancy = config.get("multi_tenancy")
    ext_zk_list = yaml.load(config.get("external_zookeeper_servers")) if \
       config.get("external_zookeeper_servers") else []
    ext_rabbitmq_list = yaml.load(config.get("external_rabbitmq_servers")) if \
       config.get("external_rabbitmq_servers") else []
    ext_configdb_list = yaml.load(config.get("external_configdb_servers")) if \
       config.get("external_configdb_servers") else []

    ctx["multi_tenancy"] = multi_tenancy
    ctx["external_zookeeper_servers"] = ext_zk_list
    ctx["external_rabbitmq_servers"] = ext_rabbitmq_list
    ctx["external_configdb_servers"] = ext_configdb_list
    ctx["controller_servers"] = controller_ip_list
    return ctx


def analytics_ctx():
    """Get the ipaddres of all contrail nodes"""
    analytics_ip_list = [ gethostbyname(relation_get("private-address", unit, rid))
                                     for rid in relation_ids("contrail-analytics")
                                     for unit in related_units(rid) ]
    analytics_ip_list = sorted(analytics_ip_list, key=lambda ip: struct.unpack("!L", inet_aton(ip))[0])
    return { "analytics_servers": analytics_ip_list }


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


def config_ctx():
    return {"cloud_orchestrator": config.get("cloud_orchestrator"),
            "default_log_level": config.get("log_level") }


def apply_control_config():
    config["config-applied"] = True
    cmd = '/usr/bin/docker exec contrail-controller contrailctl config sync -c controller'
    check_call(cmd, shell=True)


def open_ports(image_id):
    try:
        result = check_output(["/usr/bin/docker",
                               "inspect",
                               "-f='{{json .Config.ExposedPorts}}'",
                               image_id
                               ])
    except CalledProcessError as e:
        log("error in getting ExposedPorts from image. " + str(e), level=ERROR)
        return
    try:
        ports = json.loads(result)
    except Exception:
        log("error in decoding ExposedPorts from image: " + result, level=ERROR)
        return

    for pp_str in ports:
        pp = pp_str.split('/')
        open_port(pp[0], pp[1].upper())


def launch_docker_image():
    image_id = None
    orchestrator = config.get("cloud_orchestrator")
    output =  check_output(["docker",
                            "images",
                            ])
    output = output.decode().split('\n')[:-1]
    for line in output:
        if "contrail-controller" in line.split()[0]:
            image_id = line.split()[2].strip()
    if image_id:
        log("contrail-controller docker image is not available")
        return

    open_ports(image_id)
    dist = platform.linux_distribution()[2].strip()
    cmd = "/usr/bin/docker "+ \
          "run "+ \
          "--net=host "+ \
          "--cap-add=AUDIT_WRITE "+ \
          "--privileged "+ \
          "--env='CLOUD_ORCHESTRATOR=%s' "%(orchestrator)+ \
          "--volume=/etc/contrailctl:/etc/contrailctl "+ \
          "--name=contrail-controller "
    if dist == "trusty":
        cmd = cmd + "--pid=host "
    cmd = cmd +"-itd "+ image_id
    check_call(cmd, shell=True)


def write_control_config():
    ctx = {}
    ctx.update(config_ctx())
    ctx.update(controller_ctx())
    ctx.update(analytics_ctx())
    ctx.update(identity_admin_ctx())
    render("controller.conf", "/etc/contrailctl/controller.conf", ctx)
    if ctx.get("keystone_ip") and ctx.get("analytics_servers"):
        if is_already_launched():
            apply_control_config()
        else:
            launch_docker_image()
