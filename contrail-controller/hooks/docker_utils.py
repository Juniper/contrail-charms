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
    resource_get,
    config,
    log,
    ERROR,
    WARNING,
)
from charmhelpers.core.host import service_restart


config = config()


DOCKER_PACKAGES = ["docker.engine"]
DOCKER_CLI = "/usr/bin/docker"


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
    docker_registry = config.get("docker-registry")
    if not docker_registry:
        return

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
        check_call([DOCKER_CLI, "login", "-u", login, "-p", password, docker_registry])


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


def get_contrail_version(pkg="python-contrail"):
    image_name = config.get("image-name")
    image_tag = config.get("image-tag")
    image_id = "{}:{}".format(image_name, image_tag)
    return check_output([DOCKER_CLI,
        "run", "--rm", "--entrypoint", "dpkg-query",
        image_id, "-f", "${Version}", "-W", pkg]).rstrip()


def load_docker_image(name):
    img_path = resource_get(name)
    if not img_path:
        return None, None
    output = check_output([DOCKER_CLI, "load", "-q", "-i", img_path])
    if "sha256:" not in output:
        # suppose that file has name/tag inside. just eval it from output
        res = output.rstrip().split(' ')[2].split(":")
        return res[0], res[1]

    sha = output.rstrip().split(' ')[2].split(":")[1]
    # name can be sha[0:12] but looks like that resource name can be used
    tag = "latest"
    check_call([DOCKER_CLI, "tag", sha, "{}:{}".format(name, tag)])
    return name, tag


def launch_docker_image(name, additional_args=[]):
    image_name = config.get("image-name")
    image_tag = config.get("image-tag")
    if not image_name or not image_tag:
        log("Docker image is not available", level=ERROR)
        return

    image_id = "{}:{}".format(image_name, image_tag)
    orchestrator = config.get("cloud_orchestrator")
    args = [DOCKER_CLI,
            "run",
            "--net=host",
            "--cap-add=AUDIT_WRITE",
            "--privileged",
            "--restart=unless-stopped",
            "--env='CLOUD_ORCHESTRATOR=%s'" % (orchestrator),
            "--volume=/etc/contrailctl:/etc/contrailctl",
            "--name=%s" % name]
    args.extend(additional_args)
    args.extend(["-itd", image_id])
    log("Run container with cmd: " + ' '.join(args))
    check_call(args)


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


@retry(timeout=32, delay=10)
def apply_config_in_container(name, cfg_name):
    try:
        cmd = (DOCKER_CLI + ' exec ' + name + ' contrailctl config sync -v'
               + ' -c ' + cfg_name)
        check_call(cmd, shell=True)
        return True
    except CalledProcessError as e:
        if e.returncode == 137:
            log("Container was restarted. " + str(e.output), level=ERROR)
            return False
        raise
