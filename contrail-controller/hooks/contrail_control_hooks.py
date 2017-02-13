#!/usr/bin/env python3

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
    relation_set,
    unit_get,
    remote_unit,
    application_version_set
)

from charmhelpers.fetch import (
    apt_install,
    apt_upgrade
)

from contrail_control_utils import (
  launch_docker_image,
  write_control_config,
  units,
  get_control_ip,
  dpkg_version,
  is_already_launched
)

PACKAGES = [ "python", "python-yaml", "python-apt", "docker.io" ]


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

@hooks.hook("contrail-api-relation-joined")
def api_joined():
  controller_ip = get_control_ip()
  settings = { "private-address": controller_ip,
               "port": 8082
             }
  for rid in relation_ids("contrail-api"):
      relation_set(relation_id=rid, relation_settings=settings)
  
@hooks.hook("contrail-lb-relation-joined")
def lb_joined():
    controller_ip_list = [ gethostbyname(relation_get("private-address", unit, rid))
                                     for rid in relation_ids("control-cluster")
                                     for unit in related_units(rid) ]
    # add it's own ip address
    controller_ip_list.append(gethostbyname(unit_get("private-address")))
    print ("LB RELATION JOINED: ", controller_ip_list)
    config["lb-ready"] = True
    write_control_config()

@hooks.hook("control-cluster-relation-joined")
def cluster_joined():
    controller_ip_list = [ gethostbyname(relation_get("private-address", unit, rid))
                                     for rid in relation_ids("control-cluster")
                                     for unit in related_units(rid) ]
    # add it's own ip address
    controller_ip_list.append(gethostbyname(unit_get("private-address")))
    print ("CLUSTER RELATION JOINED: ", controller_ip_list)
    if len(controller_ip_list) == config.get("control_units"):
        config["control-ready"] = True
    write_control_config()

@hooks.hook("contrail-analytics-relation-joined")
def analytics_joined():
    analytics_ip_list = [ gethostbyname(relation_get("private-address", unit, rid))
                                     for rid in relation_ids("contrail-analytics")
                                     for unit in related_units(rid) ]
    print ("ANALYTICS_RELATION JOINED: ", analytics_ip_list)
    if len(analytics_ip_list) == config.get("control_units"):
        config["analytics-ready"] = True
    write_control_config()

@hooks.hook("contrail-analytics-relation-departed")
@hooks.hook("contrail-analytics-relation-broken")
def analytics_departed():
    config["config-ready"] = False

@hooks.hook("identity-admin-relation-changed")
def identity_admin_changed():
   if not relation_get("service_hostname"):
        log("Relation not ready")
        return
   config["identity-admin-ready"] = True
   write_control_config()

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
