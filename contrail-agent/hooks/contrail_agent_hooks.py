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
    relation_get,
    application_version_set
)

from charmhelpers.fetch import (
    apt_install,
    apt_upgrade,
    apt-update
)

from contrail_agent_utils import (
    remove_juju_bridges,
    launch_docker_image,
    write_agent_config,
    is_already_launched,
    dpkg_version
)

PACKAGES = [ "docker.engine" ]


hooks = Hooks()
config = config()


@hooks.hook("config-changed")
def config_changed():
    log_level =  config.get("log_level")
    #set_status()
    write_agent_config()
    return None


def set_status():
    try:
       # set the application version
       if is_already_launched():
           version  = dpkg_version("contrail-vrouter-agent")
           application_version_set(version)
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


def setup_docker_env():
    import platform
    cmd = 'curl -fsSL https://apt.dockerproject.org/gpg | sudo apt-key add -'
    check_output(cmd, shell=True)
    dist = platform.linux_distribution()[2].strip()
    cmd = "add-apt-repository "+ \
          "\"deb https://apt.dockerproject.org/repo/ " + \
          "ubuntu-%s "%(dist) +\
          "main\""
    check_output(cmd, shell=True)


@hooks.hook()
def install():
    apt_upgrade(fatal=True, dist=True)
    setup_docker_env()
    apt_update(fatal=False)
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


@hooks.hook("contrail-lb-relation-joined")
def lb_relation_joined():
    config["lb-ready"] = True
    write_agent_config()


@hooks.hook("contrail-lb-relation-departed")
def lb_relation_departed():
    config["lb-ready"] = False


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
