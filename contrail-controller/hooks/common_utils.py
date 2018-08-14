from base64 import b64decode
import os
from socket import gethostbyname, gethostname, gaierror
from subprocess import (
    CalledProcessError,
    check_call,
    check_output
)
import netifaces
import json

from charmhelpers.contrib.network.ip import (
    get_address_in_network,
    get_iface_addr,
)
from charmhelpers.core.hookenv import (
    config,
    status_set,
    log,
    ERROR,
)
from charmhelpers.core.host import file_hash, write_file
import docker_utils


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


def update_services_status(name, services):
    try:
        output = docker_utils.docker_exec(name, "contrail-status")
    except CalledProcessError as e:
        log("Container is not ready to get contrail-status: " + str(e))
        status_set("waiting", "Waiting services to run in container")
        return

    statuses = dict()
    for line in output.splitlines()[1:]:
        if len(line) == 0 or line.startswith("=="):
            continue
        lst = line.split()
        if len(lst) < 2:
            continue
        srv = lst[0].split(":")[0]
        statuses[srv] = (lst[1], " ".join(lst[2:]))
    for srv in services:
        if srv not in statuses:
            status_set("waiting", srv + " is absent in the contrail-status")
            return
        status, desc = statuses.get(srv)
        if status != "active":
            workload = "waiting" if status == "initializing" else "blocked"
            status_set(workload, "{} is not ready. Reason: {}"
                       .format(srv, desc))
            return

    status_set("active", "Unit is ready")


def json_loads(data, default=None):
    return json.loads(data) if data else default


def apply_keystone_ca(ctx):
    ks_ca_path = "/etc/contrail/keystone-ca-cert.pem"
    ks_ca = ctx.get("keystone_ssl_ca")
    save_file(ks_ca_path, ks_ca, 0o444)
    if ks_ca:
        ctx["keystone_ssl_ca_path"] = ks_ca_path


def update_certificates(cert, key, ca):
    # NOTE: store files in default paths cause no way to pass this path to
    # some of components (sandesh)
    files = {"/etc/contrail/ssl/server.pem": cert,
             "/etc/contrail/ssl/server-privkey.pem": key,
             "/etc/contrail/ssl/ca-cert.pem": ca}
    changed = False
    for cfile in files:
        data = files[cfile]
        old_hash = file_hash(cfile)
        save_file(cfile, data)
        changed |= (old_hash != file_hash(cfile))

    return changed
