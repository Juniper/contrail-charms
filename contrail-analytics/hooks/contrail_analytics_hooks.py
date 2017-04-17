#!/usr/bin/env python
from subprocess import (
    CalledProcessError,
    check_call,
    check_output
)
import sys

from socket import gaierror, gethostbyname, gethostname

from charmhelpers.core.hookenv import (
    Hooks,
    UnregisteredHookError,
    config,
    resource_get,
    log,
    status_set,
    relation_get,
    relation_ids,
    unit_get,
    application_version_set
)

from charmhelpers.fetch import (
    apt_install,
    apt_upgrade,
    apt_update
)


from contrail_analytics_utils import (
    fix_hostname,
    write_analytics_config,
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
    write_analytics_config()
    return None


def set_status():
  try:
      if is_already_launched():
          version = dpkg_version("contrail-analytics")
          application_version_set(version)
      result = check_output(["/usr/bin/docker",
                             "inspect",
                             "-f",
                             "{{.State.Running}}",
                             "contrail-analytics"
                             ])
  except CalledProcessError:
      status_set("waiting", "Waiting for container to be launched")
      return
  if result:
      status_set("active", "Unit ready")
  else:
      status_set("blocked", "Container is not running")


def load_docker_image():
    img_path = resource_get("contrail-analytics")
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


@hooks.hook("contrail-controller-relation-joined")
@hooks.hook("contrail-controller-relation-departed")
def contrail_controller_relation():
    write_analytics_config()


@hooks.hook("contrail-controller-relation-changed")
def contrail_controller_changed():
    multi_tenancy = relation_get("multi_tenancy")
    if multi_tenancy is not None:
        config["multi_tenancy"] = multi_tenancy
    write_analytics_config()


@hooks.hook("contrail-analyticsdb-relation-joined")
@hooks.hook("contrail-analyticsdb-relation-departed")
def contrail_analyticsdb_relation():
    write_analytics_config()


@hooks.hook("identity-admin-relation-changed")
@hooks.hook("identity-admin-relation-departed")
@hooks.hook("identity-admin-relation-broken")
def identity_admin_relation():
    if not relation_get("service_hostname"):
        log("Keystone relation not ready")
    write_analytics_config()


@hooks.hook("analytics-cluster-relation-joined")
def analytics_cluster_joined():
    write_analytics_config()


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
