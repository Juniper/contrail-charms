#!/usr/bin/env python

import os
from socket import gethostbyname
import sys

from apt_pkg import version_compare
import json
import uuid
import yaml

from charmhelpers.core.hookenv import (
    Hooks,
    UnregisteredHookError,
    config,
    is_leader,
    leader_get,
    leader_set,
    log,
    relation_get,
    relation_ids,
    relation_set,
    related_units,
)

from charmhelpers.core.host import (
    restart_on_change,
    service_restart
)

from charmhelpers.fetch import (
    apt_install,
    apt_upgrade,
    configure_sources
)
from subprocess import (
    CalledProcessError,
)
from neutron_contrail_utils import (
    get_openstack_version,
    configure_vrouter,
    disable_vrouter_vgw,
    drop_caches,
    enable_vrouter_vgw,
    fix_nodemgr,
    ifdown,
    ifup,
    modprobe,
    provision_local_metadata,
    provision_vrouter,
    unprovision_local_metadata,
    unprovision_vrouter,
    write_nodemgr_config,
    write_vnc_api_config,
    write_vrouter_config,
    write_vrouter_vgw_interfaces,
    set_status
)

PACKAGES = ["python", "python-yaml", "python-apt",
            "python-netaddr", "python-netifaces", "python-jinja2",
            "contrail-vrouter-dkms", "contrail-vrouter-agent",
            "contrail-vrouter-common"]

PACKAGES_DKMS_INIT = ["contrail-vrouter-init"]
PACKAGES_DPDK_INIT = ["contrail-vrouter-dpdk-init"]

hooks = Hooks()
config = config()


@hooks.hook()
def install():
    configure_sources(True, "install-sources", "install-keys")
    apt_upgrade(fatal=True, dist=True)
    packages = list()
    packages.extend(PACKAGES)
    # TODO: support dpdk config option
    packages.extend(PACKAGES_DKMS_INIT)
    apt_install(packages, fatal=True)

    os.chmod("/etc/contrail", 0o755)
    os.chown("/etc/contrail", 0, 0)
    fix_nodemgr()

    try:
        modprobe("vrouter")
    except CalledProcessError:
        log("vrouter kernel module failed to load,"
            " clearing pagecache and retrying")
        drop_caches()
        modprobe("vrouter")
    modprobe("vrouter", True, True)
    configure_vrouter()


def units(relation):
    """Return a list of units for the specified relation"""
    return [unit for rid in relation_ids(relation)
                 for unit in related_units(rid)]


def check_local_metadata():
    if not is_leader():
        return

    if not config.get("vrouter-provisioned"):
        if leader_get("local-metadata-provisioned"):
            # impossible to know if current hook is firing because
            # relation or leader is being removed lp #1469731
            if not relation_ids("cluster"):
                unprovision_local_metadata()
            leader_set({"local-metadata-provisioned": ""})
        return

    if config["local-metadata-server"]:
        if not leader_get("local-metadata-provisioned"):
            provision_local_metadata()
            leader_set({"local-metadata-provisioned": True})
    elif leader_get("local-metadata-provisioned"):
        unprovision_local_metadata()
        leader_set({"local-metadata-provisioned": ""})


def check_vrouter():
    # check relation dependencies
    if config.get("controller-ready") \
       and config.get("analytics-servers") \
       and config.get("auth_info"):
        if not config.get("vrouter-provisioned"):
            provision_vrouter()
            config["vrouter-provisioned"] = True
    elif config.get("vrouter-provisioned"):
        unprovision_vrouter()
        config["vrouter-provisioned"] = False


@hooks.hook("config-changed")
def config_changed():
    configure_local_metadata()
    configure_virtual_gateways()
    write_config()
    check_vrouter()
    check_local_metadata()
    set_status()


def configure_local_metadata():
    if config["local-metadata-server"]:
        if "local-metadata-secret" not in config:
            # generate secret
            secret = str(uuid.uuid4())
            config["local-metadata-secret"] = secret
            settings = {"metadata-shared-secret": secret}
            # inform relations
            for rid in relation_ids("neutron-plugin"):
                relation_set(relation_id=rid, relation_settings=settings)
    else:
        if "local-metadata-secret" in config:
            # remove secret
            del config["local-metadata-secret"]
            settings = {"metadata-shared-secret": None}
            # inform relations
            for rid in relation_ids("neutron-plugin"):
                relation_set(relation_id=rid, relation_settings=settings)


