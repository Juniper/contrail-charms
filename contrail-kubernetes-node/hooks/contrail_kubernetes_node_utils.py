from charmhelpers.core.hookenv import (
    config,
    status_set,
    log,
)
import common_utils
import docker_utils


config = config()

MODULE = "kubernetes-node"
BASE_CONFIGS_PATH = "/etc/contrail"

CONFIGS_PATH = BASE_CONFIGS_PATH + "/contrail-kubernetes-node"
IMAGES = [
    "contrail-kubernetes-cni-init",
]


def get_context():
    ctx = {}
    ctx["module"] = MODULE
    ctx["log_level"] = config.get("log-level", "SYS_NOTICE")
    ctx["container_registry"] = config.get("docker-registry")
    ctx["contrail_version_tag"] = config.get("image-tag")

    ctx["nested_mode"] = config.get("nested_mode")
    if ctx["nested_mode"]:
        ctx["nested_mode_config"] = common_utils.json_loads(config.get("nested_mode_config"), dict())

    ctx["logging"] = docker_utils.render_logging()

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
    changed = common_utils.render_and_log("cni.env",
        BASE_CONFIGS_PATH + "/common_cni.env", ctx)
    changed |= common_utils.render_and_log("/contrail-cni.yaml",
        CONFIGS_PATH + "/docker-compose.yaml", ctx)
    docker_utils.compose_run(CONFIGS_PATH + "/docker-compose.yaml", changed)

    status_set("active", "Unit is ready")
