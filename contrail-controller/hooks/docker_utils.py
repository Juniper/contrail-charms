import json

from subprocess import (
    CalledProcessError,
    check_call,
    check_output
)
from charmhelpers.core.hookenv import (
    resource_get,
    config,
    log,
    ERROR,
    DEBUG,
    open_port,
)


config = config()


DOCKER_PACKAGES = ["docker.engine"]
DOCKER_CLI = "/usr/bin/docker"


# NOTE: this code assumes that name of container is the part of the
# name of docker image

def add_docker_repo():
    import platform
    cmd = 'curl -fsSL https://apt.dockerproject.org/gpg | sudo apt-key add -'
    check_output(cmd, shell=True)
    dist = platform.linux_distribution()[2].strip()
    cmd = "add-apt-repository " + \
          "\"deb https://apt.dockerproject.org/repo/ " + \
          "ubuntu-%s " % (dist) + \
          "main\""
    check_output(cmd, shell=True)


def is_container_launched(name):
    # NOTE: 'paused' state is not getting into account if someone paused it
    # NOTE: assume that this cmd is the same as inspect of state:
    # [DOCKER_CLI, "inspect", "-f", "{{.State.Running}}", name]
    cmd = DOCKER_CLI + ' ps | grep -w ' + name
    try:
        check_output(cmd, shell=True)
        return True
    except CalledProcessError:
        return False


def is_container_present(name):
    cmd = DOCKER_CLI + ' ps --all | grep -w ' + name
    try:
        check_output(cmd, shell=True)
        return True
    except CalledProcessError:
        return False


def dpkg_version(name, pkg):
    try:
        return check_output([DOCKER_CLI,
                             "exec",
                             name,
                             "dpkg-query",
                             "-f", "${Version}\\n", "-W", pkg]).rstrip()
    except CalledProcessError:
        return None


def load_docker_image(name):
    img_path = resource_get(name)
    if not img_path:
        return False
    image_id = get_docker_image_id(name)
    if image_id:
        # remove previous image
        check_call([DOCKER_CLI, "rmi", image_id])
    check_call([DOCKER_CLI, "load", "-i", img_path])
    return True


def get_docker_image_id(name):
    try:
        output = check_output(DOCKER_CLI + ' images | grep -w ' + name, shell=True)
    except CalledProcessError:
        return None
    output = output.decode().split('\n')
    for line in output:
        parts = line.split()
        if name in parts[0]:
            return parts[2].strip()
    return None


def open_ports(image_id):
    try:
        result = check_output([DOCKER_CLI,
                               "inspect",
                               "-f='{{json .Config.ExposedPorts}}'",
                               image_id
                               ])
        result = result.replace("'", "")
    except CalledProcessError as e:
        log("error in getting ExposedPorts from image. " + str(e), level=ERROR)
        return
    try:
        ports = json.loads(result)
    except Exception as e:
        log("error in decoding ExposedPorts from image: " + result, level=ERROR)
        log(str(e), level=ERROR)
        return

    for pp_str in ports:
        pp = pp_str.split('/')
        open_port(pp[0], pp[1].upper())


def launch_docker_image(name, additional_args=[]):
    image_id = get_docker_image_id(name)
    if not image_id:
        log(name + " docker image is not available", ERROR)
        return

    open_ports(image_id)

    orchestrator = config.get("cloud_orchestrator")
    args = [DOCKER_CLI,
            "run",
            "--net=host",
            "--cap-add=AUDIT_WRITE",
            "--privileged",
            "--restart unless-stopped",
            "--env='CLOUD_ORCHESTRATOR=%s'" % (orchestrator),
            "--volume=/etc/contrailctl:/etc/contrailctl",
            "--name=%s" % name]
    args.extend(additional_args)
    args.extend(["-itd", image_id])
    log("Run container with cmd: " + ' '.join(args))
    check_call(args)


def docker_cp(name, src, dst):
    check_call([DOCKER_CLI, "cp", name + ":" + src, dst])


def apply_config_in_container(name, cfg_name):
    cmd = DOCKER_CLI + ' exec ' + name + ' contrailctl config sync -c ' + cfg_name
    check_call(cmd, shell=True)
