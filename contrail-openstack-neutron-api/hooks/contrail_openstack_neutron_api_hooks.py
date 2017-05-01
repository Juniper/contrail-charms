#!/usr/bin/env python

import sys

import json

from charmhelpers.core.hookenv import (
    Hooks,
    UnregisteredHookError,
    config,
    log,
    related_units,
    relation_get,
    relation_ids,
    relation_set
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

from contrail_openstack_neutron_api_utils import (
    write_plugin_config,
    set_status
)

PACKAGES = ["python", "python-yaml", "python-apt", "neutron-plugin-contrail"]


hooks = Hooks()
config = config()


@hooks.hook("config-changed")
def config_changed():
    set_status()


@hooks.hook("contrail-controller-relation-changed")
@restart_on_change({"/etc/neutron/plugins/opencontrail/ContrailPlugin.ini":
                        ["neutron-server"]})
def contrail_controller_changed():
    if not relation_get("port"):
        log("Relation not ready")
        return
    auth_info = relation_get("auth-info")
    if auth_info is not None:
        config["auth_info"] = auth_info
    else:
        config.pop("auth_info", None)
    write_plugin_config()


@hooks.hook("contrail-controller-relation-departed")
@restart_on_change({"/etc/neutron/plugins/opencontrail/ContrailPlugin.ini":
                        ["neutron-server"]})
def contrail_cotroller_departed():
    units = [unit for rid in relation_ids("contrail-controller")
                  for unit in related_units(rid)]
    if not units:
        config.pop("auth_info", None)
    write_plugin_config()


@hooks.hook()
def install():
    configure_sources(True, "install-sources", "install-keys")
    apt_upgrade(fatal=True, dist=True)
    apt_install(PACKAGES, fatal=True)


@hooks.hook("neutron-plugin-api-subordinate-relation-joined")
def neutron_plugin_joined():
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


@hooks.hook("update-status")
def update_status():
    set_status()


@hooks.hook("upgrade-charm")
def upgrade_charm():
    write_plugin_config()
    service_restart("neutron-server")


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log("Unknown hook {} - skipping.".format(e))


if __name__ == "__main__":
    main()
