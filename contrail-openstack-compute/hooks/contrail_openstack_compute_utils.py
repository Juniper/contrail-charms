import functools
import os
import pwd
import shutil
from socket import gethostname
from subprocess import (
    CalledProcessError,
    check_call,
    check_output
)
from time import sleep, time

import apt_pkg
import json
import yaml

import netaddr
import netifaces

from charmhelpers.core.hookenv import (
    config,
    log,
    related_units,
    relation_get,
    relation_ids,
    status_set,
    application_version_set
)

from charmhelpers.core.host import service_restart, service_start

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
            if delay <= remaining:
                sleep(delay)
            else:
                sleep(remaining)
                raise error
    return func


def _dpkg_version(pkg):
    try:
        return check_output(
            ["dpkg-query", "-f", "${Version}\\n", "-W", pkg]).decode().rstrip()
    except CalledProcessError:
        return None


def set_status():
    version = _dpkg_version("contrail-vrouter-agent")
    application_version_set(version)
    output = check_output("contrail-status", shell=True)
    for line in output.splitlines()[1:]:
        if len(line) == 0:
            return
        lst = line.decode().split()
        if len(lst) < 2:
            continue
        s_name = lst[0].strip()
        s_status = lst[1].strip()
        if 'contrail-vrouter-agent' in s_name:
            if 'active' in s_status or 'initializing' in s_status:
                status_set("active", "Unit is ready")
            else:
                # TODO: rework this
                status_set("waiting", "vrouter-agent is not up")
            break


def configure_vrouter():
    # run external script to configure vrouter
    args = ["./create-vrouter.sh"]
    if config["remove-juju-bridge"]:
        args.append("-b")
    iface = config.get("vhost-interface")
    if iface:
        args.append(iface)
    check_call(args, cwd="scripts")


def enable_vrouter_vgw():
    if not os.path.exists("/etc/sysctl.d/60-vrouter-vgw.conf"):
        # set sysctl options
        shutil.copy("files/60-vrouter-vgw.conf", "/etc/sysctl.d")
        service_start("procps")


def disable_vrouter_vgw():
    if os.path.exists("/etc/sysctl.d/60-vrouter-vgw.conf"):
        # unset sysctl options
        os.remove("/etc/sysctl.d/60-vrouter-vgw.conf")
        check_call(["sysctl", "-qw", "net.ipv4.ip_forward=0"])


def drop_caches():
    """Clears OS pagecache"""
    log("Clearing pagecache")
    check_call(["sync"])
    with open("/proc/sys/vm/drop_caches", "w") as f:
        f.write("3\n")


def fix_nodemgr():
    # add files missing from contrail-nodemgr package
    etc_dir = "/etc/contrail"
    dest = etc_dir + "/supervisord_vrouter_files/contrail-vrouter-nodemgr.ini"
    shutil.copy("files/contrail-nodemgr-vrouter.ini", dest)
    pw = pwd.getpwnam("contrail")
    os.chown(dest, pw.pw_uid, pw.pw_gid)

    shutil.copy("files/contrail-vrouter.rules",
                etc_dir + "/supervisord_vrouter_files")
    os.chown(etc_dir + "/supervisord_vrouter_files/contrail-vrouter.rules",
             pw.pw_uid, pw.pw_gid)

    shutil.copy("files/contrail-vrouter-nodemgr",
                "/etc/init.d/contrail-vrouter-nodemgr")
    os.chmod("/etc/init.d/contrail-vrouter-nodemgr", 0o755)

    service_restart("supervisor-vrouter")


def ifdown(interfaces=None):
    """ifdown an interface or all interfaces"""
    log("Taking down {}".format(interfaces if interfaces else "interfaces"))
    check_call(["ifdown"] + interfaces if interfaces else ["-a"])


def ifup(interfaces=None):
    """ifup an interface or all interfaces"""
    log("Bringing up {}".format(interfaces if interfaces else "interfaces"))
    check_call(["ifup"] + interfaces if interfaces else ["-a"])


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
    if ip and port:
        return (ip, port)
    for rid in relation_ids("contrail-controller"):
        for unit in related_units(rid):
            port = relation_get("port", unit, rid)
            if not port:
                continue
            ip = relation_get("private-address", unit, rid)
            return (ip, port)
    return (None, None)


@retry(timeout=300)
def contrail_provision_linklocal(api_ip, api_port, service_name, service_ip,
                                 service_port, fabric_ip, fabric_port, op,
                                 user, password):
    check_call(["contrail-provision-linklocal",
                "--api_server_ip", api_ip,
                "--api_server_port", str(api_port),
                "--linklocal_service_name", service_name,
                "--linklocal_service_ip", service_ip,
                "--linklocal_service_port", str(service_port),
                "--ipfabric_service_ip", fabric_ip,
                "--ipfabric_service_port", str(fabric_port),
                "--oper", op,
                "--admin_user", user,
                "--admin_password", password])


def provision_local_metadata():
    api_ip, api_port = get_controller_address()
    identity = identity_admin_ctx()
    user = identity.get("keystone_admin_user")
    password = identity.get("keystone_admin_password")
    log("Provisioning local metadata service 127.0.0.1:8775")
    contrail_provision_linklocal(api_ip, api_port, "metadata",
                                 "169.254.169.254", 80, "127.0.0.1", 8775,
                                 "add", user, password)


