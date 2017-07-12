#!/usr/bin/env python

import json
import sys

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
    is_leader,
)

from charmhelpers.fetch import (
    apt_install,
    apt_update,
    apt_upgrade,
    configure_sources
)

from contrail_kubernetes_utils import (
    write_configs,
)

PACKAGES = ["contrail-k8s-cni"]


hooks = Hooks()
config = config()


@hooks.hook("install.real")
def install():
    status_set('maintenance', 'Installing...')
    configure_sources(True, "install-sources", "install-keys")
    apt_update(fatal=True)
    apt_upgrade(fatal=True, dist=False)
    apt_install(PACKAGES, fatal=True)
    status_set("blocked", "Missing relation to contrail-controller")


@hooks.hook("config-changed")
def config_changed():
    if config.changed("install-sources") or config.changed("install-keys"):
        configure_sources(True, "install-sources", "install-keys")
        apt_update(fatal=True)
        apt_upgrade(fatal=True, dist=False)


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

    _update_config("api_vip", "api-vip")
    _update_config("api_ip", "private-address")
    _update_config("api_port", "port")
    config.save()
    write_configs()

    status_set("active", "Unit is ready")


@hooks.hook("contrail-controller-relation-departed")
def contrail_cotroller_departed():
    units = [unit for rid in relation_ids("contrail-controller")
                  for unit in related_units(rid)]
    if units:
        return

    for key in ["api_vip", "api_ip", "api_port"]:
        config.pop(key, None)
    config.save()
    write_configs()
    status_set("blocked", "Missing relation to contrail-controller")


def _notify_clients():
    # notify clients
    data = _get_orchestrator_info()
    for rid in relation_ids("contrail-controller"):
        relation_set(relation_id=rid, **data)


def _get_orchestrator_info():
    info = {"cloud_orchestrator": "kubernetes"}

    # TODO: add info from CNI

    return {"orchestrator-info": json.dumps(info)}


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log("Unknown hook {} - skipping.".format(e))


if __name__ == "__main__":
    main()
