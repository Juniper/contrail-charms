#!/usr/bin/env python

from subprocess import (
    CalledProcessError,
    check_call,
    check_output
)
import sys
from socket import gethostbyname
import yaml

from charmhelpers.core.hookenv import (
    Hooks,
    UnregisteredHookError,
    config,
    resource_get,
    log,
    status_set,
    related_units,
    relation_get,
    relation_ids,
    relation_type,
    relation_get,
    unit_get,
    remote_unit
)

from charmhelpers.fetch import (
    apt_install,
    apt_upgrade
)

from contrail_control_utils import (
  launch_docker_image,
  write_control_config,
  units
)

PACKAGES = [ "docker.io" ]


hooks = Hooks()
config = config()

@hooks.hook("config-changed")
def config_changed():
    #log_level =  config.get("log_level")
    #set_status()
    return None

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
                         "contrail-controller"
                         ])
  if result:
      status_set("active", "Unit ready")
  else:
      status_set("blocked", "Control container is not running")

def load_docker_image():
    img_path = resource_get("contrail-control")
    check_call(["/usr/bin/docker",
                "load",
                "-i",
                img_path,
                ])

@hooks.hook()
def install():
    apt_upgrade(fatal=True, dist=True)
    apt_install(PACKAGES, fatal=True)
    load_docker_image()
    #launch_docker_image()

@hooks.hook("contrail-lb-relation-joined")
def lb_joined():
    controller_ip_list = [ gethostbyname(relation_get("private-address", unit, rid))
                                     for rid in relation_ids("control-cluster")
                                     for unit in related_units(rid) ]
    # add it's own ip address
    controller_ip_list.append(gethostbyname(unit_get("private-address")))
    write_control_config()

@hooks.hook("control-cluster-relation-joined")
def cluster_joined():
    controller_ip_list = [ gethostbyname(relation_get("private-address", unit, rid))
                                     for rid in relation_ids("control-cluster")
                                     for unit in related_units(rid) ]
    # add it's own ip address
    controller_ip_list.append(gethostbyname(unit_get("private-address")))

@hooks.hook("update-status")
def update_status():
  #set_status()
  status_set("active", "Unit ready")
                
def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log("Unknown hook {} - skipping.".format(e))

if __name__ == "__main__":
    main()
