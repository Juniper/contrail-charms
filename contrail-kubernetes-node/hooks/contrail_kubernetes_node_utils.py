from socket import inet_aton
import struct

from charmhelpers.core.hookenv import (
    config,
    related_units,
    relation_get,
    relation_id,
    relation_ids,
    related_units,
    relation_types,
    relations,
    relation_set,
    status_set,
    log,
    leader_get,
)
from charmhelpers.core.templating import render
import common_utils
import docker_utils

from subprocess import (
    check_call,
    check_output,
)


config = config()


BASE_CONFIGS_PATH = "/host/etc_cni/net.d"

CONFIGS_PATH = BASE_CONFIGS_PATH + "/10-contrail.conf"
IMAGES = [
        "contrail-kubernetes-cni-init",
    ]


def get_context():
    ctx = {}
    ctx["log_level"] = config.get("log-level", "SYS_NOTICE")
    ctx["container_registry"] = config.get("docker-registry")
    ctx["contrail_version_tag"] = config.get("image-tag")

    ctx["pod_subnets"] = config.get("pod_subnets")

    log("CTX: {}".format(ctx))
    return ctx


def update_charm_status():
    tag = config.get('image-tag')

    for image in IMAGES:
        try:
            docker_utils.pull(image, tag)
        except Exception as e:
            log("Can't load image {}".format(e))
            status_set('blocked',
                       'Image could not be pulled: {}:{}'.format(image, tag))
            return

    ctx = get_context()
    missing_relations = []
    if not ctx.get("pod_subnets"):
        missing_relations.append("contrail-kubernetes-config")
    if missing_relations:
        status_set('blocked',
                   'Missing relations: ' + ', '.join(missing_relations))
        return
    changed = common_utils.render_and_log("/contrail-cni.yaml",
        CONFIGS_PATH + "/docker-compose.yaml", ctx)

    if changed:
        docker_utils.compose_run(CONFIGS_PATH + "/docker-compose.yaml")

    status_set("active", "Unit is ready")
