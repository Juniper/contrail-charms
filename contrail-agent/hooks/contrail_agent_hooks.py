#!/usr/bin/env python3

import json
from socket import gethostname, gethostbyname
import sys

from charmhelpers.core.hookenv import (
    Hooks,
    UnregisteredHookError,
    config,
    log,
    relation_get,
    relation_set,
    relation_ids,
    related_units,
    status_set,
    local_unit,
    unit_get,
)
from charmhelpers.contrib.charmsupport import nrpe

from subprocess import check_output


import contrail_agent_utils as utils
import common_utils
import docker_utils

hooks = Hooks()
config = config()


@hooks.hook("install.real")
def install():
    status_set('maintenance', 'Installing...')

    # TODO: try to remove this call
    common_utils.fix_hostname()

    docker_utils.install()
    if config["dpdk"]:
        utils.fix_libvirt()
    utils.update_charm_status()


@hooks.hook("config-changed")
def config_changed():
    update_nrpe_config()
    # Charm doesn't support changing of some parameters.
    if config.changed("dpdk"):
        raise Exception("Configuration parameter dpdk couldn't be changed")

    config["config_analytics_ssl_available"] = common_utils.is_config_analytics_ssl_available()
    config.save()

    docker_utils.config_changed()
    utils.update_charm_status()


@hooks.hook("contrail-controller-relation-joined")
def contrail_controller_joined():
    settings = {'dpdk': config["dpdk"], 'unit-type': 'agent'}
    relation_set(relation_settings=settings)


@hooks.hook("contrail-controller-relation-changed")
def contrail_controller_changed():
    data = relation_get()
    log("RelData: " + str(data))

    def _update_config(key, data_key):
        if data_key in data:
            config[key] = data[data_key]

    _update_config("analytics_servers", "analytics-server")
    _update_config("api_ip", "private-address")
    _update_config("api_port", "port")
    _update_config("auth_info", "auth-info")
    _update_config("orchestrator_info", "orchestrator-info")
    config.save()

    utils.update_charm_status()


@hooks.hook("contrail-controller-relation-departed")
def contrail_controller_node_departed():
    units = [unit for rid in relation_ids("contrail-controller")
                      for unit in related_units(rid)]
    if units:
        return

    utils.update_charm_status()
    status_set("blocked", "Missing relation to contrail-controller")


@hooks.hook('tls-certificates-relation-joined')
def tls_certificates_relation_joined():
    settings = common_utils.get_tls_settings(utils.get_vhost_ip())
    relation_set(relation_settings=settings)


@hooks.hook('tls-certificates-relation-changed')
def tls_certificates_relation_changed():
    if common_utils.tls_changed(utils.MODULE, relation_get()):
        utils.update_charm_status()


@hooks.hook('tls-certificates-relation-departed')
def tls_certificates_relation_departed():
    if common_utils.tls_changed(utils.MODULE, None):
        utils.update_charm_status()


@hooks.hook("vrouter-plugin-relation-changed")
def vrouter_plugin_changed():
    # accepts 'ready' value in realation (True/False)
    # accepts 'settings' value as a serialized dict to json for contrail-vrouter-agent.conf:
    # {"DEFAULT": {"key1": "value1"}, "SECTION_2": {"key1": "value1"}}
    data = relation_get()
    plugin_ip = data.get("private-address")
    plugin_ready = data.get("ready", False)
    if plugin_ready:
        plugin_ips = common_utils.json_loads(config.get("plugin-ips"), dict())
        plugin_ips[plugin_ip] = common_utils.json_loads(data.get("settings"), dict())
        config["plugin-ips"] = json.dumps(plugin_ips)
        config.save()
    utils.update_charm_status()


@hooks.hook("update-status")
def update_status():
    utils.update_charm_status()


@hooks.hook("upgrade-charm")
def upgrade_charm():
    utils.update_charm_status()


@hooks.hook('nrpe-external-master-relation-changed')
def nrpe_external_master_relation_changed():
    update_nrpe_config()


def update_nrpe_config():
    plugins_dir = '/usr/local/lib/nagios/plugins'
    nrpe_compat = nrpe.NRPE(primary=False)
    common_utils.rsync_nrpe_checks(plugins_dir)
    common_utils.add_nagios_to_sudoers()

    ctl_status_shortname = 'check_contrail_status_' + utils.MODULE
    nrpe_compat.add_check(
        shortname=ctl_status_shortname,
        description='Check contrail-status',
        check_cmd=common_utils.contrail_status_cmd(utils.MODULE, plugins_dir)
    )

    nrpe_compat.write()


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log("Unknown hook {} - skipping.".format(e))


if __name__ == "__main__":
    main()
