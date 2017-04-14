#!/usr/bin/env python

from subprocess import (
    CalledProcessError,
    check_call,
    check_output
)
import sys
from socket import gethostbyname

from charmhelpers.core.hookenv import (
    Hooks,
    UnregisteredHookError,
    config,
    resource_get,
    log,
    status_set,
    relation_get,
    relation_ids,
    relation_type,
    relation_get,
    application_version_set
)

from charmhelpers.fetch import (
    apt_install,
    apt_upgrade,
    apt_update
)

from contrail_analyticsdb_utils import (
    fix_hostname,
    write_analyticsdb_config,
    launch_docker_image,
    dpkg_version,
    is_already_launched
)

PACKAGES = [ "python", "python-yaml", "python-apt", "docker-engine" ]


hooks = Hooks()
config = config()


@hooks.hook("config-changed")
def config_changed():
    set_status()
    write_analyticsdb_config()
    return None


def set_status():
    try:
        # set the application version
        if is_already_launched():
            version  = dpkg_version("contrail-nodemgr")
            application_version_set(version)
        result = check_output(["/usr/bin/docker",
                               "inspect",
                               "-f",
                               "{{.State.Running}}",
                               "contrail-analyticsdb"
                               ])
    except CalledProcessError:
        status_set("waiting", "Waiting for the container to be launched")
        return
    if result:
        status_set("active", "Unit ready")
    else:
        status_set("blocked", "Control container is not running")


def load_docker_image():
    img_path = resource_get("contrail-analyticsdb")
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
    fix_hostname()
    apt_upgrade(fatal=True, dist=True)
    setup_docker_env()
    apt_update(fatal=False)
    apt_install(PACKAGES, fatal=True)
    load_docker_image()
    #launch_docker_image()


@hooks.hook("contrail-control-relation-joined")
def control_joined():
    config["control-ready"] = True
    write_analyticsdb_config()


@hooks.hook("contrail-lb-relation-joined")
def lb_joined():
    config["lb-ready"] = True
    write_analyticsdb_config()


@hooks.hook("contrail-control-relation-departed")
def control_departed():
    config["control-ready"] = False


@hooks.hook("contrail-lb-relation-departed")
def lb_departed():
    config["lb-ready"] = False


@hooks.hook("contrail-analytics-relation-joined")
def analytics_joined():
    config["analytics-ready"] = True
    write_analyticsdb_config()


@hooks.hook("contrail-analytics-relation-departed")
@hooks.hook("contrail-analytics-relation-broken")
def control_departed():
    config["analytics-ready"] = False


@hooks.hook("identity-admin-relation-changed")
def identity_admin_changed():
    if not relation_get("service_hostname"):
        log("Keystone relation not ready")
        return
    config["identity-admin-ready"] = True
    write_analyticsdb_config()


@hooks.hook("identity-admin-relation-departed")
@hooks.hook("identity-admin-relation-broken")
def identity_admin_broken():
    config["identity-admin-ready"] = False


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