def configure_virtual_gateways():
    gateways = config.get("virtual-gateways")
    previous_gateways = config.get("virtual-gateways-prev")
    if gateways == previous_gateways:
        return

    # create/destroy virtual gateway interfaces according to new value
    interfaces = {gateway["interface"]: set(gateway["subnets"])
                  for gateway in yaml.safe_load(gateways)} \
                 if gateways else {}
    previous_interfaces = {gateway["interface"]: set(gateway["subnets"])
                           for gateway in yaml.safe_load(previous_gateways)} \
                          if previous_gateways else {}
    ifaces = [
        interface for interface, subnets in previous_interfaces.iteritems()
        if interface not in interfaces
        or subnets != interfaces[interface]]
    if ifaces:
        ifdown(ifaces)

    write_vrouter_vgw_interfaces()

    ifaces = [interface for interface, subnets in interfaces.iteritems()
              if interface not in previous_interfaces
              or subnets != previous_interfaces[interface]]
    if ifaces:
        ifup(ifaces)

    if interfaces:
        enable_vrouter_vgw()
    else:
        disable_vrouter_vgw()

    config["virtual-gateways-prev"] = gateways


@hooks.hook("contrail-controller-relation-changed")
def contrail_controller_changed():
    config["analytics-servers"] = relation_get("analytics-server")
    if not relation_get("port"):
        log("Relation not ready")
        return

    write_vnc_api_config()
    control_node_relation()
    config["controller-ready"] = True
    check_vrouter()
    check_local_metadata()


@hooks.hook("contrail-controller-relation-departed")
def contrail_controller_node_departed():
    if not units("contrail-controller"):
        del config["analytics-servers"]
        config["controller-ready"] = False
        check_vrouter()
        check_local_metadata()
    write_vnc_api_config()
    control_node_relation()


@restart_on_change({"/etc/contrail/contrail-vrouter-agent.conf":
                        ["contrail-vrouter-agent"],
                    "/etc/contrail/contrail-vrouter-nodemgr.conf":
                        ["contrail-vrouter-nodemgr"]})
def control_node_relation():
    write_vrouter_config()
    write_nodemgr_config()


@hooks.hook("identity-admin-relation-changed")
def identity_admin_changed():
    if not relation_get("service_hostname"):
        log("Relation not ready")
        return

    auth_info = {
        "auth_host": gethostbyname(relation_get("service_hostname")),
        "auth_port": relation_get("service_port"),
        "admin_user": relation_get("service_username"),
        "admin_password": relation_get("service_password"),
        "admin_tenant_name": relation_get("service_tenant_name"),
        "auth_region": relation_get("service_region")}
    auth_info = json.dumps(auth_info)
    config["auth_info"] = auth_info

    write_vnc_api_config()
    check_vrouter()
    check_local_metadata()


@hooks.hook("identity-admin-relation-departed")
def identity_admin_departed():
    if not units("identity-admin"):
        del config["auth_info"]
        check_vrouter()
        check_local_metadata()
    write_vnc_api_config()


@hooks.hook("neutron-plugin-relation-joined")
def neutron_plugin_joined():
    # create plugin config
    section = []
    if version_compare(get_openstack_version(), "1:2015.1~") < 0:
        if version_compare(get_openstack_version(), "1:2014.2") >= 0:
            section.append(
                ("network_api_class",
                 "nova_contrail_vif.contrailvif.ContrailNetworkAPI"))
        else:
            section.append(
                ("libvirt_vif_driver",
                 "nova_contrail_vif.contrailvif.VRouterVIFDriver"))
    section.append(
        ("firewall_driver",
         "nova.virt.firewall.NoopFirewallDriver"))
    conf = {
      "nova-compute": {
        "/etc/nova/nova.conf": {
          "sections": {
            "DEFAULT": section
          }
        }
      }
    }
    relation_set(subordinate_configuration=json.dumps(conf))

    if config["local-metadata-server"]:
        settings = {"metadata-shared-secret": config["local-metadata-secret"]}
        relation_set(relation_settings=settings)


@hooks.hook("update-status")
def update_status():
    set_status()


@hooks.hook("upgrade-charm")
def upgrade_charm():
    write_vrouter_config()
    write_vnc_api_config()
    write_nodemgr_config()
    service_restart("supervisor-vrouter")


@restart_on_change({"/etc/contrail/contrail-vrouter-agent.conf":
                        ["contrail-vrouter-agent"],
                    "/etc/contrail/contrail-vrouter-nodemgr.conf":
                        ["contrail-vrouter-nodemgr"]})
def write_config():
    write_vrouter_config()
    write_vnc_api_config()
    write_nodemgr_config()


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log("Unknown hook {} - skipping.".format(e))


if __name__ == "__main__":
    main()
