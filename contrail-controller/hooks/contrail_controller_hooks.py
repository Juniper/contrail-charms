#!/usr/bin/env python

import json
import sys
import uuid
import yaml

from charmhelpers.core.hookenv import (
    Hooks,
    UnregisteredHookError,
    config,
    log,
    is_leader,
    leader_get,
    leader_set,
    relation_get,
    relation_ids,
    relation_set,
    relation_id,
    related_units,
    status_set,
    remote_unit,
    local_unit,
)

from charmhelpers.fetch import (
    apt_install,
    apt_upgrade,
    apt_update
)

from contrail_controller_utils import (
    update_charm_status,
    CONTAINER_NAME,
    get_analytics_list,
    fix_hostname,
    get_ip
)

from docker_utils import (
    add_docker_repo,
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

    update_charm_status()


@hooks.hook("leader-elected")
def leader_elected():
    if not leader_get("db_user"):
        user = "controller"
        password = uuid.uuid4().hex
        leader_set(db_user=user, db_password=password)
    if not leader_get("rabbitmq_user"):
        user = "contrail"
        password = uuid.uuid4().hex
        vhost = "contrail"
        leader_set(rabbitmq_user=user,
                   rabbitmq_password=password,
                   rabbitmq_vhost=vhost)
        update_northbound_relations()
    update_charm_status()


@hooks.hook("leader-settings-changed")
def leader_settings_changed():
    update_charm_status()


@hooks.hook("config-changed")
def config_changed():
    auth_mode = config.get("auth-mode")
    if auth_mode not in ('rbac', 'cloud-admin', 'no-auth'):
        raise Exception("Config is invalid. auth-mode must one of: "
                        "rbac, cloud-admin, no-auth.")

    update_charm_status()

    if not is_leader():
        return

    update_northbound_relations()
    update_southbound_relations()


def update_northbound_relations(rid=None):
    settings = {
        "auth-mode": config.get("auth-mode"),
        "auth-info": config.get("auth_info"),
        "cloud-orchestrator": config.get("cloud_orchestrator"),
        "ssl-ca": config.get("ssl_ca"),
        "ssl-cert": config.get("ssl_cert"),
        "ssl-key": config.get("ssl_key"),
        "rabbitmq_user": leader_get("rabbitmq_user"),
        "rabbitmq_password": leader_get("rabbitmq_password"),
        "rabbitmq_vhost": leader_get("rabbitmq_vhost"),
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
        "analytics-server": json.dumps(get_analytics_list()),
        "auth-mode": config.get("auth-mode"),
        "auth-info": config.get("auth_info"),
        "ssl-ca": config.get("ssl_ca"),
        "ssl-cert": config.get("ssl_cert"),
        "ssl-key": config.get("ssl_key"),
        "analytics-api-vip": config.get("analytics-api-vip"),
        "contrail-api-vip": config.get("vip"),
    }
    for rid in ([rid] if rid else relation_ids("contrail-controller")):
        relation_set(relation_id=rid, relation_settings=settings)


@hooks.hook("contrail-controller-relation-joined")
def contrail_controller_joined():
    settings = {'private-address': get_ip(), "port": 8082}
    relation_set(relation_settings=settings)

    if remote_unit().startswith("contrail-openstack-compute"):
        config["cloud_orchestrator"] = "openstack"
    # TODO: add other orchestrators
    # TODO: set error if orchestrator is changing and container was started
    if is_leader():
        update_southbound_relations(rid=relation_id())
        update_northbound_relations()
    update_charm_status()


@hooks.hook("contrail-controller-relation-changed")
def contrail_controller_changed():
    data = relation_get()
    changed = False
    keys = ["compute_service_ip", "image_service_ip", "network_service_ip"]
    for key in keys:
        if key not in data:
            continue
        val = data[key]
        if val != config.get(key):
            config[key] = val
            changed = True
    if changed:
        update_charm_status()


@hooks.hook("contrail-controller-relation-departed")
def contrail_controller_departed():
    if not remote_unit().startswith("contrail-openstack-compute"):
        return

    units = [unit for rid in relation_ids("contrail-openstack-compute")
                  for unit in related_units(rid)]
    if units:
        return
    config.pop("cloud_orchestrator")
    if is_leader():
        update_northbound_relations()
    if is_container_launched(CONTAINER_NAME):
        status_set(
            "error",
            "Container is present but cloud orchestrator was disappeared."
            " Please kill container by yourself or restore relation.")


@hooks.hook("controller-cluster-relation-joined")
def cluster_joined():
    settings = {'private-address': get_ip()}
    relation_set(relation_settings=settings)
    update_charm_status()


@hooks.hook("contrail-analytics-relation-joined")
def analytics_joined():
    settings = {'private-address': get_ip()}
    relation_set(relation_settings=settings)
    if is_leader():
        update_northbound_relations(rid=relation_id())
        update_southbound_relations()
    update_charm_status()


@hooks.hook("contrail-analytics-relation-changed")
def analytics_changed():
    config["analytics-api-vip"] = relation_get("analytics-api-vip")
    config.save()
    if is_leader():
        update_southbound_relations()


@hooks.hook("contrail-analytics-relation-departed")
def analytics_departed():
    update_charm_status()
    if is_leader():
        update_southbound_relations()


@hooks.hook("contrail-analyticsdb-relation-joined")
def analyticsdb_joined():
    settings = {'private-address': get_ip()}
    relation_set(relation_settings=settings)
    if is_leader():
        update_northbound_relations(rid=relation_id())


@hooks.hook("contrail-auth-relation-changed")
def contrail_auth_changed():
    auth_info = relation_get("auth-info")
    if auth_info is not None:
        config["auth_info"] = auth_info
    else:
        config.pop("auth_info", None)

    if is_leader():
        update_northbound_relations()
        update_southbound_relations()
    update_charm_status()


@hooks.hook("contrail-auth-relation-departed")
def contrail_auth_departed():
    units = [unit for rid in relation_ids("contrail-auth")
                  for unit in related_units(rid)]
    if units:
        return
    config.pop("auth_info", None)

    if is_leader():
        update_northbound_relations()
        update_southbound_relations()
    update_charm_status()


@hooks.hook("update-status")
def update_status():
    update_charm_status(update_config=False)


@hooks.hook("upgrade-charm")
def upgrade_charm():
    # NOTE: old image can not be deleted if container is running.
    # TODO: so think about killing the container

    # TODO: this hook can be fired when either resource changed or charm code
    # changed. so if code was changed then we may need to update config
    update_charm_status()


@hooks.hook("start")
@hooks.hook("stop")
def todo():
    # TODO: think about it
    pass


def _http_services():
    name = local_unit().replace("/", "-")
    addr = get_ip()
    return [
        {'service_name': 'contrail-webui-http',
         'service_host': '*',
         'service_port': 8080,
         'service_options': [
            'timeout client 86400000',
            'mode http',
            'balance roundrobin',
            'cookie SERVERID insert indirect nocache',
            'timeout server 30000',
            'timeout connect 4000',
         ],
         'servers': [[name, addr, 8080,
            'cookie ' + addr + ' weight 1 maxconn 1024 check port 8082']]},
        {'service_name': 'contrail-api',
         'service_host': '*',
         'service_port': 8082,
         'service_options': [
            'timeout client 3m',
            'option nolinger',
            'timeout server 3m',
            'balance roundrobin',
         ],
         'servers': [[name, addr, 8082, 'check inter 2000 rise 2 fall 3']]}
    ]


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
