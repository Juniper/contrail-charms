#!/usr/bin/env python

import uuid
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
    leader_set,
    leader_get,
    is_leader,
    relation_id,
)

from charmhelpers.fetch import (
    apt_install,
    apt_upgrade,
    apt_update
)

from contrail_analyticsdb_utils import (
    update_charm_status,
    CONTAINER_NAME,
)
from common_utils import (
    get_ip,
    fix_hostname,
)
from docker_utils import (
    add_docker_repo,
    apply_docker_insecure,
    docker_login,
    DOCKER_PACKAGES,
    is_container_launched,
)


PACKAGES = []


hooks = Hooks()
config = config()


@hooks.hook("install.real")
def install():
    status_set('maintenance', 'Installing...')

    # TODO: try to remove this call
    fix_hostname()

    apt_upgrade(fatal=True, dist=True)
    add_docker_repo()
    apt_update(fatal=False)
    apt_install(PACKAGES + DOCKER_PACKAGES, fatal=True)

    apply_docker_insecure()
    docker_login()

    update_charm_status()


@hooks.hook("leader-elected")
def leader_elected():
    if not leader_get("db_user"):
        user = "analytics"
        password = uuid.uuid4().hex
        leader_set(db_user=user, db_password=password)
        _update_relation()
    update_charm_status()


@hooks.hook("leader-settings-changed")
def leader_settings_changed():
    update_charm_status()


@hooks.hook("config-changed")
def config_changed():
    if config.changed("control-network"):
        settings = {'private-address': get_ip()}
        rnames = ("contrail-analyticsdb", "analyticsdb-cluster")
        for rname in rnames:
            for rid in relation_ids(rname):
                relation_set(relation_id=rid, relation_settings=settings)

    if config.changed("docker-registry"):
        apply_docker_insecure()
    if config.changed("docker-user") or config.changed("docker-password"):
        docker_login()

    update_charm_status()


def _update_relation(rid=None):
    db_user = leader_get("db_user")
    db_password = leader_get("db_password")
    if not db_user or not db_password:
        return

    settings = {
        "db-user": db_user,
        "db-password": db_password
    }

    if rid:
        relation_set(relation_id=rid, relation_settings=settings)
        return

    for rid in relation_ids("contrail-analyticsdb"):
        relation_set(relation_id=rid, relation_settings=settings)


@hooks.hook("contrail-analyticsdb-relation-joined")
def analyticsdb_joined():
    settings = {'private-address': get_ip()}
    relation_set(relation_settings=settings)
    if is_leader():
        _update_relation(rid=relation_id())


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
    changed |= _value_changed(data, "ssl-enabled", "ssl_enabled")
    # TODO: handle changing of all values
    # TODO: set error if orchestrator is changing and container was started
    if changed:
        update_charm_status()


@hooks.hook("contrail-analyticsdb-relation-departed")
def analyticsdb_departed():
    units = [unit for rid in relation_ids("contrail-controller")
                  for unit in related_units(rid)]
    if not units:
        for key in ["auth_info", "orchestrator_info", "ssl_enabled"]:
            config.pop(key, None)
        if is_container_launched(CONTAINER_NAME):
            status_set(
                "blocked",
                "Container is present but cloud orchestrator was disappeared."
                " Please kill container by yourself or restore"
                " cloud orchestrator.")
    update_charm_status()


@hooks.hook("analyticsdb-cluster-relation-joined")
def analyticsdb_cluster_joined():
    settings = {'private-address': get_ip()}
    relation_set(relation_settings=settings)


@hooks.hook("update-status")
def update_status():
    update_charm_status(update_config=False)


@hooks.hook("upgrade-charm")
def upgrade_charm():
    # NOTE: image can not be deleted if container is running.
    # TODO: so think about killing the container

    # clear cached version of image
    config.pop("version_with_build", None)
    config.pop("version", None)
    config.save()

    # NOTE: this hook can be fired when either resource changed or charm code
    # changed. so if code was changed then we may need to update config
    update_charm_status()


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log("Unknown hook {} - skipping.".format(e))


if __name__ == "__main__":
    main()
