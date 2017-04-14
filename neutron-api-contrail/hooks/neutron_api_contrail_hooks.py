#!/usr/bin/env python

import sys
from subprocess import check_output

from apt_pkg import version_compare
import json

from charmhelpers.core.hookenv import (
    Hooks,
    UnregisteredHookError,
    config,
    log,
    relation_get,
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

from neutron_api_contrail_utils import (
    CONTRAIL_VERSION,
    OPENSTACK_VERSION,
    write_plugin_config,
    dpkg_version,
    set_status
)

PACKAGES = [ "python", "python-yaml", "python-apt", "neutron-plugin-contrail" ]

hooks = Hooks()
config = config()

@hooks.hook("config-changed")
def config_changed():
    set_status()
    pass

@hooks.hook("contrail-api-relation-changed")
def contrail_api_changed():
    if not relation_get("port"):
        log("Relation not ready")
        return
    contrail_api_relation()

@hooks.hook("contrail-api-relation-departed")
@hooks.hook("contrail-api-relation-broken")
@restart_on_change({"/etc/neutron/plugins/opencontrail/ContrailPlugin.ini": ["neutron-server"]})
def contrail_api_relation():
    write_plugin_config()

@hooks.hook("identity-admin-relation-changed")
def identity_admin_changed():
    if not relation_get("service_hostname"):
        log("Relation not ready")
        return
    identity_admin_relation()

@hooks.hook("identity-admin-relation-departed")
@hooks.hook("identity-admin-relation-broken")
@restart_on_change({"/etc/neutron/plugins/opencontrail/ContrailPlugin.ini": ["neutron-server"]})
def identity_admin_relation():
    write_plugin_config()

@hooks.hook()
def install():
    configure_sources(True, "install-sources", "install-keys")
    apt_upgrade(fatal=True, dist=True)
    apt_install(PACKAGES, fatal=True)

def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log("Unknown hook {} - skipping.".format(e))

@hooks.hook("neutron-plugin-api-subordinate-relation-joined")
def neutron_plugin_joined():
    # create plugin config
    plugin = "neutron_plugin_contrail.plugins.opencontrail.contrail_plugin.NeutronPluginContrailCoreV2" \
             if version_compare(CONTRAIL_VERSION, "1.20~") >= 0 \
             else "neutron_plugin_contrail.plugins.opencontrail.contrail_plugin_core.NeutronPluginContrailCoreV2"
    service_plugins = "neutron_plugin_contrail.plugins.opencontrail.loadbalancer.v2.plugin.LoadBalancerPluginV2" \
                      if version_compare(CONTRAIL_VERSION, "3.0.2.0-34") >= 0 \
                         and version_compare(OPENSTACK_VERSION, "2:7.0.0") >= 0 \
                      else " "
    extensions = [ "/usr/lib/python2.7/dist-packages/neutron_plugin_contrail/extensions" ]
    if version_compare(CONTRAIL_VERSION, "3.0.2.0-34") >= 0 \
       and version_compare(OPENSTACK_VERSION, "2:7.0.0") >= 0:
        extensions.append("/usr/lib/python2.7/dist-packages/neutron_lbaas/extensions")
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
    settings = { "neutron-plugin": "contrail",
                 "core-plugin": plugin,
                 "neutron-plugin-config": "/etc/neutron/plugins/opencontrail/ContrailPlugin.ini",
                 "service-plugins": service_plugins,
                 "quota-driver": "neutron_plugin_contrail.plugins.opencontrail.quota.driver.QuotaDriver",
                 "subordinate_configuration": json.dumps(conf) }
    relation_set(relation_settings=settings)

@hooks.hook("update-status")
def update_status():
    set_status()

@hooks.hook("upgrade-charm")
def upgrade_charm():
    write_plugin_config()
    service_restart("neutron-server")

if __name__ == "__main__":
    main()
