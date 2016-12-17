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
    remote_unit,
    related_units
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
        if "contrail-lb" in line.split()[0]:
            image_id = line.split()[2].strip()
    if image_id:
        check_call(["/usr/bin/docker",
                    "run",
                    "--net=host",
                    "--pid=host",
                    "--cap-add=AUDIT_WRITE",
                    "--privileged",
                    "--env='CLOUD_ORCHESTRATOR=kubernetes'",
                    "--volume=/etc/contrailctl:/etc/contrailctl",
                    "--name=contrail-lb",
                    "-itd",
                    image_id
                   ])
    else:
        log("contrail-lb docker image is not available")

def is_already_launched():
    cmd = 'docker ps | grep contrail-lb'
    try:
        output =  check_output(cmd, shell=True)
        return True
    except CalledProcessError:
        return False

def write_lb_config():
    """Render the configuration entries in the lb.conf file"""
    ctx = {}
    ctx.update(controller_ctx())
    ctx.update(analytics_ctx())
    render("lb.conf", "/etc/contrailctl/lb.conf", ctx)
    print "write_lb_config control: ", config_get("contrail-control-ready")
    print "write_lb_config analytics: ", config_get("contrail-analytics-ready")
    print "CTX: ", ctx
    if config_get("contrail-control-ready") and config_get("contrail-analytics-ready") \
         and not is_already_launched():
        print "LAUNCHING THE LB CONTAINER"
        launch_docker_image()
        #apply_lb_config()

def controller_ctx():
    """Get the ipaddres of all contrail control nodes"""
    controller_ip_list = [ gethostbyname(relation_get("private-address", unit, rid))
                               for rid in relation_ids("contrail-control")
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

def config_get(key):
    try:
        return config[key]
    except KeyError:
        return None
