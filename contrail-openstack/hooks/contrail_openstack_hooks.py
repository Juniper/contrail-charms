#!/usr/bin/env python

import json
from subprocess import CalledProcessError, check_output
import sys
import uuid

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
    application_version_set,
)

from charmhelpers.core.host import (
    restart_on_change,
)

from charmhelpers.fetch import (
    apt_install,
    apt_update,
    apt_upgrade,
    configure_sources
)

from contrail_openstack_utils import (
    write_configs,
    update_service_ips,
)

NEUTRON_API_PACKAGES = ["neutron-plugin-contrail"]


hooks = Hooks()
config = config()


@hooks.hook("install.real")
def install():
    status_set('maintenance', 'Installing...')
    configure_sources(True, "install-sources", "install-keys")
    apt_update(fatal=True)
    apt_upgrade(fatal=True, dist=False)
    status_set("blocked", "Missing relation to contrail-controller")


@hooks.hook("config-changed")
def config_changed():
    if config.changed("install-sources") or config.changed("install-keys"):
        configure_sources(True, "install-sources", "install-keys")
        apt_update(fatal=True)
        apt_upgrade(fatal=True, dist=False)

    if is_leader():
        _configure_metadata_shared_secret()


@hooks.hook("leader-elected")
def leader_elected():
    _configure_metadata_shared_secret()
    _notify_clients()


@hooks.hook("leader-settings-changed")
def leader_settings_changed():
    _notify_clients()


@hooks.hook("contrail-controller-relation-joined")
def contrail_controller_joined():
    if not is_leader():
        return

    data = _get_orchestrator_info()
    relation_set(**data)


@hooks.hook("contrail-controller-relation-changed")
@restart_on_change({"/etc/neutron/plugins/opencontrail/ContrailPlugin.ini":
                        ["neutron-server"]})
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
    _update_config("ssl_ca", "ssl-ca")
    _update_config("api_vip", "api-vip")
    _update_config("api_ip", "private-address")
    _update_config("api_port", "port")
    config.save()
    write_configs()

    status_set("active", "Unit is ready")

    # auth_info can affect endpoints
    changed = update_service_ips()
    if changed and is_leader():
        data = _get_orchestrator_info()
        for rid in relation_ids("contrail-controller"):
            relation_set(relation_id=rid, **data)


@hooks.hook("contrail-controller-relation-departed")
@restart_on_change({"/etc/neutron/plugins/opencontrail/ContrailPlugin.ini":
                        ["neutron-server"]})
def contrail_cotroller_departed():
    units = [unit for rid in relation_ids("contrail-controller")
                  for unit in related_units(rid)]
    if units:
        return

    for key in ["auth_info", "ssl_ca", "api_vip", "api_ip", "api_port"]:
        config.pop(key, None)
    config.save()
    write_configs()
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


def _notify_clients():
    # notify clients
    data = _get_orchestrator_info()
    for rid in relation_ids("contrail-controller"):
        relation_set(relation_id=rid, **data)
    for rid in relation_ids("nova-compute"):
        nova_compute_joined(rid)


def _get_orchestrator_info():
    info = {"cloud_orchestrator": "openstack"}

    if config["enable-metadata-server"]:
        info["metadata_shared_secret"] = leader_get("metadata-shared-secret")

    def _add_to_info(key):
        value = config.get(key)
        if value:
            info[key] = value

    _add_to_info("compute_service_ip")
    _add_to_info("image_service_ip")
    _add_to_info("network_service_ip")
    return {"orchestrator-info": json.dumps(info)}


@hooks.hook("neutron-api-relation-joined")
def neutron_api_joined():
    apt_install(NEUTRON_API_PACKAGES, fatal=True)
    try:
        cmd = ["dpkg-query", "-f", "${Version}\\n",
               "-W", "neutron-plugin-contrail"]
        version = check_output(cmd).decode("UTF-8").rstrip()
        application_version_set(version)
    except CalledProcessError as e:
        log("Couldn't detect installed application version: " + str(e))

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
        "subordinate_configuration": json.dumps(conf)}
    relation_set(relation_settings=settings)


@hooks.hook("nova-compute-relation-joined")
def nova_compute_joined(rel_id=None):
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
    settings = {
        "metadata-shared-secret": leader_get("metadata-shared-secret"),
        "subordinate_configuration": json.dumps(conf)}
    relation_set(relation_id=rel_id, relation_settings=settings)


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log("Unknown hook {} - skipping.".format(e))


if __name__ == "__main__":
    main()
