#!/usr/bin/env python3
from subprocess import (
    CalledProcessError,
    check_call,
    check_output
)
import sys

#import yaml
from socket import gaierror, gethostbyname, gethostname

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
    units,
    dpkg_version,
    is_already_launched
)

PACKAGES = [ "python", "python-yaml", "python-apt", "docker.io" ]
#PACKAGES = [ "python", "python-yaml", "python-apt", "docker-engine" ]

hooks = Hooks()
config = config()

@hooks.hook("config-changed")
def config_changed():
    set_status()
    return None

def config_get(key):
    try:
        return config[key]
    except KeyError:
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
      status_set("blocked", "Control container is not running")

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
    #setup_docker_env()
    #apt_update(fatal=False)
    apt_install(PACKAGES, fatal=True)
    load_docker_image()
    #launch_docker_image()

@hooks.hook("contrail-control-relation-joined")
def contrail_control_joined():
   print ("NUM CONTROL UNITS: ", len(units("contrail-control")))
   if len(units("contrail-control")) == config.get("control_units"):
       config["control-ready"] = True
   write_analytics_config()

@hooks.hook("contrail-analyticsdb-relation-joined")
def contrail_analyticsdb_joined():
   print ("NUM ANALYTICSDB UNITS: ", len(units("contrail-analyticsdb")))
   if len(units("contrail-analyticsdb")) == config.get("analyticsdb_units"):
       config["analyticsdb-ready"] = True
   write_analytics_config()

@hooks.hook("contrail-lb-relation-joined")
def contrail_lb_joined():
   config["lb-ready"] = True
   print ("LB RELATION JOINED")
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

@hooks.hook("identity-admin-relation-changed")
def identity_admin_changed():
   if not relation_get("service_hostname"):
        log("Keystone relation not ready")
        return
   print ("KEYSTONE RELATION JOINED")
   config["identity-admin-ready"] = True
   write_analytics_config()

@hooks.hook("identity-admin-relation-departed")
@hooks.hook("identity-admin-relation-broken")
def identity_admin_broken():
   config["identity-admin-ready"] = False

@hooks.hook("analytics-cluster-relation-joined")
def analytics_cluster_joined():
    analytics_ip_list = [ gethostbyname(relation_get("private-address", unit, rid))
                                     for rid in relation_ids("analytics-cluster")
                                     for unit in related_units(rid) ]
    # add it's own ip address
    analytics_ip_list.append(gethostbyname(unit_get("private-address")))
    print ("CLUSTER RELATION JOINED: ", analytics_ip_list)
    if len(analytics_ip_list) == config.get("control_units"):
        config["analytics-ready"] = True
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
