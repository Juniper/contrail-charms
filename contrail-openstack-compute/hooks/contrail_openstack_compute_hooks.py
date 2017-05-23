#!/usr/bin/env python

import os
import sys
import time

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
    WARNING,
    status_set,
)

from charmhelpers.fetch import (
    apt_install,
    apt_upgrade,
    configure_sources
)
from subprocess import (
    CalledProcessError,
)
from contrail_openstack_compute_utils import (
    configure_vrouter,
    disable_vrouter_vgw,
    drop_caches,
    enable_vrouter_vgw,
    ifdown,
    ifup,
    modprobe,
    provision_linklocal,
    provision_vrouter,
    write_configs,
    write_vrouter_vgw_interfaces,
    set_status,
    vrouter_restart,
)

PACKAGES = ["contrail-vrouter-dkms", "contrail-vrouter-agent",
            "contrail-vrouter-common"]

PACKAGES_DKMS_INIT = ["contrail-vrouter-init"]
PACKAGES_DPDK_INIT = ["contrail-vrouter-dpdk-init"]

hooks = Hooks()
config = config()


@hooks.hook("install.real")
def install():
    status_set('maintenance', 'Installing...')

    configure_sources(True, "install-sources", "install-keys")
    apt_upgrade(fatal=True, dist=True)
    packages = list()
    packages.extend(PACKAGES)
    # TODO: support dpdk config option
    packages.extend(PACKAGES_DKMS_INIT)
    apt_install(packages, fatal=True)

    status_set('maintenance', 'Configuring...')
    os.chmod("/etc/contrail", 0o755)
    os.chown("/etc/contrail", 0, 0)
    vrouter_restart()

    try:
        modprobe("vrouter")
    except CalledProcessError:
        log("vrouter kernel module failed to load,"
            " clearing pagecache and retrying")
        drop_caches()
        modprobe("vrouter")
    modprobe("vrouter", True, True)
    configure_vrouter()
    status_set("waiting", "Waiting for relations.")


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
                provision_linklocal("del")
            leader_set({"local-metadata-provisioned": ""})
        return

    if config["enable-metadata-server"]:
        if not leader_get("local-metadata-provisioned"):
            provision_linklocal("add")
            leader_set({"local-metadata-provisioned": True})
    elif leader_get("local-metadata-provisioned"):
        provision_linklocal("del")
        leader_set({"local-metadata-provisioned": ""})


def check_vrouter():
    # TODO: support authentication-less
    # check relation dependencies
    if config.get("controller-ready") \
       and config.get("analytics-servers") \
       and config.get("auth_info"):
        if not config.get("vrouter-provisioned"):
            try:
                provision_vrouter("add")
                config["vrouter-provisioned"] = True
            except Exception as e:
                # vrouter is not up yet
                log("Couldn't provision vrouter: " + str(e), level=WARNING)
    elif config.get("vrouter-provisioned"):
        provision_vrouter("del")
        config["vrouter-provisioned"] = False


@hooks.hook("config-changed")
def config_changed():
    configure_local_metadata()
    configure_virtual_gateways()
    write_configs()
    check_vrouter()
    check_local_metadata()
    set_status()


def configure_local_metadata():
    if config["enable-metadata-server"]:
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
            config.pop("local-metadata-secret", None)
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
    data = relation_get()
    if "analytics-server" in data:
        config["analytics-servers"] = data["analytics-server"]
    config["api_ip"] = data.get("private-address")
    config["api_port"] = data.get("port")
    if "auth-info" in data:
        auth_info = data["auth-info"]
        if auth_info is not None:
            config["auth_info"] = auth_info
        else:
            config.pop("auth_info", None)
    config["ssl_ca"] = data.get("ssl-ca")
    config["ssl_cert"] = data.get("ssl-cert")
    config["ssl_key"] = data.get("ssl-key")
    config.save()

    # TODO: add reaction to change auth_info from None to not-None and back

    auth_info = config.get("auth_info")
    if auth_info is None:
        log("Relation not ready")
        return

    write_configs()
    config["controller-ready"] = True
    config.save()

    check_vrouter()
    check_local_metadata()
    set_status()


@hooks.hook("contrail-controller-relation-departed")
def contrail_controller_node_departed():
    if not units("contrail-controller"):
        config["controller-ready"] = False
        check_vrouter()
        check_local_metadata()
        config.pop("analytics-servers", None)
        config.pop("auth_info", None)
        config.pop("ssl_ca", None)
        config.pop("ssl_cert", None)
        config.pop("ssl_key", None)
        config.save()
        set_status()
    write_configs()


@hooks.hook("neutron-plugin-relation-joined")
def neutron_plugin_joined():
    # create plugin config
    conf = {
      "nova-compute": {
        "/etc/nova/nova.conf": {
          "sections": {
            "DEFAULT": [
                ("firewall_driver", "nova.virt.firewall.NoopFirewallDriver")
            ]
          }
        }
      }
    }
    relation_set(subordinate_configuration=json.dumps(conf))

    if config["enable-metadata-server"]:
        settings = {"metadata-shared-secret": config["local-metadata-secret"]}
        relation_set(relation_settings=settings)


@hooks.hook("update-status")
def update_status():
    check_vrouter()
    check_local_metadata()
    if set_status() == 1:
        vrouter_restart()
        time.sleep(5)
        set_status()


@hooks.hook("upgrade-charm")
def upgrade_charm():
    write_configs()
    vrouter_restart()
    check_vrouter()
    check_local_metadata()
    set_status()


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log("Unknown hook {} - skipping.".format(e))


if __name__ == "__main__":
    main()
