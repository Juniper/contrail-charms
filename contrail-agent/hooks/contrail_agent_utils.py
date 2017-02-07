import functools
import os
import pwd
import shutil
from socket import gethostbyname, gethostname
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
    remote_unit
)

from charmhelpers.core.host import service_restart, service_start

from charmhelpers.core.templating import render

apt_pkg.init()

def is_already_launched():
    cmd = 'docker ps | grep contrail-agent'
    try:
        output =  check_output(cmd, shell=True)
        return True
    except CalledProcessError:
        return False

def dpkg_version(pkg):
    try:
        return check_output(["docker",
                              "exec",
                              "contrail-agent",
                              "dpkg-query",
                              "-f", "${Version}\\n", "-W", pkg]).rstrip()
    except CalledProcessError:
        return None

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

def units(relation):
    """Return a list of units for the specified relation"""
    return [ unit for rid in relation_ids(relation)
                  for unit in related_units(rid) ]

def launch_docker_image():
    image_id = None
    orchestrator = config.get("cloud_orchestrator")
    output =  check_output(["docker",
                            "images",
                            ])
    output = output.decode()split('\n')[:-1]
    for line in output:
        if "contrail-agent" in line.split()[0]:
            image_id = line.split()[2].strip()
    if image_id:
        check_call(["/usr/bin/docker",
                    "run",
                    "--net=host",
                    "--cap-add=AUDIT_WRITE",
                    "--privileged",
                    "--env='CLOUD_ORCHESTRATOR=%s'"%(orchestrator),
                    "--volume=/lib/modules:/lib/modules",
                    "--volume=/usr/src:/usr/src",
                    "--volume=/etc/contrailctl:/etc/contrailctl",
                    "--name=contrail-agent",
                    "-itd",
                    image_id
                    ])
        log("contrail-agent docker image is not available")

def config_get(key):
    try:
        return config[key]
    except KeyError:
        return None

def identity_admin_ctx():
   if not relation_get("service_hostname"):
       return {}
   for rid in relation_ids("identity-admin"):
      for unit in related_units(rid):
          hostname = relation_get("service_hostname", unit, rid)
          return { "keystone_ip": gethostbyname(hostname),
                   "keystone_public_port": relation_get("service_port", unit, rid),
                   "keystone_admin_user": relation_get("service_username", unit, rid),
                   "keystone_admin_password": relation_get("service_password", unit, rid),
                   "keystone_admin_tenant": relation_get("service_tenant_name", unit, rid),
                   "keystone_auth_protocol": relation_get("service_protocol", unit, rid)
                 }

def lb_ctx():
   if config_get("lb-ready"):
    for rid in relation_ids("contrail-lb"):
     for unit in related_units(rid):
      return {"controller_ip": relation_get("private-address", unit, rid) }
   return {}

def remove_juju_bridges():
    cmd = "scripts/remove-juju-bridges.sh"
    #check_call("remove-juju-bridges.sh", cwd="scripts")
    check_call(cmd)

def write_agent_config():
    ctx = {}
    ctx.update({"cloud_orchestrator": config.get("cloud_orchestrator")})
    ctx.update(identity_admin_ctx())
    ctx.update(lb_ctx())
    render("agent.conf", "/etc/contrailctl/agent.conf", ctx)
    if config_get("lb-ready") and config_get("identity-admin-ready"):
        print "LAUNCHING THE AGENT CONTAINER"
        launch_docker_image()
