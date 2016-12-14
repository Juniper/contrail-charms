#!/usr/bin/env python

from subprocess import (
    CalledProcessError,
    check_call,
    check_output
)
import sys

import yaml
from socket import gethostbyname

from charmhelpers.core.hookenv import (
    Hooks,
    UnregisteredHookError,
    config,
    resource_get,
    log,
    status_set,
    relation_set,
    unit_get,
    relation_get,
    relation_ids,
    related_units
)

from charmhelpers.fetch import (
    apt_install,
    apt_upgrade
)

from contrail_lb_utils import (
  write_lb_config
)

PACKAGES = [ "docker.io" ]


hooks = Hooks()
config = config()

launched = False

def config_get(key):
    try:
        return config[key]
    except KeyError:
        return None

def set_status():
  result = check_output(["/usr/bin/docker",
                         "inspect",
                         "-f",
                         "{{.State.Running}}",
                         "contrail-lb"
                         ])
  if result:
      status_set("active", "Unit ready")
  else:
      status_set("blocked", "Control container is not running")

def load_docker_image():
    img_path = resource_get("contrail-lb")
    check_call(["/usr/bin/docker",
                "load",
                "-i",
                img_path,
                ])

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

@hooks.hook()
def install():
    apt_upgrade(fatal=True, dist=True)
    apt_install(PACKAGES, fatal=True)
    load_docker_image()
    #config["launched"] = False
    launch_docker_image()
                
@hooks.hook("config-changed")
def config_changed():
    set_status()
    return None

@hooks.hook("contrail-lb-relation-joined")
def contrail_lb_joined():
    ipaddress = gethostbyname(unit_get("private-address"))
    settings = { "contrail-lb-vip": ipaddress }
    relation_set(relation_settings=settings)

@hooks.hook("contrail-control-relation-joined")
def contrail_control_joined():
    config["contrail-control-ready"] = True
    write_lb_config()

@hooks.hook("contrail-analytics-relation-joined")
def contrail_analytics_joined():
    config["contrail-analytics-ready"] = True
    write_lb_config()
    #if not config["launched"]:
    #    launch_docker_image()
    #    config["launched"] = True
    #return

@hooks.hook("contrail-control-relation-departed")
def contrail_control_departed():
    config["contrail-control-ready"] = False

@hooks.hook("contrail-analytics-relation-departed")
def contrail_analytics_departed():
    config["contrail-analytics-ready"] = False

@hooks.hook("update-status")
def update_status():
  set_status()

def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log("Unknown hook {} - skipping.".format(e))

if __name__ == "__main__":
    main()
