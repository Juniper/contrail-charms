#!/usr/bin/env python

import sys

from charmhelpers.core.hookenv import (
    Hooks,
    UnregisteredHookError,
    config,
    log,
    relation_get,
    related_units,
    relation_ids,
    relation_types,
    relations,
    status_set,
    relation_set,
    related_units,
    is_leader,
    leader_set,
)
from charmhelpers.contrib.charmsupport import nrpe

import contrail_kubernetes_node_utils as utils
import common_utils
import docker_utils
import time

from subprocess import (
    check_call,
    check_output,
)

hooks = Hooks()
config = config()


@hooks.hook("install.real")
def install():
    status_set('maintenance', 'Installing...')

    docker_utils.install()
    utils.update_charm_status()


@hooks.hook("config-changed")
def config_changed():
    docker_utils.config_changed()
    utils.update_charm_status()


@hooks.hook("contrail-kubernetes-config-relation-changed")
def contrail_kubernetes_config_changed():
    cidr = relation_get("pod_subnets")
    if not cidr:
        return
    config["pod_subnets"] = cidr
    config.save()
    # send cni config data
    for rid in relation_ids("cni"):
        relation_set(relation_id=rid, relation_settings={"cidr": cidr})
    utils.update_charm_status()


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
