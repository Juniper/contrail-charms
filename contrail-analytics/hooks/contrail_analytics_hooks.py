#!/usr/bin/env python
import sys

from charmhelpers.core.hookenv import (
    Hooks,
    UnregisteredHookError,
    config,
    log,
    relation_get,
)

from charmhelpers.fetch import (
    apt_install,
    apt_upgrade,
    apt_update
)

from contrail_analytics_utils import (
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


@hooks.hook("contrail-analytics-relation-joined")
@hooks.hook("contrail-analytics-relation-departed")
def contrail_analytics_relation():
    update_charm_status()


@hooks.hook("contrail-analytics-relation-changed")
def contrail_analytics_changed():
    multi_tenancy = relation_get("multi-tenancy")
    if multi_tenancy is not None:
        config["multi_tenancy"] = multi_tenancy
    update_charm_status()


@hooks.hook("contrail-analyticsdb-relation-joined")
@hooks.hook("contrail-analyticsdb-relation-departed")
def contrail_analyticsdb_relation():
    update_charm_status()


@hooks.hook("identity-admin-relation-changed")
@hooks.hook("identity-admin-relation-departed")
@hooks.hook("identity-admin-relation-broken")
def identity_admin_relation():
    if not relation_get("service_hostname"):
        log("Keystone relation not ready")
    update_charm_status()


@hooks.hook("analytics-cluster-relation-joined")
def analytics_cluster_joined():
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
