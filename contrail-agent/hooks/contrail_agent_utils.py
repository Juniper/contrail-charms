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
config = config()


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


def launch_docker_image():
    image_id = None
    orchestrator = config.get("cloud_orchestrator")
    output =  check_output(["docker",
                            "images",
                            ])
    output = output.decode().split('\n')[:-1]
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
        # TODO: read from image config. open only needed ports
        open_port(8085)
        open_port(9090)
        # sudo docker cp contrail-agent:/usr/bin/vrouter-port-control /usr/bin/
    else:
        log("contrail-agent docker image is not available")


def apply_agent_config():
    cmd = '/usr/bin/docker exec contrail-agent contrailctl config sync -c agent'
    check_call(cmd, shell=True)


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


def lb_ctx():
    for rid in relation_ids("contrail-controller"):
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
    if ctx.get("controller_ip") and ctx.get("keystone_ip"):
        if is_already_launched():
            apply_agent_config()
        else:
            launch_docker_image()
