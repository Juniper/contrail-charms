#!/usr/bin/env python3

import sys

from charmhelpers.core.hookenv import (
    Hooks,
    UnregisteredHookError,
    config,
    log,
    relation_get,
    related_units,
    relation_ids,
    status_set,
    relation_set,
)
from charmhelpers.contrib.charmsupport import nrpe

import contrail_analyticsdb_utils as utils
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
    utils.update_charm_status()


@hooks.hook("config-changed")
def config_changed():
    update_nrpe_config()
    if config.changed("control-network"):
        settings = {'private-address': common_utils.get_ip()}
        rnames = ("contrail-analyticsdb", "analyticsdb-cluster")
        for rname in rnames:
            for rid in relation_ids(rname):
                relation_set(relation_id=rid, relation_settings=settings)

    config["config_analytics_ssl_available"] = common_utils.is_config_analytics_ssl_available()
    config.save()

    docker_utils.config_changed()
    utils.update_charm_status()


@hooks.hook("contrail-analyticsdb-relation-joined")
def analyticsdb_joined():
    settings = {'private-address': common_utils.get_ip()}
    relation_set(relation_settings=settings)


def _value_changed(rel_data, rel_key, cfg_key):
    if rel_key not in rel_data:
        # data is absent in relation. it means that remote charm doesn't
        # send it due to lack of information
        return False
    value = rel_data[rel_key]
    if value is not None and value != config.get(cfg_key):
        config[cfg_key] = value
        return True
    elif value is None and config.get(cfg_key) is not None:
        config.pop(cfg_key, None)
        return True
    return False


@hooks.hook("contrail-analyticsdb-relation-changed")
def analyticsdb_changed():
    data = relation_get()
    changed = False
    changed |= _value_changed(data, "auth-info", "auth_info")
    changed |= _value_changed(data, "orchestrator-info", "orchestrator_info")
    # TODO: handle changing of all values
    # TODO: set error if orchestrator is changing and container was started
    if changed:
        utils.update_charm_status()


@hooks.hook("contrail-analyticsdb-relation-departed")
def analyticsdb_departed():
    count = 0
    for rid in relation_ids("contrail-analyticsdb"):
        for unit in related_units(rid):
            if relation_get("unit-type", unit, rid) == "controller":
                count += 1
    if count == 0:
        for key in ["auth_info", "orchestrator_info"]:
            config.pop(key, None)
    utils.update_charm_status()


@hooks.hook("analyticsdb-cluster-relation-joined")
def analyticsdb_cluster_joined():
    settings = {'private-address': common_utils.get_ip()}
    relation_set(relation_settings=settings)


@hooks.hook('tls-certificates-relation-joined')
def tls_certificates_relation_joined():
    settings = common_utils.get_tls_settings(common_utils.get_ip())
    relation_set(relation_settings=settings)


@hooks.hook('tls-certificates-relation-changed')
def tls_certificates_relation_changed():
    if common_utils.tls_changed(utils.MODULE, relation_get()):
        utils.update_charm_status()


@hooks.hook('tls-certificates-relation-departed')
def tls_certificates_relation_departed():
    if common_utils.tls_changed(utils.MODULE, None):
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
    nrpe_compat = nrpe.NRPE()
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
