import functools
import os
from socket import gethostname
from subprocess import (
    check_call,
    check_output,
)
from time import sleep, time
import yaml

import apt_pkg
import json

import netaddr
import netifaces

from charmhelpers.contrib.network.ip import get_address_in_network
from charmhelpers.core import sysctl
from charmhelpers.core.hookenv import (
    config,
    log,
    related_units,
    relation_get,
    relation_ids,
    status_set,
    WARNING,
)

from charmhelpers.core.host import (
    file_hash,
    restart_on_change,
    write_file,
    service_restart,
    init_is_systemd,
    get_total_ram,
    mkdir,
)

from charmhelpers.core.templating import render

apt_pkg.init()
config = config()


# as it's hardcoded in several scripts/configs
VROUTER_INTERFACE = "vhost0"


def configure_crashes():
    mkdir("/var/crashes", perms=0o755, force=True)
    options = {"kernel.core_pattern": "/var/crashes/core.%e.%p.%h.%t"}
    sysctl.create(yaml.dump(options), "/etc/sysctl.d/10-core-pattern.conf")


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


def _get_default_gateway_iface():
    if hasattr(netifaces, "gateways"):
        return netifaces.gateways()["default"][netifaces.AF_INET][1]

    data = check_output("ip route | grep ^default", shell=True).split()
    return data[data.index("dev") + 1]


def _get_iface_gateway_ip(iface):
    if hasattr(netifaces, "gateways"):
        data = netifaces.gateways()["default"][netifaces.AF_INET]
        return data[0] if data[1] == iface else None

    data = check_output("ip route | grep ^default", shell=True).split()
    return data[2] if data[4] == iface else None


def _vhost_cidr(iface):
    # return a vhost formatted address and mask - x.x.x.x/xx
    addr = netifaces.ifaddresses(iface)[netifaces.AF_INET][0]
    ip = addr["addr"]
    cidr = netaddr.IPNetwork(ip + "/" + addr["netmask"]).prefixlen
    return ip + "/" + str(cidr)


def get_control_network_ip(control_network=None):
    network = control_network
    if not network:
        network = config.get("control-network")
    ip = get_address_in_network(network) if network else None
    if not ip:
        ip = config["vhost-cidr"].split('/')[0]
    return ip


def configure_vrouter_interface():
    # run external script to configure vrouter
    args = ["./create-vrouter.sh"]
    if config.get("remove-juju-bridge"):
        args.append("-b")
    if config.get("dpdk"):
        args.append("-d")
    iface = config.get("physical-interface")
    if not iface:
        iface = _get_default_gateway_iface()
    config["vhost-physical"] = iface
    config["vhost-cidr"] = _vhost_cidr(iface)
    gateway_ip = config.get("vhost-gateway")
    if gateway_ip == "auto":
        gateway_ip = _get_iface_gateway_ip(iface)
    config["vhost-gateway-ip"] = gateway_ip

    if config["dpdk"]:
        fs = os.path.realpath("/sys/class/net/" + iface).split("/")
        # NOTE: why it's not an error?
        pci_address = fs[4] if fs[3].startswith("pci") else "0000:00:00.0"
        config["dpdk-pci"] = pci_address
        addr = netifaces.ifaddresses(iface)[netifaces.AF_PACKET][0]
        config["dpdk-mac"] = addr["addr"]

    args.append(iface)
    check_call(args, cwd="scripts")

    if config["dpdk"]:
        render("agent_param", "/etc/contrail/agent_param",
               {"interface": iface})


def drop_caches():
    """Clears OS pagecache"""
    log("Clearing pagecache")
    check_call(["sync"])
    with open("/proc/sys/vm/drop_caches", "w") as f:
        f.write("3\n")


