#!/usr/bin/env python
import json
import sys
import yaml

from charmhelpers.core.hookenv import (
    Hooks,
    UnregisteredHookError,
    config,
    log,
    relation_get,
    relation_ids,
    related_units,
    status_set,
    relation_set,
    unit_private_ip,
    is_leader,
    leader_set,
    leader_get,
)
from charmhelpers.contrib.charmsupport import nrpe

import contrail_kubernetes_master_utils as utils
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
    status_set("blocked", "Missing relation to contrail-controller")


@hooks.hook("config-changed")
def config_changed():
    update_nrpe_config()
    docker_utils.config_changed()
    utils.update_charm_status()


@hooks.hook("contrail-controller-relation-joined")
def contrail_controller_joined():
    settings = {'unit-type': 'kubernetes',
                'orchestrator-info': json.dumps({"cloud_orchestrator": "kubernetes"})}
    relation_set(relation_settings=settings)


@hooks.hook("contrail-controller-relation-changed")
def contrail_controller_changed():
    data = relation_get()
    log("RelData: " + str(data))

    def _update_config(key, data_key):
        if data_key in data:
            config[key] = data[data_key]

    _update_config("analytics_servers", "analytics-server")
    config.save()

    utils.update_charm_status()


@hooks.hook("contrail-controller-relation-departed")
def contrail_cotroller_departed():
    status_set("blocked", "Missing relation to contrail-controller")


@hooks.hook("kube-api-endpoint-relation-joined")
def kube_api_endpoint_joined():
    _get_kubernetes_api_endpoint()
    # send orchestrator data
    if is_leader() and utils.update_orchestrator_info():
        _notify_controller()
    utils.update_charm_status()


@hooks.hook("kube-api-endpoint-relation-changed")
def kube_api_endpoint_changed():
    _get_kubernetes_api_endpoint()
    # send orchestrator data
    if is_leader() and utils.update_orchestrator_info():
        _notify_controller()
    utils.update_charm_status()


def _get_kubernetes_api_endpoint():
    if not is_leader():
        return
    kubernetes_api_server = relation_get("hostname")
    if kubernetes_api_server:
        leader_set({"kubernetes_api_server": kubernetes_api_server})
    kubernetes_api_secure_port = relation_get("port")
    if kubernetes_api_secure_port:
        leader_set({"kubernetes_api_secure_port": kubernetes_api_secure_port})


@hooks.hook("kube-api-endpoint-relation-departed")
def kube_api_endpoint_departed():
    status_set("blocked", "Missing relation to kube-api-endpoint")


@hooks.hook("contrail-kubernetes-config-relation-joined")
def contrail_kubernetes_config_joined():
    data = {"pod_subnets": config.get("pod_subnets")}
    relation_set(relation_settings=data)


@hooks.hook("update-status")
def update_status():
    # wait to kubectl is available
    utils.update_kube_manager_token()
    # send orchestrator data
    if is_leader() and utils.update_orchestrator_info():
        _notify_controller()
    utils.update_charm_status()


def _notify_controller():
    data = _get_orchestrator_info()
    leader_set(data)
    for rid in relation_ids("contrail-controller"):
        if related_units(rid):
            relation_set(relation_id=rid, **data)


def _get_orchestrator_info():
    info = {"cloud_orchestrator": "kubernetes"}

    def _add_to_info(key):
        value = leader_get(key)
        if value:
            info[key] = value

    _add_to_info("kube_manager_token")
    _add_to_info("kubernetes_api_server")
    _add_to_info("kubernetes_api_secure_port")
    return {"orchestrator-info": json.dumps(info)}


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

    ctl_status_shortname = 'check_contrail_status_kubernetes_master'
    nrpe_compat.add_check(
        shortname=ctl_status_shortname,
        description='Check contrail-status',
        check_cmd=common_utils.contrail_status_cmd('kubernetes-master', plugins_dir)
    )

    nrpe_compat.write()


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log("Unknown hook {} - skipping.".format(e))


if __name__ == "__main__":
    main()
