import json
import platform

from subprocess import (
    CalledProcessError,
    check_call,
    check_output
)
from charmhelpers.core.hookenv import (
    config,
    log,
    WARNING,
)
from charmhelpers.core.host import service_restart


config = config()


DOCKER_PACKAGES = ["docker.engine", "docker-compose"]
DOCKER_CLI = "/usr/bin/docker"
DOCKER_COMPOSE_CLI = "docker-compose"


def add_docker_repo():
    try:
        cmd = ["/bin/bash", "-c",
               "set -o pipefail ; curl -fsSL --connect-timeout 10 "
               "https://apt.dockerproject.org/gpg | sudo apt-key add -"]
        check_output(cmd)
        dist = platform.linux_distribution()[2].strip()
        cmd = "add-apt-repository " + \
              "\"deb https://apt.dockerproject.org/repo/ " + \
              "ubuntu-%s " % (dist) + \
              "main\""
        check_output(cmd, shell=True)
    except CalledProcessError as e:
        log("Official docker repo is not available: {}".format(e),
            level=WARNING)


def apply_docker_insecure():
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


def docker_login():
    login = config.get("docker-user")
    password = config.get("docker-password")
    docker_registry = config.get("docker-registry")
    if login and password:
        check_call([DOCKER_CLI, "login", "-u", login, "-p",
                    password, docker_registry])


# TODO: fix it
def get_contrail_version(pkg="python-contrail"):
    image_name = config.get("image-name")
    image_tag = config.get("image-tag")
    image_id = "{}:{}".format(image_name, image_tag)
    return check_output([DOCKER_CLI,
        "run", "--rm", "--entrypoint", "dpkg-query",
        image_id, "-f", "${Version}", "-W", pkg]).rstrip()


def docker_cp(name, src, dst):
    check_call([DOCKER_CLI, "cp", name + ":" + src, dst])


def docker_exec(name, cmd, shell=False):
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


def docker_pull(registry, name, tag):
    check_call([DOCKER_CLI, "pull", "{}/{}:{}".format(registry, name, tag)])


def docker_compose_run(path):
    check_call([DOCKER_COMPOSE_CLI, "up", "-d", "--project-directory", path])


def docker_remove_container_by_image(image):
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


def docker_run(registry, image, tag, volumes):
    image_id = "{}/{}:{}".format(registry, image, tag)
    args = [DOCKER_CLI, "run", "--rm", "-i", "--network", "host"]
    for volume in volumes:
        args.extend(["-v", volume])
    args.extend([image_id])
    check_call(args)
