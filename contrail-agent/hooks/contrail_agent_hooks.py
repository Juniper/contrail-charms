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
    relation_get
)

from charmhelpers.fetch import (
    apt_install,
    apt_upgrade
)

from contrail_agent_utils import (
    remove_juju_bridges,
    launch_docker_image,
    write_agent_config
)

PACKAGES = [ "docker.io" ]


hooks = Hooks()
config = config()

@hooks.hook("config-changed")
def config_changed():
    log_level =  config.get("log_level")
    #set_status()
    return None

def set_status():
    try:
       result = check_output(["/usr/bin/docker",
                              "inspect",
                              "-f",
                              "{{.State.Running}}",
                              "contrail-agent"
                              ])
    except CalledProcessError:
        status_set("waiting", "Waiting for the container to be launched")
        return
    if result:
        status_set("active", "Unit ready")
    else:
        status_set("blocked", "Control container is not running")

def load_docker_image():
    img_path = resource_get("contrail-agent")
    check_call(["/usr/bin/docker",
                "load",
                "-i",
                img_path,
                ])


@hooks.hook()
def install():
    apt_upgrade(fatal=True, dist=True)
    apt_install(PACKAGES, fatal=True)
    remove_juju_bridges()
    load_docker_image()
    #launch_docker_image()

@hooks.hook("identity-admin-relation-changed")
def identity_admin_changed():
   if not relation_get("service_hostname"):
        log("Relation not ready")
        return
   config["identity-admin-ready"] = True
   write_agent_config()

@hooks.hook("identity-admin-relation-departed")
@hooks.hook("identity-admin-relation-broken")
def identity_admin_departed():
    config["identity-admin-ready"] = False

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
