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
    #TODO: get iface from route to CONTROL_NODES
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


def get_context():
    ctx = {}
    ctx["ssl_enabled"] = config.get("ssl_enabled", False)
    ctx["log_level"] = config.get("log-level", "SYS_NOTICE")
    ctx["container_registry"] = config.get("docker-registry")
    ctx["contrail_version_tag"] = config.get("image-tag")

    iface = config.get("physical-interface")
    if not iface:
        iface = _get_default_gateway_iface()
    ctx["physical_interface"] = iface
    gateway_ip = config.get("vhost-gateway")
    if gateway_ip == "auto":
        gateway_ip = _get_iface_gateway_ip(iface)
    ctx["vrouter_gateway"] = gateway_ip #if gateway_ip else ''

    ctx["agent_mode"] = "dpdk" if config["dpdk"] else "kernel"
    if config["dpdk"]:
        ctx["dpdk_additional_args"] = _get_dpdk_args()
        ctx["dpdk_driver"] = config.get("dpdk-driver")
        ctx["dpdk_coremask"] = config.get("dpdk-coremask")
        ctx["dpdk_hugepages"] = _get_hugepages()

    info = common_utils.json_loads(config.get("orchestrator_info"), dict())
    ctx.update(info)

    ips = [relation_get("private-address", unit, rid)
           for rid in relation_ids("contrail-controller")
           for unit in related_units(rid)]
    ctx["controller_servers"] = ips
    ips = common_utils.json_loads(config.get("analytics_servers"), list())
    ctx["analytics_servers"] = ips

    log("CTX: " + str(ctx))

    ctx.update(common_utils.json_loads(config.get("auth_info"), dict()))
    return ctx


def render_config(ctx):
    common_utils.apply_keystone_ca(ctx)
    common_utils.render_and_log("vrouter.env",
           BASE_CONFIGS_PATH + "/common_vrouter.env", ctx)

    common_utils.render_and_log("vrouter.yaml",
           CONFIGS_PATH + "/docker-compose.yaml", ctx)

    common_utils.render_and_log("contrail-vrouter-agent.conf",
           "/etc/contrail/contrail-vrouter-agent.conf", ctx, perms=0o440)


def update_charm_status():
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
    if missing_relations:
        status_set('blocked',
                   'Missing relations: ' + ', '.join(missing_relations))
        return
    if not ctx.get("analytics_servers"):
        status_set('blocked',
                   'Missing analytics_servers info in relation '
                   'with contrail-controller.')
    if not ctx.get("cloud_orchestrator"):
        status_set('blocked',
                   'Missing cloud_orchestrator info in relation '
                   'with contrail-controller.')
        return
    if not ctx.get("keystone_ip"):
        status_set('blocked',
                   'Missing auth info in relation with contrail-controller.')
        return
    # TODO: what should happens if relation departed?

    render_config(ctx)
    docker_utils.compose_run(CONFIGS_PATH + "/docker-compose.yaml")
    common_utils.update_services_status(SERVICES)


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


def tls_changed(cert, key, ca):
    changed = common_utils.update_certificates(cert, key, ca)
    if not changed:
        log("Certificates were not changed.")
        return

    log("Certificates have changed. Rewrite configs and rerun services.")
    config["ssl_enabled"] = (cert is not None and len(cert) > 0)
    config.save()
    update_charm_status()


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
