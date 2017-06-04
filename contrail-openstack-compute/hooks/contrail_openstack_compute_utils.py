from base64 import b64decode
import functools
import os
from socket import gethostname, gethostbyname
from subprocess import (
    CalledProcessError,
    check_call,
    check_output
)
from time import sleep, time

import apt_pkg
import json
from six.moves.urllib.parse import urlparse

import requests
import netaddr
import netifaces

from charmhelpers.core.hookenv import (
    config,
    log,
    related_units,
    relation_get,
    relation_ids,
    status_set,
    application_version_set,
    leader_get,
    log,
    ERROR,
)

from charmhelpers.core.host import (
    restart_on_change,
    service_restart,
    write_file,
    lsb_release,
)

from charmhelpers.core.templating import render

apt_pkg.init()
config = config()


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


def _dpkg_version(pkg):
    try:
        output = check_output(["dpkg-query", "-f", "${Version}\\n", "-W", pkg])
        return output.decode('UTF-8').rstrip()
    except CalledProcessError:
        return None


def set_status():
    """ Analyzis status 'contrail-status' utility

    returns:
    0 - active
    1 - initializing
    2 - other
    """
    version = _dpkg_version("contrail-vrouter-agent")
    application_version_set(version)
    output = check_output("contrail-status", shell=True)
    for line in output.splitlines()[1:]:
        if len(line) == 0:
            return
        lst = line.decode('UTF-8').split()
        if len(lst) < 2:
            continue
        s_name = lst[0].strip()
        s_status = lst[1].strip()
        if 'contrail-vrouter-agent' not in s_name:
            continue

        log("contrail-status: " + line)
        if s_status == 'active':
            status_set("active", "Unit is ready")
            return 0
        else:
            # TODO: rework this
            status_set("waiting", "vrouter-agent is not up")
            return 1 if s_status == "initializing" else 2


def configure_vrouter():
    # run external script to configure vrouter
    args = ["./create-vrouter.sh"]
    if config["remove-juju-bridge"]:
        args.append("-b")
    iface = config.get("vhost-interface")
    if iface:
        args.append(iface)
    check_call(args, cwd="scripts")


def drop_caches():
    """Clears OS pagecache"""
    log("Clearing pagecache")
    check_call(["sync"])
    with open("/proc/sys/vm/drop_caches", "w") as f:
        f.write("3\n")


def vrouter_restart():
    release = lsb_release()["DISTRIB_CODENAME"]
    if release == 'trusty':
        # supervisord
        service_restart("supervisor-vrouter")
    elif release == 'xenial':
        # systemd
        service_restart("contrail-vrouter-agent")


def lsmod(module):
    """Check if a kernel module is loaded"""
    with open("/proc/modules", "r") as modules:
        for line in modules:
            if line.split()[0] == module:
                return True
    return False


def modprobe(module, auto_load=False, dkms_autoinstall=False):
    """Load a kernel module.

    Allows loading of a kernel module.

    'dkms_autoinstall' is useful for DKMS kernel modules. Juju often upgrades
    units to newer kernels before charm install, which won't be used until the
    machine is rebooted. In these cases, some modules may not be compiled for
    the newer kernel. Setting this argument to True will ensure these modules
    are compiled for newer kernels.

    :param module: module to load
    :param auto_load: load module on boot (default False)
    :param dkms_autoinstall: invoke DKMS autoinstall for other kernels
                             (default False)
    """
    if not lsmod(module):
        log("Loading kernel module {}".format(module))
        check_call(["modprobe", module])
    if auto_load:
        with open("/etc/modules", "a") as modules:
            modules.write(module)
            modules.write("\n")
    if dkms_autoinstall:
        current = check_output(["uname", "-r"]).rstrip()
        for kernel in os.listdir("/lib/modules"):
            if kernel == current:
                continue
            log("DKMS auto installing for kernel {}".format(kernel))
            check_call(["dkms", "autoinstall", "-k", kernel])


def get_controller_address():
    ip = config.get("api_ip")
    port = config.get("api_port")
    api_vip = config.get("api_vip")
    if api_vip:
        ip = api_vip
    return (ip, port) if ip and port else (None, None)


def provision_vrouter(op):
    iface = config.get("control-interface")
    ip = vhost_addr(iface)["addr"]
    api_ip, api_port = get_controller_address()
    identity = identity_admin_ctx()
    params = [
        "contrail-provision-vrouter",
        "--host_name", gethostname(),
        "--host_ip", ip,
        "--api_server_ip", api_ip,
        "--api_server_port", str(api_port),
        "--oper", op,
        "--admin_user", identity.get("keystone_admin_user"),
        "--admin_password", identity.get("keystone_admin_password"),
        "--admin_tenant_name", identity.get("keystone_admin_tenant")]

    @retry(timeout=120, delay=20)
    def _call():
        check_call(params)

    log("{} vrouter {}".format(op, ip))
    _call()


def vhost_gateway():
    # determine vhost gateway
    iface = config.get("control-interface")
    gateway = config.get("vhost-gateway")
    if gateway == "auto":
        for line in check_output(["route", "-n"]).splitlines()[2:]:
            l = line.decode('UTF-8').split()
            if "G" in l[3] and l[7] == iface:
                return l[1]
        gateway = None
    return gateway


def vhost_addr(iface):
    return netifaces.ifaddresses(iface)[netifaces.AF_INET][0]


