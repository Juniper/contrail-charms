import json
import functools
import platform
from time import sleep, time

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
DOCKER_COMPOSE_CLI = "docker-sompse"


def retry(f=None, timeout=10, delay=2):
    """Retry decorator.

    Provides a decorator that can be used to retry a function if it raises
    an exception.

    :param timeout: timeout in seconds (default 10)
    :param delay: retry delay in seconds (default 2)

    Examples::

        # retry fetch_url function
        @retry
        def fetch_url():
            # fetch url

        # retry fetch_url function for 60 secs
        @retry(timeout=60)
        def fetch_url():
            # fetch url
    """
    if not f:
        return functools.partial(retry, timeout=timeout, delay=delay)

    @functools.wraps(f)
    def func(*args, **kwargs):
        start = time()
        error = None
        while True:
            try:
                return f(*args, **kwargs)
            except Exception as e:
                error = e
            elapsed = time() - start
            if elapsed >= timeout:
                raise error
            remaining = timeout - elapsed
            sleep(delay if delay <= remaining else remaining)
    return func


# NOTE: this code assumes that name of container is the part of the
# name of docker image

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
