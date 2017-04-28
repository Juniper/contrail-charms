import json
from subprocess import check_call
import time

import apt_pkg

from charmhelpers.core.hookenv import (
    config,
    related_units,
    relation_get,
    relation_ids,
    status_set,
    application_version_set,
)
from charmhelpers.core.templating import render

from docker_utils import (
    is_container_launched,
    is_container_present,
    apply_config_in_container,
    launch_docker_image,
    docker_cp,
    dpkg_version,
    get_docker_image_id
)

apt_pkg.init()
config = config()


CONTAINER_NAME = "contrail-agent"
CONFIG_NAME = "agent"


def identity_admin_ctx():
    auth_info = config.get("auth_info")
    return (json.loads(auth_info) if auth_info else {})


def lb_ctx():
    for rid in relation_ids("contrail-controller"):
        for unit in related_units(rid):
            return {"controller_ip":
                        relation_get("private-address", unit, rid)}
    return {}


def remove_juju_bridges():
    cmd = "scripts/remove-juju-bridges.sh"
    check_call(cmd)


def get_context():
    ctx = {}
    ctx.update({"cloud_orchestrator": config.get("cloud_orchestrator")})
    ctx.update(identity_admin_ctx())
    ctx.update(lb_ctx())
    return ctx


def render_config(ctx=None):
    if not ctx:
        ctx = get_context()
    render("agent.conf", "/etc/contrailctl/agent.conf", ctx)


def update_charm_status(update_config=True):
    if is_container_launched(CONTAINER_NAME):
        status_set("active", "Unit ready")
        if update_config:
            render_config()
            apply_config_in_container(CONTAINER_NAME, CONFIG_NAME)
        return

    if is_container_present(CONTAINER_NAME):
        status_set(
            "error",
            "Container is present but is not running. Run or remove it.")
        return

    image_id = get_docker_image_id(CONTAINER_NAME)
    if not image_id:
        status_set('waiting', 'Awaiting for container resource')
        return

    ctx = get_context()
    missing_relations = []
    if not ctx.get("controller_ip"):
        missing_relations.append("contrail-controller")
    if missing_relations:
        status_set('waiting',
                   'Missing relations: ' + ', '.join(missing_relations))
        return
    if not ctx.get("keystone_ip"):
        status_set('waiting',
                   'Missing auth info in relation with contrail-controller.')
        return
    # TODO: what should happens if relation departed?

    render_config(ctx)
    launch_docker_image(CONTAINER_NAME,
                        ["--volume=/usr/src:/usr/src",
                         "--volume=/lib/modules:/lib/modules"])
    # TODO: find a way to do not use 'sleep'
    time.sleep(5)
    # TODO: looks like that this step is needed only for OpenStack
    # NOTE: agent container specific code
    docker_cp(CONTAINER_NAME,
              "/usr/bin/vrouter-port-control",
              "/usr/bin/")

    version = dpkg_version(CONTAINER_NAME, "contrail-vrouter-agent")
    application_version_set(version)
    status_set("active", "Unit ready")