def vhost_ip(iface):
    # return a vhost formatted address and mask - x.x.x.x/xx
    addr = vhost_addr(iface)
    ip = addr["addr"]
    cidr = netaddr.IPNetwork(ip + "/" + addr["netmask"]).prefixlen
    return ip + "/" + str(cidr)


def vhost_phys():
    # run external script to determine physical interface of 'vhost0'
    iface = config.get("control-interface")
    return (check_output(["scripts/vhost-phys.sh", iface])
                .decode('UTF-8')
                .rstrip())


def contrail_api_ctx():
    ip, port = get_controller_address()
    return ({"api_server": ip, "api_port": port} if ip and port else {})


def control_node_ctx():
    return {"control_nodes":
        [relation_get("private-address", unit, rid)
         for rid in relation_ids("contrail-controller")
         for unit in related_units(rid)]}


def identity_admin_ctx():
    auth_info = config.get("auth_info")
    return json.loads(auth_info) if auth_info else {}


def analytics_node_ctx():
    """Get the ipaddres of all contrail analytics nodes"""
    data = config.get("analytics-servers")
    return {"analytics_nodes": json.loads(data) if data else []}


def network_ctx():
    iface = config.get("control-interface")
    return {"control_network_ip": vhost_addr(iface)["addr"]}


def neutron_metadata_ctx():
    return {"metadata_shared_secret": leader_get("metadata_shared_secret")}


def vrouter_ctx():
    iface = config.get("control-interface")
    return {"vhost_ip": vhost_ip(iface),
            "vhost_gateway": vhost_gateway(),
            "vhost_physical": vhost_phys()}


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


def get_context():
    ctx = {}
    ssl_ca = decode_cert("ssl_ca")
    ctx["ssl_ca"] = ssl_ca
    ctx["ssl_enabled"] = (ssl_ca is not None and len(ssl_ca) > 0)
    ctx.update(contrail_api_ctx())
    ctx.update(control_node_ctx())
    ctx.update(analytics_node_ctx())
    ctx.update(neutron_metadata_ctx())
    ctx.update(network_ctx())
    ctx.update(vrouter_ctx())
    log("CTX: " + str(ctx))

    ctx.update(identity_admin_ctx())
    return ctx


def _save_file(path, data):
    if data:
        fdir = os.path.dirname(path)
        if not os.path.exists(fdir):
            os.makedirs(fdir)
        write_file(path, data, perms=0o400)
    elif os.path.exists(path):
        os.remove(path)


@restart_on_change({
    "/etc/contrail/ssl/certs/ca-cert.pem":
        ["contrail-vrouter-agent", "contrail-vrouter-nodemgr"],
    "/etc/contrail/ssl/certs/server.pem":
        ["contrail-vrouter-agent", "contrail-vrouter-nodemgr"],
    "/etc/contrail/ssl/private/server-privkey.pem":
        ["contrail-vrouter-agent", "contrail-vrouter-nodemgr"],
    "/etc/contrail/contrail-vrouter-agent.conf":
        ["contrail-vrouter-agent"],
    "/etc/contrail/contrail-vrouter-nodemgr.conf":
        ["contrail-vrouter-nodemgr"]})
def write_configs():
    ctx = get_context()

    # NOTE: store files in the same paths as in tepmlates
    ssl_ca = ctx["ssl_ca"]
    _save_file("/etc/contrail/ssl/certs/ca-cert.pem", ssl_ca)

    render("contrail-vrouter-nodemgr.conf",
           "/etc/contrail/contrail-vrouter-nodemgr.conf", ctx)
    render("vnc_api_lib.ini", "/etc/contrail/vnc_api_lib.ini", ctx)
    render("contrail-vrouter-agent.conf",
           "/etc/contrail/contrail-vrouter-agent.conf", ctx, perms=0o440)


def get_endpoints():
    auth_info = identity_admin_ctx()
    api_ver = int(auth_info["keystone_api_version"])
    if api_ver == 2:
        req_data = {
            "auth": {
                "tenantName": auth_info["keystone_admin_tenant"],
                "passwordCredentials": {
                    "username": auth_info["keystone_admin_user"],
                    "password": auth_info["keystone_admin_password"]}}}
    else:
        req_data = {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "name": auth_info["keystone_admin_user"],
                            "domain": {"id": "default"},
                            "password": auth_info["keystone_admin_password"]
                        }
                    }
                }
            }
        }

    url = "{proto}://{ip}:{port}/{tokens}".format(
        proto=auth_info["keystone_protocol"],
        ip=auth_info["keystone_ip"],
        port=auth_info["keystone_public_port"],
        tokens=auth_info["keystone_api_tokens"])
    r = requests.post(url, headers={'Content-type': 'application/json'},
                      data=json.dumps(req_data), verify=False)
    content = json.loads(r.content)
    result = dict()
    catalog = (content["access"]["serviceCatalog"] if api_ver == 2 else
               content["token"]["catalog"])
    for service in catalog:
        if api_ver == 2:
            # NOTE: 0 means first region. do we need to search for region?
            url = service["endpoints"][0]["publicURL"]
        else:
            for endpoint in service["endpoints"]:
                if endpoint["interface"] == "public":
                    url = endpoint["url"]
                    break
        host = gethostbyname(urlparse(url).hostname)
        result[service["type"] + "_service_ip"] = host
    return result
