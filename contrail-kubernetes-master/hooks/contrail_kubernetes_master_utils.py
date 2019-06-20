import json
from socket import inet_aton
import struct
import time
import os
import base64

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
    is_leader,
    leader_get,
    leader_set,
    unit_private_ip,
    charm_dir,

)
from charmhelpers.core.templating import render

import common_utils
import docker_utils
from subprocess import (
    check_output,
)


config = config()


BASE_CONFIGS_PATH = "/etc/contrail"

CONFIGS_PATH = BASE_CONFIGS_PATH + "/contrail-kubernetes"
IMAGES = [
        "contrail-kubernetes-kube-manager",
    ]


def kubernetes_token():
    try:
        account_file = os.path.join(charm_dir(), 'files', 'contrail-kubemanager-serviceaccount.yaml')
        check_output(["snap", "run", "kubectl", "apply", "-f", account_file])
    except:
        return None
    token_id = None
    for i in range (10):
        try:
            token_id = check_output(["snap", "run", "kubectl", "get", "sa", "contrail-kubemanager", "-n", "contrail",
                                "-ogo-template=\"{{(index .secrets 0).name}}\""]).strip('\"')
        except:
            return None
        if token_id:
            break
        time.sleep(1)
    if not token_id:
        return None
    try:
        token_64 = check_output(["snap", "run", "kubectl", "get", "secret", token_id, "-n", "contrail",
                            "-ogo-template=\"{{.data.token}}\""]).strip('\"')
        token = base64.b64decode(token_64)
        return token
    except:
        return None


def get_context():
    ctx = {}
    ctx["log_level"] = config.get("log-level", "SYS_NOTICE")
    ctx["container_registry"] = config.get("docker-registry")
    ctx["contrail_version_tag"] = config.get("image-tag")

    ctx["cluster_name"] = config.get("cluster_name")
    ctx["cluster_project"] = config.get("cluster_project")
    ctx["pod_subnets"] = config.get("pod_subnets")
    ctx["ip_fabric_subnets"] = config.get("ip_fabric_subnets")
    ctx["service_subnets"] = config.get("service_subnets")
    ctx["ip_fabric_forwarding"] = config.get("ip_fabric_forwarding")
    ctx["ip_fabric_snat"] = config.get("ip_fabric_snat")
    ctx["host_network_service"] = config.get("host_network_service")
    ctx["public_fip_pool"] = config.get("public_fip_pool")

    ctx.update(common_utils.json_loads(leader_get("orchestrator-info"), dict()))

    ips = [relation_get("private-address", unit, rid)
           for rid in relation_ids("contrail-controller")
           for unit in related_units(rid)]
    ctx["controller_servers"] = ips
    ips = common_utils.json_loads(config.get("analytics_servers"), list())
    ctx["analytics_servers"] = ips

    log("CTX: {}".format(ctx))
    return ctx


def update_kube_manager_token():
    if not is_leader() or leader_get("kube_manager_token"):
        return
    token = kubernetes_token()
    if token:
        leader_set({"kube_manager_token":token})


def update_orchestrator_info():
    data = common_utils.json_loads(leader_get("orchestrator-info"), dict())
    values = dict()

    def _check_key(key):
        val = data.get(key)
        get = leader_get(key)
        if val != get:
            values[key] = get

    _check_key("kube_manager_token")
    _check_key("kubernetes_api_server")
    _check_key("kubernetes_api_secure_port")
    return values


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
    if not ctx.get("controller_servers"):
        missing_relations.append("contrail-controller")
    if not ctx.get("kubernetes_api_server"):
        missing_relations.append("kube-api-endpoint")
    if missing_relations:
        status_set('blocked',
                   'Missing relations: ' + ', '.join(missing_relations))
        return
    if not ctx.get("kube_manager_token") or ctx.get("kube_manager_token") == "":
        status_set('waiting',
                   'Kube manager token undefined. Wait to kubectl is running.')
        return
    changed = common_utils.render_and_log("kube-manager.env",
        BASE_CONFIGS_PATH + "/common_kubemanager.env", ctx)
    changed |= common_utils.render_and_log("/contrail-kubemanager.yaml",
        CONFIGS_PATH + "/docker-compose.yaml", ctx)

    if changed:
        docker_utils.compose_run(CONFIGS_PATH + "/docker-compose.yaml")

    status_set("active", "Unit is ready")
