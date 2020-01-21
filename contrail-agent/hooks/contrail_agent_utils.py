import os
import socket
import struct
from subprocess import (
    check_call,
    check_output,
)
import netifaces
from charmhelpers.core.hookenv import (
    config,
    log,
    related_units,
    relation_get,
    relation_ids,
    status_set,
    unit_get,
    WARNING,
)

from charmhelpers.core.host import (
    file_hash,
    service_restart,
    get_total_ram,
    lsb_release,
)

from charmhelpers.core.templating import render
import common_utils
import docker_utils


MODULE = "agent"
BASE_CONFIGS_PATH = "/etc/contrail"

CONFIGS_PATH = BASE_CONFIGS_PATH + "/vrouter"
IMAGES = [
    "contrail-node-init",
    "contrail-nodemgr",
    "contrail-vrouter-agent",
]
IMAGES_KERNEL = [
    "contrail-vrouter-kernel-build-init",
]
IMAGES_DPDK = [
    "contrail-vrouter-kernel-init-dpdk",
    "contrail-vrouter-agent-dpdk",
]
SERVICES = {
    "vrouter": [
        "agent",
        "nodemgr",
    ]
}

DPDK_ARGS = {
    "dpdk-main-mempool-size": "--vr_mempool_sz",
    "dpdk-pmd-txd-size": "--dpdk_txd_sz",
    "dpdk-pmd-rxd-size": "--dpdk_rxd_sz"
}

config = config()


def _get_dpdk_args():
    result = []
    for arg in DPDK_ARGS:
        val = config.get(arg)
        if val:
            result.append("{} {}".format(DPDK_ARGS[arg], val))
    return " ".join(result)


def _get_hugepages():
    pages = config.get("dpdk-hugepages")
    if not pages:
        return None
    if not pages.endswith("%"):
        return pages
    pp = int(pages.rstrip("%"))
    return int(get_total_ram() * pp / 100 / 1024 / 2048)


def _get_default_gateway_iface():
    # TODO: get iface from route to CONTROL_NODES
    if hasattr(netifaces, "gateways"):
        return netifaces.gateways()["default"][netifaces.AF_INET][1]

    data = check_output("ip route | grep ^default", shell=True).decode('UTF-8').split()
    return data[data.index("dev") + 1]


def _get_iface_gateway_ip(iface):
    ifaces = [iface, "vhost0"]
    for line in check_output(["route", "-n"]).decode('UTF-8').splitlines()[2:]:
        l = line.split()
        if "G" in l[3] and l[7] in ifaces:
            log("Found gateway {} for interface {}".format(l[1], iface))
            return l[1]
    log("vrouter-gateway set to 'auto' but gateway could not be determined "
        "from routing table for interface {}".format(iface), level=WARNING)
    return None


def get_context():
    ctx = {}
    ctx["module"] = MODULE
    ctx["ssl_enabled"] = config.get("ssl_enabled", False)
    ctx["log_level"] = config.get("log-level", "SYS_NOTICE")
    ctx["container_registry"] = config.get("docker-registry")
    ctx["contrail_version_tag"] = config.get("image-tag")
    ctx["sriov_physical_interface"] = config.get("sriov-physical-interface")
    ctx["sriov_numvfs"] = config.get("sriov-numvfs")

    iface = config.get("physical-interface")
    ctx["physical_interface"] = iface
    gateway_ip = config.get("vhost-gateway")
    if gateway_ip == "auto":
         gateway_ip = _get_iface_gateway_ip(iface)
    ctx["vrouter_gateway"] = gateway_ip if gateway_ip else ''

    ctx["agent_mode"] = "dpdk" if config["dpdk"] else "kernel"
    if config["dpdk"]:
        ctx["dpdk_additional_args"] = _get_dpdk_args()
        ctx["dpdk_driver"] = config.get("dpdk-driver")
        ctx["dpdk_coremask"] = config.get("dpdk-coremask")
        ctx["dpdk_hugepages"] = _get_hugepages()

    info = common_utils.json_loads(config.get("orchestrator_info"), dict())
    ctx.update(info)

    ips = list()
    data_ips = list()
    for rid in relation_ids("contrail-controller"):
        for unit in related_units(rid):
            ip = relation_get("private-address", unit, rid)
            if ip:
                ips.append(ip)
            data_ip = relation_get("data-address", unit, rid)
            if data_ip or ip:
                data_ips.append(data_ip if data_ip else ip)
    ctx["controller_servers"] = ips
    ctx["control_servers"] = data_ips
    ips = common_utils.json_loads(config.get("analytics_servers"), list())
    ctx["analytics_servers"] = ips

    if "plugin-ips" in config:
        plugin_ips = common_utils.json_loads(config["plugin-ips"], dict())
        my_ip = unit_get("private-address")
        if my_ip in plugin_ips:
            ctx["plugin_settings"] = plugin_ips[my_ip]
    ctx["hostname"] = socket.getfqdn()

    ctx["config_analytics_ssl_available"] = config.get("config_analytics_ssl_available", False)
    ctx["logging"] = docker_utils.render_logging()
    log("CTX: " + str(ctx))

    ctx.update(common_utils.json_loads(config.get("auth_info"), dict()))
    return ctx


