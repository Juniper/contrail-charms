import json
import platform

from subprocess import (
    check_call,
    check_output
)
from charmhelpers.core.hookenv import (
    config,
    log,
)
from charmhelpers.fetch import (
    apt_install,
    apt_update,
)
from charmhelpers.core.host import service_restart


config = config()


DOCKER_PACKAGES = ["docker.ce", "docker-compose"]
DOCKER_CLI = "/usr/bin/docker"
DOCKER_COMPOSE_CLI = "docker-compose"


def install():
    apt_install(["apt-transport-https", "ca-certificates", "curl",
                 "software-properties-common"])
    cmd = ["/bin/bash", "-c",
           "set -o pipefail ; curl -fsSL --connect-timeout 10 "
           "https://download.docker.com/linux/ubuntu/gpg "
           "| sudo apt-key add -"]
    check_output(cmd)
    dist = platform.linux_distribution()[2].strip()
    cmd = ("add-apt-repository "
           "\"deb [arch=amd64] https://download.docker.com/linux/ubuntu "
           + dist + " stable\"")
    check_output(cmd, shell=True)
    apt_update()
    apt_install(DOCKER_PACKAGES)


def apply_insecure():
    if not config.get("docker-registry-insecure"):
        return
    docker_registry = config.get("docker-registry")

    log("Re-configure docker daemon")
    dc = {}
    try:
        with open("/etc/docker/daemon.json") as f:
            dc = json.load(f)
    except Exception as e:
        log("There is no docker config. Creating... (Err = {})".format(e))

    cv = dc.get("insecure-registries", list())
    if docker_registry in cv:
        return
    cv.append(docker_registry)
    dc["insecure-registries"] = cv

    with open("/etc/docker/daemon.json", "w") as f:
        json.dump(dc, f)

    log("Restarting docker service")
    service_restart('docker')


def login():
    login = config.get("docker-user")
    password = config.get("docker-password")
    docker_registry = config.get("docker-registry")
    if login and password:
        check_call([DOCKER_CLI, "login", "-u", login, "-p",
                    password, docker_registry])


def cp(name, src, dst):
    check_call([DOCKER_CLI, "cp", name + ":" + src, dst])


def execute(name, cmd, shell=False):
    cli = [DOCKER_CLI, "exec", name]
    if isinstance(cmd, list):
        cli.extend(cmd)
    else:
        cli.append(cmd)
    if shell:
        output = check_output(' '.join(cli), shell=True)
    else:
        output = check_output(cli)
    return output.decode('UTF-8')


def pull(image, tag):
    registry = config.get("docker-registry")
    check_call([DOCKER_CLI, "pull", "{}/{}:{}".format(registry, image, tag)])


def compose_run(path):
    check_call([DOCKER_COMPOSE_CLI, "-f", path, "up", "-d"])


def remove_container_by_image(image):
    output = check_output([DOCKER_CLI, "ps", "-a"]).decode('UTF-8')
    containers = [line.split() for line in output.splitlines()][1:]
    for cnt in containers:
        if len(cnt) < 2:
            # bad string. normal output contains 6-7 fields.
            continue
        cnt_image = cnt[1]
        index = cnt_image.find(image)
        if index < 0 or (index > 0 and cnt_image[index - 1] != '/'):
            # TODO: there is a case when image name just a prefix...
            continue
        check_call([DOCKER_CLI, "rm", cnt[0]])


def run(image, tag, volumes, remove=False):
    registry = config.get("docker-registry")
    image_id = "{}/{}:{}".format(registry, image, tag)
    args = [DOCKER_CLI, "run"]
    if remove:
        args.append("--rm")
    args.extend(["-i", "--network", "host"])
    for volume in volumes:
        args.extend(["-v", volume])
    args.extend([image_id])
    check_call(args)


def get_contrail_version(image, tag, pkg="python-contrail"):
    image_id = "{}:{}".format(image, tag)
    return check_output([DOCKER_CLI,
        "run", "--rm", "--entrypoint", "rpm", image_id,
        "-q", "--qf", "'%{VERSION}-%{RELEASE}'", pkg]).decode("UTF-8").rstrip()
