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
    remote_unit
)

from charmhelpers.core.host import service_restart, service_start

from charmhelpers.core.templating import render

apt_pkg.init()


config = config()

def retry(f=None, timeout=10, delay=2):
    """Retry decorator.

    Provides a decorator that can be used to retry a function if it raises
    an exception.

    :param timeout: timeout in seconds (default 10)
    :param delay: retry delay in seconds (default 2)

    Examples::

        # retry fetch_url function
        @retry
        def fetch_url():
            # fetch url

        # retry fetch_url function for 60 secs
        @retry(timeout=60)
        def fetch_url():
            # fetch url
    """
    if not f:
        return functools.partial(retry, timeout=timeout, delay=delay)
    @functools.wraps(f)
    def func(*args, **kwargs):
        start = time()
        error = None
        while True:
            try:
                return f(*args, **kwargs)
            except Exception as e:
                error = e
            elapsed = time() - start
            if elapsed >= timeout:
                raise error
            remaining = timeout - elapsed
            if delay <= remaining:
                sleep(delay)
            else:
                sleep(remaining)
                raise error
    return func

def contrail_api_ctx():
    ip = config.get("contrail-api-ip")
    if ip:
        port = config.get("contrail-api-port")
        return { "api_server": ip,
                 "api_port": port if port is not None else 8082 }

    ctxs = [ { "api_server": gethostbyname(relation_get("private-address", unit, rid)),
               "api_port": port }
             for rid in relation_ids("contrail-api")
             for unit, port in
             ((unit, relation_get("port", unit, rid)) for unit in related_units(rid))
             if port ]
    return ctxs[0] if ctxs else {}

def contrail_discovery_ctx():
    ip = config.get("discovery-server-ip")
    if ip:
        return { "discovery_server": ip,
                 "discovery_port": 5998 }

    ctxs = [ { "discovery_server": vip if vip \
                 else gethostbyname(relation_get("private-address", unit, rid)),
               "discovery_port": port }
             for rid in relation_ids("contrail-discovery")
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
               "admin_tenant_name": relation_get("service_tenant_name", unit, rid),
               "auth_region": relation_get("service_region", unit, rid) }
             for rid in relation_ids("identity-admin")
             for unit, hostname in
             ((unit, relation_get("service_hostname", unit, rid)) for unit in related_units(rid))
             if hostname ]
    return ctxs[0] if ctxs else {}

def is_already_launched():
    cmd = 'docker ps | grep contrail-controller'
    try:
        output =  check_output(cmd, shell=True)
        return True
    except CalledProcessError:
        return False

def controller_ctx():
    """Get the ipaddres of all contrail control nodes"""
    controller_ip_list = [ gethostbyname(relation_get("private-address", unit, rid))
                                     for rid in relation_ids("control-cluster")
                                     for unit in related_units(rid) ]
    # add it's own ip address
    controller_ip_list.append(gethostbyname(unit_get("private-address")))
    controller_ip_list = sorted(controller_ip_list, key=lambda ip: struct.unpack("!L", inet_aton(ip))[0])
    return { "controller_servers": controller_ip_list }

def lb_ctx():
    lb_vip = None
    for rid in relation_ids("contrail-lb"):
        for unit in related_units(rid):
           lb_vip = gethostbyname(relation_get("private-address", unit, rid))
    return { "controller_ip": lb_vip,
             "analytics_ip": lb_vip
           }

def config_get(key):
    try:
        return config[key]
    except KeyError:
        return None

def apply_control_config():
        config["config-applied"] = True
        cmd = '/usr/bin/docker exec contrail-controller contrailctl config sync -c controller -F -t configure'
        check_call(cmd, shell=True)

def units(relation):
    """Return a list of units for the specified relation"""
    return [ unit for rid in relation_ids(relation)
                  for unit in related_units(rid) ]

def launch_docker_image():
    image_id = None
    output =  check_output(["docker",
                            "images",
                            ])
    output = output.split('\n')[:-1]
    for line in output:
        if "contrail-controller" in line.split()[0]:
            image_id = line.split()[2].strip()
    if image_id:
        check_call(["/usr/bin/docker",
                    "run",
                    "--net=host",
                    "--pid=host",
                    "--cap-add=AUDIT_WRITE",
                    "--privileged",
                    "--env='CLOUD_ORCHESTRATOR=kubernetes'", 
                    "--name=contrail-controller",
                    "--volume=/etc/contrailctl:/etc/contrailctl",
                    "-itd",
                    image_id 
                   ])
    else:
        log("contrail-controller docker image is not available")

def write_control_config():
    ctx = {}
    ctx.update(controller_ctx())
    ctx.update(lb_ctx())
    render("controller.conf", "/etc/contrailctl/controller.conf", ctx)
    if not is_already_launched():
        #apply_control_config()
        print "LAUNCHING THE CONTROLLER CONTAINER"
        print "CTX: ", ctx
        launch_docker_image()
