import base64
import json
import os
import platform
from subprocess import check_call, check_output
import uuid
import yaml

from charmhelpers.core.hookenv import (
    config,
    log,
    DEBUG,
    env_proxy_settings,
)
from charmhelpers.core.host import service_restart
from charmhelpers.core.templating import render
from charmhelpers.fetch import apt_install, apt_update

config = config()

DOCKER_ADD_PACKAGES = ["docker-compose"]
DOCKER_CLI = "/usr/bin/docker"
DOCKER_COMPOSE_CLI = "docker-compose"


def _format_curl_https_proxy_opt():
    proxy_settings = env_proxy_settings(['https'])
    https_proxy = None
    if proxy_settings:
        https_proxy = proxy_settings.get('https_proxy')
        return '--proxy {}'.format(https_proxy) if https_proxy else ''
    return ''


def install():
    docker_runtime = config.get("docker_runtime")
    if docker_runtime == "apt" or docker_runtime == "auto":
        docker_package = "docker.io"
        docker_repo = None
        docker_key_url = None
    elif docker_runtime == "upstream":
        docker_package = "docker.ce"
        docker_repo = "deb [arch={ARCH}] https://download.docker.com/linux/ubuntu {CODE} stable"
        docker_key_url = "https://download.docker.com/linux/ubuntu/gpg"
    else:
        # custom or default
        docker_package = config.get("docker_runtime_package") or "docker.ce"
        docker_repo = (config.get("docker_runtime_repo") or
                       "deb [arch={ARCH}] https://download.docker.com/linux/ubuntu {CODE} stable")
        docker_key_url = config.get("docker_runtime_key_url") or "https://download.docker.com/linux/ubuntu/gpg"

    apt_install(["apt-transport-https", "ca-certificates", "curl",
                 "software-properties-common"])
    if docker_key_url:
        cmd = [
            "/bin/bash", "-c",
            "set -o pipefail ; curl {} "
            "-fsSL --connect-timeout 10 "
            "{} | sudo apt-key add -"
            "".format(_format_curl_https_proxy_opt(), docker_key_url)
        ]
        check_output(cmd)
    arch = "amd64"
    dist = platform.linux_distribution()[2].strip()
    if docker_repo:
        cmd = ("add-apt-repository \"{}\"".format(docker_repo.replace("{ARCH}", arch).replace("{CODE}", dist)))
        check_output(cmd, shell=True)
    apt_update()
    apt_install(docker_package)
    apt_install(DOCKER_ADD_PACKAGES)
    _render_config()
    _apply_insecure()
    _login()


def _load_json_file(filepath):
    try:
        with open(filepath) as f:
            return json.load(f)
    except Exception as e:
        pass
    return dict()


def _save_json_file(filepath, data):
    try:
        os.mkdir(os.path.dirname(filepath))
    except OSError:
        pass
    with open(filepath, "w") as f:
        json.dump(data, f)


def _apply_insecure():
    if not config.get("docker-registry-insecure"):
        return
    # NOTE: take just host and port from registry definition
    docker_registry = config.get("docker-registry").split('/')[0]

    log("Re-configure docker daemon")
    dc = _load_json_file("/etc/docker/daemon.json")

    cv = dc.get("insecure-registries", list())
    if docker_registry in cv:
        return
    cv.append(docker_registry)
    dc["insecure-registries"] = cv

    _save_json_file("/etc/docker/daemon.json", dc)

    log("Restarting docker service")
    service_restart('docker')


def _login():
    # 'docker login' doesn't work simply on Ubuntu 18.04. let's hack.
    login = config.get("docker-user")
    password = config.get("docker-password")
    if not login or not password:
        return

    auth = base64.b64encode("{}:{}".format(login, password).encode()).decode()
    docker_registry = config.get("docker-registry")
    config_path = os.path.join(os.path.expanduser("~"), ".docker/config.json")
    data = _load_json_file(config_path)
    data.setdefault("auths", dict())[docker_registry] = {"auth": auth}
    _save_json_file(config_path, data)


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


