#!/usr/bin/env python

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
)

from subprocess import (
    check_output,
)

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
    docker_utils.apply_insecure()
    docker_utils.login()

    if config["dpdk"]:
        utils.fix_libvirt()

    utils.update_charm_status()


@hooks.hook("config-changed")
def config_changed():
    # Charm doesn't support changing of some parameters.
    if config.changed("dpdk"):
        raise Exception("Configuration parameter dpdk couldn't be changed")

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
    cn = gethostname().split(".")[0]
    sans = [cn]
    sans_ips = []
    try:
        sans_ips.append(gethostbyname(cn))
    except:
        pass
    control_ip = utils.get_vhost_ip()
    if control_ip not in sans_ips:
        sans_ips.append(control_ip)
    res = check_output(['getent', 'hosts', control_ip])
    control_name = res.split()[1].split('.')[0]
    if control_name not in sans:
        sans.append(control_name)
    sans_ips.append("127.0.0.1")
    sans.extend(sans_ips)
    settings = {
        'sans': json.dumps(sans),
        'common_name': cn,
        'certificate_name': cn
    }
    log("TLS_CTX: {}".format(settings))
    relation_set(relation_settings=settings)


@hooks.hook('tls-certificates-relation-changed')
def tls_certificates_relation_changed():
    unitname = local_unit().replace('/', '_')
    cert_name = '{0}.server.cert'.format(unitname)
    key_name = '{0}.server.key'.format(unitname)
    cert = relation_get(cert_name)
    key = relation_get(key_name)
    ca = relation_get('ca')

    if not cert or not key:
        log("tls-certificates client's relation data is not fully available")
        cert = key = None

    utils.tls_changed(cert, key, ca)


@hooks.hook('tls-certificates-relation-departed')
def tls_certificates_relation_departed():
    utils.tls_changed(None, None, None)


@hooks.hook("update-status")
def update_status():
    utils.update_charm_status()


@hooks.hook("upgrade-charm")
def upgrade_charm():
    utils.update_charm_status()


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log("Unknown hook {} - skipping.".format(e))


if __name__ == "__main__":
    main()