def update_charm_status():
    fix_dns_settings()

    tag = config.get('image-tag')
    for image in IMAGES + (IMAGES_DPDK if config["dpdk"] else IMAGES_KERNEL):
        try:
            docker_utils.pull(image, tag)
        except Exception as e:
            log("Can't load image {}".format(e))
            status_set('blocked',
                       'Image could not be pulled: {}:{}'.format(image, tag))
            return

    ctx = get_context()
    missing_relations = []
    if not ctx.get("controller_servers"):
        missing_relations.append("contrail-controller")
    if config.get("wait-for-external-plugin", False) and "plugin_settings" not in ctx:
        missing_relations.append("vrouter-plugin")
    if missing_relations:
        status_set('blocked',
                   'Missing relations: ' + ', '.join(missing_relations))
        return
    if not ctx.get("analytics_servers"):
        status_set('blocked',
                   'Missing analytics_servers info in relation '
                   'with contrail-controller.')
        return
    if not ctx.get("cloud_orchestrator"):
        status_set('blocked',
                   'Missing cloud_orchestrator info in relation '
                   'with contrail-controller.')
        return
    if ctx.get("cloud_orchestrator") == "openstack" and not ctx.get("keystone_ip"):
        status_set('blocked',
                   'Missing auth info in relation with contrail-controller.')
        return
    if ctx.get("cloud_orchestrator") == "kubernetes" and not ctx.get("kube_manager_token"):
        status_set('blocked',
                   'Kube manager token undefined.')
        return
    if ctx.get("cloud_orchestrator") == "kubernetes" and not ctx.get("kubernetes_api_server"):
        status_set('blocked',
                   'Kubernetes API unavailable')
        return

    # TODO: what should happens if relation departed?

    changed = common_utils.apply_keystone_ca(MODULE, ctx)
    changed |= common_utils.render_and_log("vrouter.env",
        BASE_CONFIGS_PATH + "/common_vrouter.env", ctx)
    changed |= common_utils.render_and_log("vrouter.yaml",
        CONFIGS_PATH + "/docker-compose.yaml", ctx)
    docker_utils.compose_run(CONFIGS_PATH + "/docker-compose.yaml", changed)

    # local file for vif utility
    common_utils.render_and_log("contrail-vrouter-agent.conf",
           "/etc/contrail/contrail-vrouter-agent.conf", ctx, perms=0o440)

    common_utils.update_services_status(MODULE, SERVICES)


def fix_dns_settings():
    # in some bionix installations DNS is proxied by local instance
    # of systed-resolved service. this services applies DNS settings
    # that was taken overDHCP to exact interface - ens3 for example.
    # and when we move traffic from ens3 to vhost0 then local DNS
    # service stops working correctly because vhost0 doesn't have
    # upstream DNS server setting.
    # while we don't know how to move DNS settings to vhost0 in
    # vrouter-agent container - let's remove local DNS proxy from
    # the path and send DNS requests directly to the HUB.
    # this situation is observed only in bionic.
    if lsb_release()['DISTRIB_CODENAME'] != 'bionic':
        return
    if os.path.exists('/run/systemd/resolve/resolv.conf'):
        os.remove('/etc/resolv.conf')
        os.symlink('/run/systemd/resolve/resolv.conf', '/etc/resolv.conf')


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
        render("TEMPLATE.qemu",
               "/etc/apparmor.d/libvirt/TEMPLATE.qemu",
               dict())
        libvirt_file = '/etc/apparmor.d/abstractions/libvirt-qemu'
        with open(libvirt_file) as f:
            data = f.readlines()
        new_line = "/run/vrouter/* rw,"
        for line in data:
            if new_line in line:
                break
        else:
            with open(libvirt_file, "a") as f:
                f.write("\n  " + new_line + "\n")

    service_restart("apparmor")
    check_call(["/etc/init.d/apparmor",  "reload"])


def get_vhost_ip():
    try:
        addr = netifaces.ifaddresses("vhost0")
        if netifaces.AF_INET in addr and len(addr[netifaces.AF_INET]) > 0:
            return addr[netifaces.AF_INET][0]["addr"]
    except ValueError:
        pass

    iface = config.get("physical-interface")
    if not iface:
        iface = _get_default_gateway_iface()
    addr = netifaces.ifaddresses(iface)
    if netifaces.AF_INET in addr and len(addr[netifaces.AF_INET]) > 0:
        return addr[netifaces.AF_INET][0]["addr"]

    return None
