#!/usr/bin/env python

import os
import sys
import time

import json
import uuid

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
    ERROR,
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
    drop_caches,
    modprobe,
    provision_vrouter,
    write_configs,
    set_status,
    vrouter_restart,
    get_endpoints,
    get_controller_address,
)

PACKAGES = ["contrail-vrouter-dkms", "contrail-vrouter-agent",
            "contrail-vrouter-common"]

PACKAGES_DKMS_INIT = ["contrail-vrouter-init"]
PACKAGES_DPDK_INIT = ["contrail-vrouter-dpdk-init"]

hooks = Hooks()
config = config()


@hooks.hook("install.real")
def install():
    status_set("maintenance", "Installing...")

    configure_sources(True, "install-sources", "install-keys")
    apt_upgrade(fatal=True, dist=True)
    packages = list()
    packages.extend(PACKAGES)
    # TODO: support dpdk config option
    packages.extend(PACKAGES_DKMS_INIT)
    apt_install(packages, fatal=True)

    status_set("maintenance", "Configuring...")
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
        try:
            provision_vrouter("del")
            config["vrouter-provisioned"] = False
        except Exception as e:
            log("Couldn't unprovision vrouter: " + str(e), level=WARNING)


@hooks.hook("config-changed")
def config_changed():
    if is_leader():
        configure_metadata_shared_secret()
    write_configs()
    check_vrouter()
    set_status()


@hooks.hook("leader-elected")
def leader_elected():
    configure_metadata_shared_secret()
    write_configs()


@hooks.hook("leader-settings-changed")
def leader_settings_changed():
    write_configs()


def configure_metadata_shared_secret():
    secret = leader_get("metadata_shared_secret")
    if config["enable-metadata-server"] and not secret:
        secret = str(uuid.uuid4())
    elif not config["enable-metadata-server"] and secret:
        secret = None
    else:
        return

    leader_set(metadata_shared_secret=secret)
    # inform relations
    settings = {"metadata-shared-secret": secret}
    for rid in relation_ids("neutron-plugin"):
        relation_set(relation_id=rid, relation_settings=settings)


@hooks.hook("contrail-controller-relation-joined")
def contrail_controller_joined():
    if not is_leader():
        return

    def _pass_to_relation(key):
        value = config.get(key)
        if value:
            relation_set(**{key: value})

    _pass_to_relation("compute_service_ip")
    _pass_to_relation("image_service_ip")
    _pass_to_relation("network_service_ip")


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
    prev_contrail_api_vip = config["contrail_api_vip"]
    config["contrail_api_vip"] = data.get("contrail-api-vip")
    prev_analytics_api_vip = config["analytics_api_vip"]
    config["analytics_api_vip"] = data.get("analytics-api-vip")
    config.save()

    # TODO: add reaction to change auth_info from None to not-None and back

    auth_info = config.get("auth_info")
    if auth_info is None:
        log("Relation not ready")
        return

    if (prev_contrail_api_vip != config["contrail_api_vip"] or
            prev_analytics_api_vip != config["analytics_api_vip"]):
        keystone_joined()

    _update_service_ips()

    write_configs()
    config["controller-ready"] = True
    config.save()

    check_vrouter()
    set_status()


def _update_service_ips():
    try:
        endpoints = get_endpoints()
    except Exception as e:
        log("Couldn't detect compute/image ips: " + str(e),
            level=ERROR)
        return

    changed = {}

    def _check_key(key):
        val = endpoints.get(key)
        if val and val != config.get(key):
            config[key] = val
            changed[key] = val

    _check_key("compute_service_ip")
    _check_key("image_service_ip")
    _check_key("network_service_ip")
    if changed:
        config.save()
        if is_leader():
            for rid in relation_ids("contrail-controller"):
                relation_set(relation_id=rid, **changed)


@hooks.hook("contrail-controller-relation-departed")
def contrail_controller_node_departed():
    if not units("contrail-controller"):
        config["controller-ready"] = False
        check_vrouter()
        config.pop("analytics-servers", None)
        config.pop("auth_info", None)
        config.pop("ssl_ca", None)
        config.pop("ssl_cert", None)
        config.pop("ssl_key", None)
        config.pop("contrail_api_vip", None)
        config.pop("analytics_api_vip", None)
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
        secret = leader_get("metadata_shared_secret")
        settings = {"metadata-shared-secret": secret}
        relation_set(relation_settings=settings)


@hooks.hook("update-status")
def update_status():
    check_vrouter()
    if set_status() == 1:
        vrouter_restart()
        time.sleep(5)
        set_status()


@hooks.hook("upgrade-charm")
def upgrade_charm():
    write_configs()
    vrouter_restart()
    check_vrouter()
    set_status()


@hooks.hook("identity-service-relation-joined")
def keystone_joined(relation_id=None):
    ssl_ca = config.get("ssl_ca")
    # TODO: pass full URL-s from remote side
    proto = ("https" if (ssl_ca is not None and len(ssl_ca) > 0) else
             "http")
    api_ip, api_port = get_controller_address()
    url = "{}://{}:{}".format(proto, api_ip, api_port)
    relation_data = {
        "contrail-api": {
            "service": "contrail-api",
            "region": config.get("region"),
            "public_url": url,
            "admin_url": url,
            "internal_url": url
        }
    }

    # TODO: pass full URL-s from remote side - with protocol and port
    if config.get("analytics_api_vip"):
        vip = config.get("analytics_api_vip")
        url = "{}://{}:{}".format(proto, vip, "8081")
        relation_data = {
            "contrail-analytics": {
                "service": "contrail-analytics",
                "region": config.get("region"),
                "public_url": url,
                "admin_url": url,
                "internal_url": url
            }
        }

    relation_set(relation_id=relation_id, **relation_data)


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log("Unknown hook {} - skipping.".format(e))


if __name__ == "__main__":
    main()
