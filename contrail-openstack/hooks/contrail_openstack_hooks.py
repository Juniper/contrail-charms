#!/usr/bin/env python

import json
import sys
import uuid
import yaml

from charmhelpers.core.hookenv import (
    Hooks,
    UnregisteredHookError,
    config,
    log,
    related_units,
    relation_get,
    relation_ids,
    relation_set,
    status_set,
    leader_get,
    leader_set,
    is_leader,
    unit_private_ip,
)

import contrail_openstack_utils as utils
import docker_utils


hooks = Hooks()
config = config()


@hooks.hook("install.real")
def install():
    status_set('maintenance', 'Installing...')

    docker_utils.install()
    status_set("blocked", "Missing relation to contrail-controller")


@hooks.hook("config-changed")
def config_changed():
    changed = docker_utils.config_changed()
    if changed:
        _notify_nova()
        _notify_neutron()
        _notufy_heat()

    if is_leader():
        _configure_metadata_shared_secret()
        _notify_nova()
        _notify_controller()


@hooks.hook("leader-elected")
def leader_elected():
    _configure_metadata_shared_secret()
    _notify_nova()
    _notify_controller()


@hooks.hook("leader-settings-changed")
def leader_settings_changed():
    _notify_nova()


@hooks.hook("contrail-controller-relation-joined")
def contrail_controller_joined():
    if not is_leader():
        return

    data = _get_orchestrator_info()
    relation_set(**data)


@hooks.hook("contrail-controller-relation-changed")
def contrail_controller_changed():
    data = relation_get()

    def _update_config(key, data_key):
        if data_key in data:
            val = data[data_key]
            if val is not None:
                config[key] = val
            else:
                config.pop(key, None)

    _update_config("auth_info", "auth-info")
    _update_config("api_vip", "api-vip")
    _update_config("api_ip", "private-address")
    _update_config("api_port", "port")
    _update_config("auth_mode", "auth-mode")

    info = data.get("agents-info")
    if not info:
        config["dpdk"] = False
        log("DPDK for current host is False. agents-info is not provided.")
    else:
        ip = unit_private_ip()
        value = json.loads(info).get(ip, False)
        if not isinstance(value, bool):
            value = yaml.load(value)
        config["dpdk"] = value
        log("DPDK for host {ip} is {dpdk}".format(ip=ip, dpdk=value))

    config.save()
    utils.write_configs()

    # apply information to base charms
    _notify_nova()
    _notify_neutron()
    _notify_heat()

    status_set("active", "Unit is ready")

    # auth_info can affect endpoints
    if is_leader():
        changed = utils.update_service_ips()
        if changed:
            _notify_controller()


@hooks.hook("contrail-controller-relation-departed")
def contrail_cotroller_departed():
    units = [unit for rid in relation_ids("contrail-controller")
                  for unit in related_units(rid)]
    if units:
        return

    keys = ["auth_info", "api_vip", "api_ip", "api_port", "auth_mode"]
    for key in keys:
        config.pop(key, None)
    config.save()
    utils.write_configs()
    status_set("blocked", "Missing relation to contrail-controller")


def _configure_metadata_shared_secret():
    secret = leader_get("metadata-shared-secret")
    if config["enable-metadata-server"] and not secret:
        secret = str(uuid.uuid4())
    elif not config["enable-metadata-server"] and secret:
        secret = None
    else:
        return

    leader_set(settings={"metadata-shared-secret": secret})


def _notify_controller():
    data = _get_orchestrator_info()
    for rid in relation_ids("contrail-controller"):
        if related_units(rid):
            relation_set(relation_id=rid, **data)


def _notify_nova():
    for rid in relation_ids("nova-compute"):
        if related_units(rid):
            nova_compute_joined(rid)


def _notify_neutron():
    for rid in relation_ids("neutron-api"):
        if related_units(rid):
            neutron_api_joined(rid)

def _notify_heat():
    for rid in relation_ids("heat-plugin"):
        if related_units(rid):
            heat_plugin_joined(rid)


