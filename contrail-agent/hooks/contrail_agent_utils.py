from base64 import b64decode
import functools
import os
from socket import gethostname
from subprocess import (
    check_call,
    check_output,
)
from time import sleep, time

import apt_pkg
import json

import netaddr
import netifaces

from charmhelpers.contrib.network.ip import get_address_in_network
from charmhelpers.core.hookenv import (
    config,
    log,
    related_units,
    relation_get,
    relation_ids,
    status_set,
    ERROR,
    WARNING,
)

from charmhelpers.core.host import (
    restart_on_change,
    write_file,
    service_restart,
)

from charmhelpers.core.templating import render

apt_pkg.init()
config = config()


# as it's hardcoded in several scripts/configs
VROUTER_INTERFACE = "vhost0"


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


def configure_vrouter_interface():
    # run external script to configure vrouter
    args = ["./create-vrouter.sh"]
    if config["remove-juju-bridge"]:
        args.append("-b")
    iface = config.get("physical-interface")
    if iface:
        args.append(iface)
    check_call(args, cwd="scripts")


def drop_caches():
    """Clears OS pagecache"""
    log("Clearing pagecache")
    check_call(["sync"])
    with open("/proc/sys/vm/drop_caches", "w") as f:
        f.write("3\n")


def dkms_autoinstall(module):
    """Allows loading of a kernel module.

    'dkms_autoinstall' is useful for DKMS kernel modules. Juju often upgrades
    units to newer kernels before charm install, which won't be used until the
    machine is rebooted. In these cases, some modules may not be compiled for
    the newer kernel. Setting this argument to True will ensure these modules
    are compiled for newer kernels.

    :param module: module to load
    """
    current = check_output(["uname", "-r"]).rstrip()
    for kernel in os.listdir("/lib/modules"):
        if kernel == current:
            continue
        log("DKMS auto installing for kernel {}".format(kernel))
        check_call(["dkms", "autoinstall", "-k", kernel])


def update_vrouter_provision_status():
    # TODO: update this logic with various scenario for data in relation
    info = _load_json_from_config("orchestrator_info")
    ready = (
        config.get("api_port")
        and (config.get("api_ip") or config.get("api_vip"))
        and config.get("analytics_servers")
        and info.get("cloud_orchestrator"))
    if config.get("vrouter-expected-provision-state"):
        if ready and not config.get("vrouter-provisioned"):
            try:
                provision_vrouter("add")
                config["vrouter-provisioned"] = True
            except Exception as e:
                # vrouter is not up yet
                log("Couldn't provision vrouter: " + str(e), level=WARNING)
    elif config.get("vrouter-provisioned"):
        try:
            provision_vrouter("del")
        except Exception as e:
            log("Couldn't unprovision vrouter: " + str(e), level=WARNING)
        config["vrouter-provisioned"] = False


def get_control_network_ip(control_network=None):
    network = control_network
    if not network:
        network = config.get("control-network")
    ip = get_address_in_network(network) if network else None
    if not ip:
        ip = iface_addr(VROUTER_INTERFACE)["addr"]
    return ip


def reprovision_vrouter(old_ip):
    if not config.get("vrouter-provisioned"):
        return

    old_ip = get_control_network_ip(config.prev("control-network"))
    try:
        provision_vrouter("del", old_ip)
    except Exception as e:
        log("Couldn't unprovision vrouter: " + str(e), level=WARNING)
    try:
        provision_vrouter("add")
    except Exception as e:
        # vrouter is not up yet
        log("Couldn't provision vrouter: " + str(e), level=WARNING)


def provision_vrouter(op, self_ip=None):
    ip = self_ip if self_ip else get_control_network_ip()
    api_ip, api_port = get_controller_address()
    identity = _load_json_from_config("auth_info")
    params = [
        "contrail-provision-vrouter",
        "--host_name", gethostname(),
        "--host_ip", ip,
        "--api_server_ip", api_ip,
        "--api_server_port", str(api_port),
        "--oper", op]
    if "keystone_admin_user" in identity:
        params += [
            "--admin_user", identity.get("keystone_admin_user"),
            "--admin_password", identity.get("keystone_admin_password"),
            "--admin_tenant_name", identity.get("keystone_admin_tenant")]

    @retry(timeout=65, delay=20)
    def _call():
        check_call(params)
        log("vrouter operation '{}' was successful".format(op))

    log("{} vrouter {}".format(op, ip))
    _call()


def get_controller_address():
    ip = config.get("api_ip")
    port = config.get("api_port")
    api_vip = config.get("api_vip")
    if api_vip:
        ip = api_vip
    return (ip, port) if ip and port else (None, None)


def iface_addr(iface):
    return netifaces.ifaddresses(iface)[netifaces.AF_INET][0]


