import json
import os
from base64 import b64decode
from socket import gaierror, gethostbyname, gethostname
from subprocess import CalledProcessError, check_call, check_output

import netifaces

import docker_utils
from charmhelpers.contrib.network.ip import (
    get_address_in_network,
    get_iface_addr
)
from charmhelpers.core.hookenv import (
    ERROR,
    application_version_set,
    config,
    log,
    status_set
)
from charmhelpers.core.host import file_hash, write_file
from charmhelpers.core.templating import render

config = config()


def get_ip():
    network = config.get("control-network")
    if network:
        # try to get ip from CIDR
        try:
            return get_address_in_network(network)
        except Exception:
            pass
        # try to get ip from interface name
        try:
            return get_iface_addr(network)
        except Exception:
            pass

    return _get_default_ip()


def _get_default_ip():
    if hasattr(netifaces, "gateways"):
        iface = netifaces.gateways()["default"][netifaces.AF_INET][1]
    else:
        data = check_output("ip route | grep ^default", shell=True).split()
        iface = data[data.index("dev") + 1]
    return netifaces.ifaddresses(iface)[netifaces.AF_INET][0]["addr"]


def fix_hostname():
    hostname = gethostname()
    try:
        gethostbyname(hostname)
    except gaierror:
        ip = get_ip()
        check_call(["sed", "-E", "-i", "-e",
            ("/127.0.0.1[[:blank:]]+/a \\\n" + ip + " " + hostname),
            "/etc/hosts"])


def decode_cert(key):
    val = config.get(key)
    if not val:
        return None
    try:
        return b64decode(val)
    except Exception as e:
        log("Couldn't decode certificate from config['{}']: {}".format(
            key, str(e)), level=ERROR)
    return None


def save_file(path, data, perms=0o400):
    if data:
        fdir = os.path.dirname(path)
        if not os.path.exists(fdir):
            os.makedirs(fdir)
        write_file(path, data, perms=perms)
    elif os.path.exists(path):
        os.remove(path)


def update_services_status(services):
    try:
        output = check_output("contrail-status")
    except CalledProcessError as e:
        log("Container is not ready to get contrail-status: " + str(e))
        status_set("waiting", "Waiting services to run in container")
        return

    statuses = dict()
    group = None
    for line in output.splitlines()[1:]:
        words = line.split()
        if len(words) == 4 and words[0] == "==" and words[3] == "==":
            group = words[2]
            continue
        if len(words) == 0:
            group = None
            continue
        if group and len(words) >= 2 and group in services:
            srv = words[0].split(":")[0]
            statuses.setdefault(group, dict())[srv] = (
                words[1], " ".join(words[2:]))

    for group in services:
        if group not in statuses:
            status_set("waiting",
                       "POD " + group + " is absent in the contrail-status")
            return
        for srv in services[group]:
            if srv not in statuses[group]:
                status_set("waiting",
                           srv + " is absent in the contrail-status")
                return
            status, desc = statuses[group].get(srv)
            if status not in ["active", "backup"]:
                workload = "waiting" if status == "initializing" else "blocked"
                status_set(workload, "{} is not ready. Reason: {}"
                           .format(srv, desc))
                return

    status_set("active", "Unit is ready")
    try:
        tag = config.get('image-tag')
        version = docker_utils.get_contrail_version("contrail-base", tag)
        application_version_set(version)
    except CalledProcessError as e:
        log("Couldn't detect installed application version: " + str(e))


def json_loads(data, default=None):
    return json.loads(data) if data else default


def apply_keystone_ca(ctx):
    ks_ca_path = "/etc/contrail/ssl/keystone-ca-cert.pem"
    ks_ca = ctx.get("keystone_ssl_ca")
    save_file(ks_ca_path, ks_ca, 0o444)
    if ks_ca:
        ctx["keystone_ssl_ca_path"] = ks_ca_path


def update_certificates(cert, key, ca):
    # NOTE: store files in default paths cause no way to pass this path to
    # some of components (sandesh)
    files = {"/etc/contrail/ssl/certs/server.pem": cert,
             "/etc/contrail/ssl/private/server-privkey.pem": key,
             "/etc/contrail/ssl/certs/ca-cert.pem": ca}
    changed = False
    for cfile in files:
        data = files[cfile]
        old_hash = file_hash(cfile)
        save_file(cfile, data)
        changed |= (old_hash != file_hash(cfile))

    return changed


def render_and_log(template, conf_file, ctx, perms=0o444):
    """Returns True if configuration has been changed."""

    log("Render and store new configuration: " + conf_file)
    try:
        with open(conf_file) as f:
            old_lines = set(f.readlines())
    except Exception:
        old_lines = set()

    render(template, conf_file, ctx, perms)
    with open(conf_file) as f:
        new_lines = set(f.readlines())
    new_set = new_lines.difference(old_lines)
    old_set = old_lines.difference(new_lines)
    if new_set or old_set:
        log("New lines:\n{new}".format(new="".join(new_set)))
        log("Old lines:\n{old}".format(old="".join(old_set)))
        log("Configuration file has been changed.")
    else:
        log("Configuration file has not been changed.")
