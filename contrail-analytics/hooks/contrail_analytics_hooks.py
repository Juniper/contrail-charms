#!/usr/bin/env python
from subprocess import (
    CalledProcessError,
    check_call,
    check_output
)
import sys

import yaml

from charmhelpers.core.hookenv import (
    Hooks,
    UnregisteredHookError,
    config,
    resource_get,
    log,
    status_set
)

from charmhelpers.fetch import (
    apt_install,
    apt_upgrade
)


from contrail_analytics_utils import (
    fix_hostname,
    write_analytics_config,
    launch_docker_image,
    units
)

PACKAGES = [ "docker.io" ]


hooks = Hooks()
config = config()

@hooks.hook("config-changed")
def config_changed():
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
                         "contrail-analytics"
                         ])
  if result:
      status_set("active", "Unit ready")
  else:
      status_set("blocked", "Control container is not running")

def load_docker_image():
    img_path = resource_get("contrail-analytics")
    check_call(["/usr/bin/docker",
                "load",
                "-i",
                img_path,
                ])


@hooks.hook()
def install():
    fix_hostname()
    apt_upgrade(fatal=True, dist=True)
    apt_install(PACKAGES, fatal=True)
    load_docker_image()
    #launch_docker_image()

@hooks.hook("contrail-control-relation-joined")
def contrail_control_joined():
   print "NUM CONTROL UNITS: ", len(units("contrail-control"))
   if len(units("contrail-control")) == 3:
       config["control-ready"] = True
   write_analytics_config()

@hooks.hook("contrail-analyticsdb-relation-joined")
def contrail_analyticsdb_joined():
   if len(units("contrail-analyticsdb")) == 3:
       config["analyticsdb-ready"] = True
   write_analytics_config()

@hooks.hook("contrail-lb-relation-joined")
def contrail_lb_joined():
   config["lb-ready"] = True
   write_analytics_config()

@hooks.hook("contrail-control-relation-departed")
def contrail_control_departed():
   config["control-ready"] = False

@hooks.hook("contrail-analyticsdb-relation-departed")
def contrail_analyticsdb_departed():
   config["analyticsdb-ready"] = False

@hooks.hook("contrail-lb-relation-departed")
def contrail_lb_departed():
   config["lb-ready"] = False

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
