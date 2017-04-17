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
    is_leader,
    status_set,
    relation_get,
    relation_ids,
    relation_type,
    relation_set,
    unit_get,
    remote_unit,
    application_version_set
)

from charmhelpers.fetch import (
    apt_install,
    apt_upgrade,
    apt_update
)

from contrail_controller_utils import (
  launch_docker_image,
  write_control_config,
  get_control_ip,
  dpkg_version,
  is_already_launched,
  apply_control_config
)

PACKAGES = [ "python", "python-yaml", "python-apt", "docker-engine" ]

hooks = Hooks()
config = config()


def set_status():
    try:
        # set the application version
        if is_already_launched():
            version  = dpkg_version("contrail-control")
            application_version_set(version)
        result = check_output(["/usr/bin/docker",
                               "inspect",
                               "-f",
                               "{{.State.Running}}",
                               "contrail-controller"
                               ])
    except CalledProcessError:
        status_set("waiting", "Waiting for container to be launched")
        return
    if result:
        status_set("active", "Unit ready")
    else:
        status_set("blocked", "Container is not running")


def load_docker_image():
    img_path = resource_get("contrail-controller")
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
    load_docker_image()
    #launch_docker_image()


@hooks.hook("config-changed")
def config_changed():
    set_status()
    write_control_config()

    if is_leader():
        settings = {
            "private-address": get_control_ip(),
            "port": 8082,
            "multi-tenancy": config.get("multi_tenancy")
        }
        for rid in relation_ids("contrail-controller"):
            relation_set(relation_id=rid, relation_settings=settings)


@hooks.hook("contrail-controller-relation-joined")
def contrail_controller_joined():
    settings = {
        "private-address": get_control_ip(),
        "port": 8082
    }
    if is_leader():
        settings["multi-tenancy"] = config.get("multi_tenancy")
    relation_set(relation_settings=settings)


@hooks.hook("controller-cluster-relation-joined")
def cluster_joined():
    write_control_config()


@hooks.hook("contrail-analytics-relation-joined")
@hooks.hook("contrail-analytics-relation-departed")
@hooks.hook("contrail-analytics-relation-broken")
def analytics_relation():
    write_control_config()


@hooks.hook("identity-admin-relation-changed")
@hooks.hook("identity-admin-relation-departed")
@hooks.hook("identity-admin-relation-broken")
def identity_admin_changed():
    if not relation_get("service_hostname"):
        log("Relation not ready")
    write_control_config()


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
