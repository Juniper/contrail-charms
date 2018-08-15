#!/usr/bin/env python
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
    local_unit,
)

from charmhelpers.fetch import (
    apt_upgrade,
    apt_update
)

import contrail_analytics_utils as utils
import common_utils
import docker_utils


hooks = Hooks()
config = config()


@hooks.hook("install.real")
def install():
    status_set("maintenance", "Installing...")

    # TODO: try to remove this call
    common_utils.fix_hostname()

    apt_update(fatal=False)
    apt_upgrade(fatal=True, dist=True)

    docker_utils.install_docker()
    docker_utils.apply_docker_insecure()
    docker_utils.docker_login()

    utils.update_charm_status()


@hooks.hook("config-changed")
def config_changed():
    if config.changed("control-network"):
        settings = {'private-address': common_utils.get_ip()}
        rnames = ("contrail-analytics", "contrail-analyticsdb",
                  "analytics-cluster", "http-services")
        for rname in rnames:
            for rid in relation_ids(rname):
                relation_set(relation_id=rid, relation_settings=settings)

    if config.changed("docker-registry"):
        docker_utils.apply_docker_insecure()
    if config.changed("docker-user") or config.changed("docker-password"):
        docker_utils.docker_login()

    utils.update_charm_status()


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


@hooks.hook("contrail-analytics-relation-joined")
def contrail_analytics_joined():
    settings = {"private-address": common_utils.get_ip()}
    relation_set(relation_settings=settings)


@hooks.hook("contrail-analytics-relation-changed")
def contrail_analytics_changed():
    data = relation_get()
    changed = False
    changed |= _value_changed(data, "auth-mode", "auth_mode")
    changed |= _value_changed(data, "auth-info", "auth_info")
    changed |= _value_changed(data, "orchestrator-info", "orchestrator_info")
    changed |= _value_changed(data, "ssl-enabled", "ssl_enabled")
    changed |= _value_changed(data, "rabbitmq_hosts", "rabbitmq_hosts")
    # TODO: handle changing of all values
    # TODO: set error if orchestrator is changing and container was started
    if changed:
        utils.update_charm_status()


@hooks.hook("contrail-analytics-relation-departed")
def contrail_analytics_departed():
    units = [unit for rid in relation_ids("contrail-controller")
                  for unit in related_units(rid)]
    if not units:
        for key in ["auth_info", "auth_mode", "orchestrator_info",
                    "ssl_enabled", "rabbitmq_hosts"]:
            config.pop(key, None)
    utils.update_charm_status()


@hooks.hook("contrail-analyticsdb-relation-joined")
def contrail_analyticsdb_joined():
    settings = {"private-address": common_utils.get_ip(),
                'unit-type': 'analytics'}
    relation_set(relation_settings=settings)


@hooks.hook("contrail-analyticsdb-relation-changed")
def contrail_analyticsdb_changed():
    utils.update_charm_status()


@hooks.hook("contrail-analyticsdb-relation-departed")
def contrail_analyticsdb_departed():
    utils.update_charm_status()


@hooks.hook("analytics-cluster-relation-joined")
def analytics_cluster_joined():
    settings = {"private-address": common_utils.get_ip()}
    relation_set(relation_settings=settings)

    utils.update_charm_status()


@hooks.hook("update-status")
def update_status():
    utils.update_charm_status()


@hooks.hook("upgrade-charm")
def upgrade_charm():
    # NOTE: image can not be deleted if container is running.
    # TODO: so think about killing the container

    # NOTE: this hook can be fired when either resource changed or charm code
    # changed. so if code was changed then we may need to update config
    utils.update_charm_status()


def _http_services():
    name = local_unit().replace("/", "-")
    addr = common_utils.get_ip()
    return [{"service_name": "contrail-analytics-api",
             "service_host": "*",
             "service_port": 8081,
             "service_options": ["option nolinger", "balance roundrobin"],
             "servers": [[name, addr, 8081, "check inter 2000 rise 2 fall 3"]]
            }]


@hooks.hook("http-services-relation-joined")
def http_services_joined():
    relation_set(services=yaml.dump(_http_services()))


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log("Unknown hook {} - skipping.".format(e))


if __name__ == "__main__":
    main()