def dkms_autoinstall():
    """
    'dkms_autoinstall' is useful for DKMS kernel modules. Juju often upgrades
    units to newer kernels before charm install, which won't be used until the
    machine is rebooted. In these cases, some modules may not be compiled for
    the newer kernel.
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
    use_ssl = "true" if config.get("ssl_enabled", False) else "false"
    params = [
        "contrail-provision-vrouter",
        "--host_name", gethostname(),
        "--host_ip", ip,
        "--api_server_ip", api_ip,
        "--api_server_port", str(api_port),
        "--oper", op,
        "--api_server_use_ssl", use_ssl]
    if "keystone_admin_user" in identity:
        params += [
            "--admin_user", identity.get("keystone_admin_user"),
            "--admin_password", identity.get("keystone_admin_password"),
            "--admin_tenant_name", identity.get("keystone_admin_tenant")]
    if config["dpdk"] and op == "add":
        params.append("--dpdk_enabled")

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


def _load_json_from_config(key):
    value = config.get(key)
    return json.loads(value) if value else {}


def get_context():
    ctx = {}
    ctx["ssl_enabled"] = config.get("ssl_enabled", False)

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

    ctx["vhost_ip"] = config["vhost-cidr"]
    ctx["vhost_gateway"] = config["vhost-gateway-ip"]
    ctx["vhost_physical"] = config["vhost-physical"]

    if config["dpdk"]:
        ctx["dpdk"] = True
        ctx["physical_interface_address"] = config["dpdk-pci"]
        ctx["physical_interface_mac"] = config["dpdk-mac"]
        ctx["physical_uio_driver"] = config.get("dpdk-driver")

    log("CTX: " + str(ctx))

    ctx.update(_load_json_from_config("auth_info"))
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
    "/etc/contrail/keystone/ssl/ca-cert.pem":
        ["contrail-vrouter-agent", "contrail-vrouter-nodemgr"],
    "/etc/contrail/contrail-vrouter-agent.conf":
        ["contrail-vrouter-agent"],
    "/etc/contrail/contrail-vrouter-nodemgr.conf":
        ["contrail-vrouter-nodemgr"]})
def write_configs():
    ctx = get_context()

    keystone_ssl_ca = ctx.get("keystone_ssl_ca")
    path = "/etc/contrail/keystone/ssl/ca-cert.pem"
    _save_file(path, keystone_ssl_ca)
    if keystone_ssl_ca:
        ctx["keystone_ssl_ca_path"] = path

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
            continue
        lst = line.decode('UTF-8').split()
        if len(lst) < 2:
            continue
        s_name = lst[0].strip()
        s_status = lst[1].strip()
        if 'contrail-vrouter-agent' not in s_name:
            continue

        log("contrail-status: " + line)
        return s_status, line

    return "waiting", None


def set_dpdk_coremask():
    mask = config.get("dpdk-coremask")
    service = "/usr/bin/contrail-vrouter-dpdk"
    mask_arg = mask if mask.startswith("0x") else "-c " + mask
    if not init_is_systemd():
        check_call(["sed", "-i", "-e",
            "s!^command=.*{service}!"
            "command=taskset {mask} {service}!".format(service=service,
                                                       mask=mask_arg),
            "/etc/contrail/supervisord_vrouter_files"
            "/contrail-vrouter-dpdk.ini"])
        return

    # systemd magic
    srv_orig = "/lib/systemd/system/contrail-vrouter-dpdk.service"
    with open(srv_orig, "r") as f:
        for line in f:
            if line.startswith("ExecStart="):
                args = line.split(service)[1]
                break
        else:
            args = " --no-daemon --socket-mem 1024"

    srv_dir = "/etc/systemd/system/contrail-vrouter-dpdk.service.d/"
    try:
        os.mkdir(srv_dir)
    except:
        pass
    with open(srv_dir + "/override.conf", "w") as f:
        f.write("[Service]\nExecStart=\n")
        f.write("ExecStart=/usr/bin/taskset {mask} {service} {args}"
                .format(service=service, mask=mask_arg, args=args))
    check_call(["systemctl", "daemon-reload"])


def configure_hugepages():
    if not config["dpdk"]:
        return

    pages = get_hugepages()
    if not pages:
        return
    map_max = pages * 2
    if map_max < 65536:
        map_max = 65536
    options = {"vm.nr_hugepages": pages,
               "vm.max_map_count": map_max,
               "vm.hugetlb_shm_group": 0}
    sysctl.create(yaml.dump(options), "/etc/sysctl.d/10-hugepage.conf")
    check_call(["sysctl", "-w", "vm.nr_hugepages={}".format(pages)])
    check_call(["sysctl", "-w", "vm.max_map_count={}".format(map_max)])
    check_call(["sysctl", "-w", "vm.hugetlb_shm_group=0".format(pages)])


def get_hugepages():
    pages = config.get("dpdk-hugepages")
    if not pages:
        return None
    if not pages.endswith("%"):
        return pages
    pp = int(pages.rstrip("%"))
    return int(get_total_ram() * pp / 100 / 1024 / 2048)


def fix_libvirt():
    # add apparmor exception for huge pages
    check_output(["sed", "-E", "-i", "-e",
       "\!^[[:space:]]*owner \"/run/hugepages/kvm/libvirt/qemu/\*\*\" rw"
       "!a\\\n  owner \"/hugepages/libvirt/qemu/**\" rw,",
       "/etc/apparmor.d/abstractions/libvirt-qemu"])
    service_restart("apparmor")


def tls_changed(cert, key, ca):
    files = {"/etc/contrail/ssl/certs/server.pem": cert,
             "/etc/contrail/ssl/private/server-privkey.pem": key,
             "/etc/contrail/ssl/certs/ca-cert.pem": ca}
    changed = False
    for cfile in files:
        data = files[cfile]
        old_hash = file_hash(cfile)
        _save_file(cfile, data)
        changed |= (old_hash != file_hash(cfile))

    if not changed:
        log("Certificates was not changed.")
        return

    log("Certificates was changed. Rewrite configs and rerun services.")
    config["ssl_enabled"] = (cert is not None and len(cert) > 0)
    config.save()
    write_configs()
    service_restart("contrail-vrouter-agent")
    service_restart("contrail-vrouter-nodemgr")