def _get_orchestrator_info():
    info = {"cloud_orchestrator": "openstack", "unit-type": "openstack"}

    if config["enable-metadata-server"]:
        info["metadata_shared_secret"] = leader_get("metadata-shared-secret")

    def _add_to_info(key):
        value = leader_get(key)
        if value:
            info[key] = value

    _add_to_info("compute_service_ip")
    _add_to_info("image_service_ip")
    _add_to_info("network_service_ip")
    return {"orchestrator-info": json.dumps(info)}

@hooks.hook("heat-plugin-relation-joined")
def heat_plugin_joined(rel_id=None):
    utils.deploy_openstack_code("contrail-openstack-heat-init")

    settings = {
        "plugin-dirs": config.get("heat-plugin-dirs"),
    }
    relation_set(relation_id=rel_id, relation_settings=settings)

@hooks.hook("neutron-api-relation-joined")
def neutron_api_joined(rel_id=None):
    utils.deploy_openstack_code("contrail-openstack-neutron-init")

    # create plugin config
    base = "neutron_plugin_contrail.plugins.opencontrail"
    plugin = base + ".contrail_plugin.NeutronPluginContrailCoreV2"
    service_plugins = base + ".loadbalancer.v2.plugin.LoadBalancerPluginV2"
    extensions = [
        "/usr/lib/python2.7/dist-packages/neutron_plugin_contrail/extensions",
        "/usr/lib/python2.7/dist-packages/neutron_lbaas/extensions"]
    conf = {
      "neutron-api": {
        "/etc/neutron/neutron.conf": {
          "sections": {
            "DEFAULT": [
              ("api_extensions_path", ":".join(extensions))
            ]
          }
        }
      }
    }
    settings = {
        "neutron-plugin": "contrail",
        "core-plugin": plugin,
        "neutron-plugin-config":
            "/etc/neutron/plugins/opencontrail/ContrailPlugin.ini",
        "service-plugins": service_plugins,
        "quota-driver": base + ".quota.driver.QuotaDriver",
        "subordinate_configuration": json.dumps(conf),
    }
    auth_mode = config.get("auth_mode", "cloud-admin")
    if auth_mode == "rbac":
        settings["extra_middleware"] = [{
            "name": "user_token",
            "type": "filter",
            "config": {
                "paste.filter_factory":
                    base + ".neutron_middleware:token_factory"
            }
        }]
    relation_set(relation_id=rel_id, relation_settings=settings)

    # if this hook raised after contrail-controller we need
    # to overwrite default config file after installation
    utils.write_configs()


@hooks.hook("nova-compute-relation-joined")
def nova_compute_joined(rel_id=None):
    utils.deploy_openstack_code("contrail-openstack-compute-init")

    utils.nova_patch()

    # create plugin config
    sections = {
        "DEFAULT": [
            ("firewall_driver", "nova.virt.firewall.NoopFirewallDriver")
        ]
    }
    if config.get("dpdk", False):
        sections["CONTRAIL"] = [("use_userspace_vhost", "True")]
        sections["libvirt"] = [("use_huge_pages", "True")]
    conf = {
      "nova-compute": {
        "/etc/nova/nova.conf": {
          "sections": sections
        }
      }
    }
    settings = {
        "metadata-shared-secret": leader_get("metadata-shared-secret"),
        "subordinate_configuration": json.dumps(conf)}
    relation_set(relation_id=rel_id, relation_settings=settings)


@hooks.hook("update-status")
def update_status():
    # TODO: try to deploy openstack code again if it was not done

    if not is_leader():
        return
    changed = utils.update_service_ips()
    if changed:
        _notify_controller()


@hooks.hook("upgrade-charm")
def upgrade_charm():
    # apply information to base charms
    _notify_nova()
    _notify_neutron()
    _notify_heat()


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log("Unknown hook {} - skipping.".format(e))


if __name__ == "__main__":
    main()
