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
    lsb_release,
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
    for line in check_output(["route", "-n"]).splitlines()[2:]:
        l = line.split()
        if "G" in l[3] and l[7] == iface:
            log("Found gateway {} for interface {}".format(l[1], iface))
            return l[1]
    log("vrouter-gateway set to 'auto' but gateway could not be determined "
        "from routing table for interface {}".format(iface), level=WARNING)
    return None


def _vhost_cidr(iface):
    # return a vhost formatted address and mask - x.x.x.x/xx
    addr = netifaces.ifaddresses(iface)[netifaces.AF_INET][0]
    ip = addr["addr"]
    cidr = netaddr.IPNetwork(ip + "/" + addr["netmask"]).prefixlen
    return ip + "/" + str(cidr)


def get_control_network_ip():
    return config["vhost-cidr"].split('/')[0]


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

    if config.get("vhost-mtu"):
        args.append("-m")
        args.append(config["vhost-mtu"])

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
        and config.get("api_ip")
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


def provision_vrouter(op, self_ip=None):
    ip = self_ip if self_ip else get_control_network_ip()
    api_ips = get_controller_addresses()
    api_port = config.get("api_port")
    identity = _load_json_from_config("auth_info")
    params = [
        "contrail-provision-vrouter",
        "--host_name", gethostname(),
        "--host_ip", ip,
        "--api_server_port", str(api_port),
        "--oper", op,
        "--api_server_use_ssl", "false"]
    # api_server_use_ssl is needed only if contrail-api behind haproxy with
    # ssl termination
    if "keystone_admin_user" in identity:
        params += [
            "--admin_user", identity.get("keystone_admin_user"),
            "--admin_password", identity.get("keystone_admin_password"),
            "--admin_tenant_name", identity.get("keystone_admin_tenant")]
    if config["dpdk"] and op == "add":
        params.append("--dpdk_enabled")
    # add API IP at the end to be able to substitute it for each server
    params += ["--api_server_ip", ""]

    @retry(timeout=65, delay=20)
    def _call():
        for api_ip in api_ips:
            params[-1] = api_ip
            check_call(params)
            log("vrouter operation '{}' was successful at API={}"
                .format(op, api_ip))
            break

    log("{} vrouter {}. API-IPs {}".format(op, ip, api_ips))
    _call()


def get_controller_addresses():
    return [relation_get("private-address", unit, rid)
            for rid in relation_ids("contrail-controller")
            for unit in related_units(rid)]


def _load_json_from_config(key):
    value = config.get(key)
    return json.loads(value) if value else {}


def get_context():
    ctx = {}
    ctx["ssl_enabled"] = config.get("ssl_enabled", False)
    ctx["log_level"] = config.get("log-level", "SYS_NOTICE")

    ips = get_controller_addresses()
    ctx["api_servers"] = ips
    ctx["api_port"] = config.get("api_port")
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
                params = ["curl", "-s"]
                proto = "http"
                ssl_enabled = config.get("ssl_enabled", False)
                if ssl_enabled:
                    params.extend([
                        "--cacert", "/etc/contrail/ssl/certs/ca-cert.pem",
                        "--cert", "/etc/contrail/ssl/certs/server.pem",
                        "--key", "/etc/contrail/ssl/private/server-privkey.pem"
                    ])
                    proto = "https"
                url = ("{proto}://{ip}:8083/Snh_ConfigClientReinitReq?"
                       .format(proto=proto, ip=ip))
                params.append(url)
                check_call(params)
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
    try:
        output = check_output("contrail-status", shell=True)
    except:
        return "waiting", None

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


def _get_args_from_command_string(original_args):
    args_other = ''
    command_args_dict = {}
    args_list = original_args.split(' ')
    iter_args = iter(enumerate(args_list))
    # divide dpdk arguments and other
    for index, arg in iter_args:
        if arg in ["--vr_mempool_sz", "--dpdk_txd_sz", "--dpdk_rxd_sz"]:
            command_args_dict[arg] = args_list[index+1]
            next(iter_args)
        else:
            args_other += ' ' + arg
    return command_args_dict, args_other


def _dpdk_args_from_config_to_dict():
    config_args_dict = {}
    dpdk_main_mempool_size = config.get("dpdk-main-mempool-size")
    if dpdk_main_mempool_size:
        config_args_dict["--vr_mempool_sz"] = dpdk_main_mempool_size
    dpdk_pmd_txd_size = config.get("dpdk-pmd-txd-size")
    if dpdk_pmd_txd_size:
        config_args_dict["--dpdk_txd_sz"] = dpdk_pmd_txd_size
    dpdk_pmd_rxd_size = config.get("dpdk-pmd-rxd-size")
    if dpdk_pmd_rxd_size:
        config_args_dict["--dpdk_rxd_sz"] = dpdk_pmd_rxd_size
    return config_args_dict


def set_dpdk_options():
    mask = config.get("dpdk-coremask")
    service = "/usr/bin/contrail-vrouter-dpdk"
    mask_arg = mask if mask.startswith("0x") else "-c " + mask
    if not init_is_systemd():
        srv = "/etc/contrail/supervisord_vrouter_files/contrail-vrouter-dpdk.ini"
        with open(srv, "r") as f:
            data = f.readlines()
        for index, line in enumerate(data):
            if not (line.startswith("command=") and service in line):
                continue
            original_args = line.split(service)[1].rstrip()
            command_args_dict, other_args = _get_args_from_command_string(original_args)
            config_args_dict = _dpdk_args_from_config_to_dict()
            command_args_dict.update(config_args_dict)
            dpdk_args_string = " ".join(" ".join(_) for _ in command_args_dict.items())
            args = dpdk_args_string + other_args
            newline = 'command=taskset ' + mask_arg + ' ' + service + ' ' + args + '\n'
            data[index] = newline

        with open(srv, "w") as f:
            f.writelines(data)
        service_restart("contrail-vrouter-dpdk")
        return

    # systemd magic
    srv_orig = "/lib/systemd/system/contrail-vrouter-dpdk.service"
    with open(srv_orig, "r") as f:
        data = f.readlines()
    for line in data:
        if not line.startswith("ExecStart="):
            continue
        original_args = line.split(service)[1].rstrip()
        dpdk_args_dict, other_args = _get_args_from_command_string(original_args)
        config_args_dict = _dpdk_args_from_config_to_dict()
        dpdk_args_dict.update(config_args_dict)
        break
    else:
        dpdk_args_dict = _dpdk_args_from_config_to_dict()
        other_args = " --no-daemon --socket-mem 1024"
    dpdk_args_string = " ".join(" ".join(_) for _ in dpdk_args_dict.items())
    args = dpdk_args_string + other_args

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
    service_restart("contrail-vrouter-dpdk")


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
    # do some fixes for libvirt with DPDK
    # it's not required for non-DPDK deployments

    # add apparmor exception for huge pages
    check_output(["sed", "-E", "-i", "-e",
       "\!^[[:space:]]*owner \"/run/hugepages/kvm/libvirt/qemu/\*\*\" rw"
       "!a\\\n  owner \"/hugepages/libvirt/qemu/**\" rw,",
       "/etc/apparmor.d/abstractions/libvirt-qemu"])

    if lsb_release()['DISTRIB_CODENAME'] == 'xenial':
        # fix libvirt tempate for xenial
        render("TEMPLATE.qemu", "/etc/apparmor.d/libvirt/TEMPLATE.qemu", dict())

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