def get_image_id(image, tag):
    registry = config.get("docker-registry")
    return "{}/{}:{}".format(registry, image, tag)


def pull(image, tag):
    # check image presense
    try:
        check_call([DOCKER_CLI, "inspect", get_image_id(image, tag)])
        return
    except Exception:
        pass
    # pull image
    check_call([DOCKER_CLI, "pull", get_image_id(image, tag)])


def compose_run(path, config_changed):
    do_update = config_changed
    if not do_update:
        # check count of services
        count = None
        with open(path, 'r') as fh:
            data = yaml.load(fh)
            count = len(data['services'])
        # check is it run or not
        actual_count = len(check_output([DOCKER_COMPOSE_CLI, "-f", path, "ps", "-q"]).decode("UTF-8").splitlines())
        log("Services actual count: {}, required count: {}".format(actual_count, count), level=DEBUG)
        do_update = actual_count != count
    if do_update:
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


def run(image, tag, volumes, remove=False, env_dict=None):
    image_id = get_image_id(image, tag)
    args = [DOCKER_CLI, "run"]
    if remove:
        args.append("--rm")
    args.extend(["-i", "--network", "host"])
    for volume in volumes:
        args.extend(["-v", volume])
    if env_dict:
        for key in env_dict:
            args.extend(["-e", "{}={}".format(key, env_dict[key])])
    log_driver = config.get("docker-log-driver")
    if log_driver:
        args.extend(["--log-driver", log_driver])
    log_options = config.get("docker-log-options")
    if log_options:
        for opt in log_options.split():
            args.extend(["--log-opt", opt])
    args.extend([image_id])
    check_call(args)


def create(image, tag):
    name = str(uuid.uuid4())
    image_id = get_image_id(image, tag)
    args = [DOCKER_CLI, "create", "--name", name, "--entrypoint", "/bin/true", image_id]
    check_call(args)
    return name


def get_contrail_version(image, tag, pkg="python-contrail"):
    image_id = get_image_id(image, tag)
    try:
        args = [DOCKER_CLI, "image", "inspect", "--format='{{.Config.Labels.version}}'", image_id]
        version = check_output(args).decode("UTF-8").rstrip().strip("'")
        if version != '<no value>':
            return version
    except Exception:
        pass
    return check_output([DOCKER_CLI,
        "run", "--rm", "--entrypoint", "rpm", image_id,
        "-q", "--qf", "%{VERSION}-%{RELEASE}", pkg]).decode("UTF-8").rstrip()


def config_changed():
    changed = False
    if config.changed("http_proxy") or config.changed("https_proxy") or config.changed("no_proxy"):
        _render_config()
        changed = True
    if config.changed("docker-registry") or config.changed("docker-registry-insecure"):
        _apply_insecure()
        changed = True
    if config.changed("docker-user") or config.changed("docker-password"):
        _login()
        changed = True
    return changed


def _render_config():
    # From https://docs.docker.com/config/daemon/systemd/#httphttps-proxy
    if len(config.get('no_proxy')) > 2023:
        raise Exception('no_proxy longer than 2023 chars.')
    render('docker-proxy.conf', '/etc/systemd/system/docker.service.d/docker-proxy.conf', config)
    check_call(['systemctl', 'daemon-reload'])
    service_restart('docker')


def render_logging():
    driver = config.get("docker-log-driver")
    options = config.get("docker-log-options", '').split()
    if not driver and not options:
        return ''
    logging = 'logging:\n'
    if driver:
        logging += "  driver: {}\n".format(driver)
    if options:
        logging += "  options:\n"
        # yaml is created manually because of redis.yaml that is created by 
        # controller and analytics and should be exactly the same to avoid 
        # config_changed hooks starting
        options.sort()
        for opt in options:
            option = opt.split('=')
            logging += '    {}: "{}"\n'.format(option[0], option[1])
    return logging
