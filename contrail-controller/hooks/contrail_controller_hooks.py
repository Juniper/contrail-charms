#!/usr/bin/env python

import json
import sys

from charmhelpers.core.hookenv import (
    Hooks,
    UnregisteredHookError,
    config,
    log,
    is_leader,
    relation_get,
    relation_ids,
    relation_set,
    relation_id,
    related_units,
)

from charmhelpers.fetch import (
    apt_install,
    apt_upgrade,
    apt_update
)

from contrail_controller_utils import (
    get_control_ip,
    update_charm_status,
    CONTAINER_NAME,
    get_analytics_list,
)

from docker_utils import (
    add_docker_repo,
    DOCKER_PACKAGES,
    is_container_launched,
    load_docker_image,
)

PACKAGES = ["python", "python-yaml", "python-apt"]

hooks = Hooks()
config = config()


@hooks.hook()
def install():
    apt_upgrade(fatal=True, dist=True)
    add_docker_repo()
    apt_update(fatal=False)
    apt_install(PACKAGES + DOCKER_PACKAGES, fatal=True)
    load_docker_image(CONTAINER_NAME)
    update_charm_status()


@hooks.hook("config-changed")
def config_changed():
    update_charm_status()

    if not is_leader():
        return

    settings = {
        "private-address": get_control_ip(),
        "port": 8082,
    }
    for rid in relation_ids("contrail-controller"):
        relation_set(relation_id=rid, relation_settings=settings)


def update_northbound_relations(rid=None):
    settings = {
        "multi-tenancy": config.get("multi_tenancy"),
        "auth-info": config.get("auth_info")
    }

    if rid:
        relation_set(relation_id=rid, relation_settings=settings)
        return

    for rid in relation_ids("contrail-analytics"):
        relation_set(relation_id=rid, relation_settings=settings)
    for rid in relation_ids("contrail-analyticsdb"):
        relation_set(relation_id=rid, relation_settings=settings)


def update_southbound_relations(rid=None):
    settings = {
        "port": 8082,
        "analytics-server": json.dumps(get_analytics_list())
    }
    relation_set(relation_settings=settings)
    for rid in ([rid] if rid else relation_ids("contrail-analytics")):
        relation_set(relation_id=rid, relation_settings=settings)


@hooks.hook("contrail-controller-relation-joined")
def contrail_controller_joined():
    if is_leader():
        update_southbound_relations(rid=relation_id())


@hooks.hook("controller-cluster-relation-joined")
def cluster_joined():
    update_charm_status()


@hooks.hook("contrail-analytics-relation-joined")
def analytics_joined():
    if is_leader():
        update_northbound_relations(rid=relation_id())
        update_southbound_relations()
    update_charm_status()


@hooks.hook("contrail-analytics-relation-departed")
def analytics_departed():
    update_charm_status()
    if is_leader():
        update_southbound_relations()


@hooks.hook("contrail-analyticsdb-relation-joined")
def analyticsdb_joined():
    if is_leader():
        update_northbound_relations(rid=relation_id())


@hooks.hook("identity-admin-relation-changed")
def identity_admin_changed():
    auth_info = {
        "keystone_protocol": relation_get("service_protocol"),
        "keystone_ip": relation_get("service_hostname"),
        "keystone_public_port": relation_get("service_port"),
        "keystone_admin_user": relation_get("service_username"),
        "keystone_admin_password": relation_get("service_password"),
        "keystone_admin_tenant": relation_get("service_tenant_name")}
    auth_info = json.dumps(auth_info)

    config["auth_info"] = auth_info
    if is_leader():
        update_northbound_relations()
    update_charm_status()


@hooks.hook("identity-admin-relation-departed")
def identity_admin_departed():
    count = 0
    for rid in relation_ids("identity-admin"):
        count += len(related_units(rid))
    if count > 0:
        return

    auth_info = "{}"
    config["auth_info"] = auth_info
    if is_leader():
        update_northbound_relations()
    update_charm_status()


@hooks.hook("update-status")
def update_status():
    update_charm_status(update_config=False)


@hooks.hook("upgrade-charm")
def upgrade_charm():
    if not is_container_launched(CONTAINER_NAME):
        load_docker_image(CONTAINER_NAME)
        # NOTE: image can not be deleted if container is running.
        # TODO: think about killing the container

    # TODO: this hook can be fired when either resource changed or charm code
    # changed. so if code was changed then we may need to update config
    update_charm_status()


@hooks.hook("start")
@hooks.hook("stop")
def todo():
    # TODO: think about it
    pass


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log("Unknown hook {} - skipping.".format(e))


if __name__ == "__main__":
    main()
