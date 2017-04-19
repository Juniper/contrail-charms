#!/usr/bin/env python

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
    ERROR,
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

    if is_leader():
        settings = {
            "private-address": get_control_ip(),
            "port": 8082,
            "multi-tenancy": config.get("multi_tenancy")
        }
        for rid in relation_ids("contrail-controller"):
            relation_set(relation_id=rid, relation_settings=settings)


@hooks.hook("contrail-controller-relation-joined")
def contrail_controller_joined():
    settings = {
        "private-address": get_control_ip(),
        "port": 8082
    }
    if is_leader():
        settings["multi-tenancy"] = config.get("multi_tenancy")
    relation_set(relation_settings=settings)


@hooks.hook("controller-cluster-relation-joined")
def cluster_joined():
    update_charm_status()


@hooks.hook("contrail-analytics-relation-joined")
@hooks.hook("contrail-analytics-relation-departed")
@hooks.hook("contrail-analytics-relation-broken")
def analytics_relation():
    update_charm_status()


@hooks.hook("identity-admin-relation-changed")
@hooks.hook("identity-admin-relation-departed")
@hooks.hook("identity-admin-relation-broken")
def identity_admin_changed():
    if not relation_get("service_hostname"):
        log("Relation not ready")
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