def unprovision_local_metadata():
    api_ip, api_port = get_controller_address()
    identity = identity_admin_ctx()
    user = identity.get("keystone_admin_user")
    password = identity.get("keystone_admin_password")
    log("Unprovisioning local metadata service 127.0.0.1:8775")
    contrail_provision_linklocal(api_ip, api_port, "metadata",
                                 "169.254.169.254", 80, "127.0.0.1", 8775,
                                 "del", user, password)


@retry(timeout=300)
def contrail_provision_vrouter(hostname, ip, api_ip, api_port, op,
                               user, password, tenant):
    check_call(["contrail-provision-vrouter",
                "--host_name", hostname,
                "--host_ip", ip,
                "--api_server_ip", api_ip,
                "--api_server_port", str(api_port),
                "--oper", op,
                "--admin_user", user,
                "--admin_password", password,
                "--admin_tenant_name", tenant])


def provision_vrouter():
    hostname = gethostname()
    ip = netifaces.ifaddresses("vhost0")[netifaces.AF_INET][0]["addr"]
    api_ip, api_port = get_controller_address()
    identity = identity_admin_ctx()
    user = identity.get("keystone_admin_user")
    password = identity.get("keystone_admin_password")
    tenant = identity.get("keystone_admin_tenant")
    log("Provisioning vrouter {}".format(ip))
    contrail_provision_vrouter(hostname, ip, api_ip, api_port, "add",
                               user, password, tenant)


def unprovision_vrouter():
    hostname = gethostname()
    ip = netifaces.ifaddresses("vhost0")[netifaces.AF_INET][0]["addr"]
    api_ip, api_port = get_controller_address()
    identity = identity_admin_ctx()
    user = identity.get("keystone_admin_user")
    password = identity.get("keystone_admin_password")
    tenant = identity.get("keystone_admin_tenant")
    log("Unprovisioning vrouter {}".format(ip))
    contrail_provision_vrouter(hostname, ip, api_ip, api_port, "del",
                               user, password, tenant)


def vhost_gateway():
    # determine vhost gateway
    gateway = config.get("vhost-gateway")
    if gateway == "auto":
        for line in check_output(["route", "-n"]).splitlines()[2:]:
            l = line.decode().split()
            if "G" in l[3] and l[7] == "vhost0":
                return l[1]
        gateway = None
    return gateway


def vhost_ip(iface):
    # return a vhost formatted address and mask - x.x.x.x/xx
    addr = netifaces.ifaddresses(iface)[netifaces.AF_INET][0]
    ip = addr["addr"]
    cidr = netaddr.IPNetwork(ip + "/" + addr["netmask"]).prefixlen
    return ip + "/" + str(cidr)


def vhost_phys():
    # run external script to determine physical interface of vhost0
    return check_output(["scripts/vhost-phys.sh"]).rstrip()


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
    return (json.loads(auth_info) if auth_info else {})


def analytics_node_ctx():
    """Get the ipaddres of all contrail analytics nodes"""
    data = config.get("analytics-servers")
    return {"analytics_nodes": json.loads(data) if data else []}


def network_ctx():
    iface = config.get("control-interface")
    return {"control_network_ip":
            netifaces.ifaddresses(iface)[netifaces.AF_INET][0]["addr"]}


def neutron_metadata_ctx():
    if "local-metadata-secret" in config:
        return {"metadata_secret": config["local-metadata-secret"]}
    return {}


def vrouter_ctx():
    return {"vhost_ip": vhost_ip("vhost0"),
            "vhost_gateway": vhost_gateway(),
            "vhost_physical": vhost_phys().decode()}


def vrouter_vgw_ctx():
    ctx = {}
    vgws = config.get("virtual-gateways")
    if vgws:
        vgws = yaml.safe_load(vgws)
        map(lambda item: item.update(domain="default-domain"), vgws)
        ctx["vgws"] = vgws
    return ctx


def write_nodemgr_config():
    ctx = analytics_node_ctx()
    render("contrail-vrouter-nodemgr.conf",
           "/etc/contrail/contrail-vrouter-nodemgr.conf", ctx)


def write_vnc_api_config():
    ctx = {}
    ctx.update(contrail_api_ctx())
    ctx.update(identity_admin_ctx())
    render("vnc_api_lib.ini", "/etc/contrail/vnc_api_lib.ini", ctx)


def write_vrouter_config():
    ctx = {}
    ctx.update(control_node_ctx())
    ctx.update(analytics_node_ctx())
    ctx.update(neutron_metadata_ctx())
    ctx.update(network_ctx())
    ctx.update(vrouter_ctx())
    ctx.update(vrouter_vgw_ctx())
    render("contrail-vrouter-agent.conf",
           "/etc/contrail/contrail-vrouter-agent.conf", ctx, perms=0o440)


def write_vrouter_vgw_interfaces():
    ctx = vrouter_vgw_ctx()
    render("vrouter-vgw.cfg", "/etc/network/interfaces.d/vrouter-vgw.cfg", ctx)