def vhost_ip(addr):
    # return a vhost formatted address and mask - x.x.x.x/xx
    addr = iface_addr(VROUTER_INTERFACE)
    ip = addr["addr"]
    cidr = netaddr.IPNetwork(ip + "/" + addr["netmask"]).prefixlen
    return ip + "/" + str(cidr)


def vhost_gateway(iface):
    # determine vhost gateway
    gateway = config.get("vhost-gateway")
    if gateway == "auto":
        for line in check_output(["route", "-n"]).splitlines()[2:]:
            l = line.decode('UTF-8').split()
            if "G" in l[3] and l[7] == iface:
                return l[1]
        gateway = None
    return gateway


def vhost_phys(iface):
    # run external script to determine physical interface of 'vhost0'
    cmd = ["scripts/vhost-phys.sh", iface]
    return (check_output(cmd).decode('UTF-8').rstrip())


def _load_json_from_config(key):
    value = config.get(key)
    return json.loads(value) if value else {}


def get_context():
    ctx = {}
    ssl_ca = _decode_cert("ssl_ca")
    ctx["ssl_ca"] = ssl_ca
    ctx["ssl_enabled"] = (ssl_ca is not None and len(ssl_ca) > 0)

    ip, port = get_controller_address()
    ctx["api_server"] = ip
    ctx["api_port"] = port
    ctx["control_nodes"] = [
        relation_get("private-address", unit, rid)
         for rid in relation_ids("contrail-controller")
         for unit in related_units(rid)]
    ctx["analytics_nodes"] = _load_json_from_config("analytics_servers")
    info = _load_json_from_config("orchestrator_info")
    ctx["metadata_shared_secret"] = info.get("metadata_shared_secret")

    ctx["control_network_ip"] = get_control_network_ip()

    ctx["vhost_ip"] = vhost_ip(VROUTER_INTERFACE)
    ctx["vhost_gateway"] = vhost_gateway(VROUTER_INTERFACE)
    ctx["vhost_physical"] = vhost_phys(VROUTER_INTERFACE)

    log("CTX: " + str(ctx))

    ctx.update(_load_json_from_config("auth_info"))
    return ctx


def _decode_cert(key):
    val = config.get(key)
    if not val:
        return None
    try:
        return b64decode(val)
    except Exception as e:
        log("Couldn't decode certificate from config['{}']: {}".format(
            key, str(e)), level=ERROR)
    return None


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
    "/etc/contrail/contrail-vrouter-agent.conf":
        ["contrail-vrouter-agent"],
    "/etc/contrail/contrail-vrouter-nodemgr.conf":
        ["contrail-vrouter-nodemgr"]})
def write_configs():
    ctx = get_context()

    # TODO: what we should do with two other certificates?
    # NOTE: store files in the same paths as in tepmlates
    ca_path = "/etc/contrail/ssl/certs/ca-cert.pem"
    ssl_ca = ctx["ssl_ca"]
    _save_file(ca_path, ssl_ca)
    ctx["ssl_ca_path"] = ca_path

    render("contrail-vrouter-nodemgr.conf",
           "/etc/contrail/contrail-vrouter-nodemgr.conf", ctx)
    render("vnc_api_lib.ini", "/etc/contrail/vnc_api_lib.ini", ctx)
    render("contrail-vrouter-agent.conf",
           "/etc/contrail/contrail-vrouter-agent.conf", ctx, perms=0o440)


def update_unit_status():
    if not config.get("vrouter-provisioned"):
        units = [unit for rid in relation_ids("contrail-controller")
                          for unit in related_units(rid)]
        if units:
            status_set("waiting", "There is no enough info to provision.")
        else:
            status_set("blocked", "Missing relation to contrail-controller")

    status, _ = _get_agent_status()
    if status == 'initializing':
        # some hacks
        log("Run agent hack: service restart")
        service_restart("contrail-vrouter-agent")
        sleep(10)
        status, msg = _get_agent_status()
        if status == 'initializing' and "(No Configuration for self)" in msg:
            log("Run agent hack: reinitialize config client")
            ip = config.get("api_ip")
            try:
                # TODO: apply SSL if needed
                check_call(
                    ["curl", "-s",
                     "http://{}:8083/Snh_ConfigClientReinitReq?".format(ip)])
                sleep(5)
                status, _ = _get_agent_status()
            except Exception as e:
                log("Reinitialize returns error: " + str(e))

    if status == 'active':
        status_set("active", "Unit is ready")
        return

    status_set("waiting", "vrouter-agent is not up")


def _get_agent_status():
    """ Analyzes output of 'contrail-status' utility

    returns status from agent service:
    """
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
        return s_status, line
