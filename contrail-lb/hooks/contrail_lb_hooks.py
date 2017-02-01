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
    related_units,
    application_version_set
)

from charmhelpers.fetch import (
    apt_install,
    apt_upgrade
)

from contrail_lb_utils import (
  launch_docker_image,
  write_lb_config,
  units,
  dpkg_version,
  is_already_launched
)

PACKAGES = [ "docker.io" ]


hooks = Hooks()
config = config()

def set_status():
    try:
        # set the application version
        if is_already_launched():
            version  = dpkg_version()
            application_version_set(version)
        result = check_output(["/usr/bin/docker",
                             "inspect",
                             "-f",
                             "{{.State.Running}}",
                             "contrail-lb"
                             ])
    except CalledProcessError:
        status_set("waiting", "Waiting for the container to be launched")
        return
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

@hooks.hook()
def install():
    apt_upgrade(fatal=True, dist=True)
    apt_install(PACKAGES, fatal=True)
    load_docker_image()
    config["contrail-control-ready"] = False
    config["contrail-analytics-ready"] = False
    #launch_docker_image()
                
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
    if len(units("contrail-control")) == config.get("control_units"):
        config["contrail-control-ready"] = True
    write_lb_config()

@hooks.hook("contrail-analytics-relation-joined")
def contrail_analytics_joined():
    if len(units("contrail-analytics")) == config.get("analytics_units"):
        config["contrail-analytics-ready"] = True
    write_lb_config()

@hooks.hook("contrail-control-relation-departed")
def contrail_control_departed():
    config["contrail-control-ready"] = False

@hooks.hook("contrail-analytics-relation-departed")
def contrail_analytics_departed():
    config["contrail-analytics-ready"] = False

@hooks.hook("update-status")
def update_status():
  set_status()
  #status_set("active", "Unit ready")

def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log("Unknown hook {} - skipping.".format(e))

if __name__ == "__main__":
    main()
