#!/usr/bin/env python

import json
import os
from socket import gethostname, gethostbyname
import sys

from charmhelpers.core.hookenv import (
    Hooks,
    UnregisteredHookError,
    config,
    log,
    relation_get,
    relation_set,
    relation_ids,
    related_units,
    status_set,
    application_version_set,
    local_unit,
)

from charmhelpers.fetch import (
    apt_install,
    apt_upgrade,
    configure_sources
)
from charmhelpers.core.host import (
    service_start,
    service_restart,
    init_is_systemd,
    service
)
from charmhelpers.core.kernel import modprobe
from charmhelpers.core.hugepage import hugepage_support
from subprocess import (
    CalledProcessError,
    check_output,
)
from contrail_agent_utils import (
    configure_crashes,
    configure_vrouter_interface,
    drop_caches,
    dkms_autoinstall,
    update_vrouter_provision_status,
    write_configs,
    update_unit_status,
    set_dpdk_options,
    configure_hugepages,
    get_hugepages,
    fix_libvirt,
    tls_changed,
    get_control_network_ip,
)

PACKAGES = ["dkms", "contrail-vrouter-agent", "contrail-utils",
            "contrail-vrouter-common", "contrail-setup"]

PACKAGES_DKMS_INIT = ["contrail-vrouter-dkms", "contrail-vrouter-init"]
PACKAGES_DPDK_INIT = ["contrail-vrouter-dpdk", "contrail-vrouter-dpdk-init"]

hooks = Hooks()
config = config()


@hooks.hook("install.real")
def install():
    status_set("maintenance", "Installing...")

    configure_crashes()
    configure_sources(True, "install-sources", "install-keys")
    apt_upgrade(fatal=True, dist=True)
    packages = list()
    packages.extend(PACKAGES)
    if not config.get("dpdk"):
        packages.extend(PACKAGES_DKMS_INIT)
    else:
        # services must not be started before config files creation
        if not init_is_systemd():
            with open("/etc/init/supervisor-vrouter.override", "w") as conf:
                conf.write("manual\n")
        else:
            # and another way with systemd
            for srv in ("contrail-vrouter-agent", "contrail-vrouter-dpdk"):
                try:
                    os.remove("/etc/systemd/system/{}.sevice".format(srv))
                except OSError:
                    pass
                os.symlink("/dev/null", "/etc/systemd/system/{}.sevice"
                           .format(srv))
        packages.extend(PACKAGES_DPDK_INIT)
        # apt-get upgrade can install new kernel so we need to re-install
        # packages with dpdk drivers
        kver = check_output(["uname", "-r"]).rstrip()
        packages.append("linux-image-extra-" + kver)
    apt_install(packages, fatal=True)
    try:
        output = check_output(["dpkg-query", "-f", "${Version}\\n",
                               "-W", "contrail-vrouter-agent"])
        version = output.decode('UTF-8').rstrip()
        application_version_set(version)
    except CalledProcessError:
        return None

    status_set("maintenance", "Configuring...")
    os.chmod("/etc/contrail", 0o755)
    os.chown("/etc/contrail", 0, 0)

    if config.get("dpdk"):
        install_dpdk()
    else:
        # supervisord must be started after installation
        if not init_is_systemd():
            # supervisord
            service_restart("supervisor-vrouter")
        install_dkms()


def install_dkms():
    try:
        log("Loading kernel module vrouter")
        modprobe("vrouter")
    except CalledProcessError:
        log("vrouter kernel module failed to load,"
            " clearing pagecache and retrying")
        drop_caches()
        modprobe("vrouter")
    dkms_autoinstall()
    configure_vrouter_interface()
    config["vrouter-expected-provision-state"] = False
    status_set("blocked", "Missing relation to contrail-controller")


def install_dpdk():
    modprobe(config["dpdk-driver"])
    try:
        modprobe("vfio-pci")
    except:
        pass
    dkms_autoinstall()
    pages = get_hugepages()
    if pages:
        hugepage_support("root", group="root", nr_hugepages=pages,
                         mnt_point="/hugepages")
        service_restart("libvirt-bin")

    configure_vrouter_interface()
    set_dpdk_options()
    write_configs()

    if not init_is_systemd():
        os.remove("/etc/init/supervisor-vrouter.override")
        service_start("supervisor-vrouter")
        service_restart("contrail-vrouter-agent")
    else:
        service("enable", "contrail-vrouter-dpdk")
        service_start("contrail-vrouter-dpdk")
        service("enable", "contrail-vrouter-agent")
        service_start("contrail-vrouter-agent")

    fix_libvirt()


@hooks.hook("config-changed")
def config_changed():
    # Charm doesn't support changing of some parameters that are used only in
    # install hook.
    for key in ("remove-juju-bridge", "physical-interface", "dpdk"):
        if config.changed(key):
            raise Exception("Configuration parameter {} couldn't be changed"
                            .format(key))

    if config["dpdk"]:
        for key in ("dpdk-main-mempool-size", "dpdk-pmd-txd-size", "dpdk-pmd-rxd-size", "dpdk-coremask"):
            if config.changed(key):
                set_dpdk_options()
        configure_hugepages()

    write_configs()


@hooks.hook("contrail-controller-relation-joined")
def contrail_controller_joined():
    settings = {'dpdk': config["dpdk"], 'unit-type': 'agent'}
    relation_set(relation_settings=settings)


@hooks.hook("contrail-controller-relation-changed")
def contrail_controller_changed():
    data = relation_get()
    log("RelData: " + str(data))

    def _update_config(key, data_key):
        if data_key in data:
            config[key] = data[data_key]

    _update_config("analytics_servers", "analytics-server")
    _update_config("api_ip", "private-address")
    _update_config("api_port", "port")
    _update_config("auth_info", "auth-info")
    _update_config("orchestrator_info", "orchestrator-info")
    config["vrouter-expected-provision-state"] = True
    config.save()

    write_configs()
    update_vrouter_provision_status()
    update_unit_status()


@hooks.hook("contrail-controller-relation-departed")
def contrail_controller_node_departed():
    units = [unit for rid in relation_ids("contrail-controller")
                      for unit in related_units(rid)]
    if units:
        return

    config["vrouter-expected-provision-state"] = False
    update_vrouter_provision_status()
    status_set("blocked", "Missing relation to contrail-controller")


@hooks.hook('tls-certificates-relation-joined')
def tls_certificates_relation_joined():
    cn = gethostname().split(".")[0]
    sans = [cn]
    sans_ips = []
    try:
        sans_ips.append(gethostbyname(cn))
    except:
        pass
    control_ip = get_control_network_ip()
    if control_ip not in sans_ips:
        sans_ips.append(control_ip)
    res = check_output(['getent', 'hosts', control_ip])
    control_name = res.split()[1].split('.')[0]
    if control_name not in sans:
        sans.append(control_name)
    sans_ips.append("127.0.0.1")
    sans.extend(sans_ips)
    settings = {
        'sans': json.dumps(sans),
        'common_name': cn,
        'certificate_name': cn
    }
    log("TLS_CTX: {}".format(settings))
    relation_set(relation_settings=settings)


@hooks.hook('tls-certificates-relation-changed')
def tls_certificates_relation_changed():
    unitname = local_unit().replace('/', '_')
    cert_name = '{0}.server.cert'.format(unitname)
    key_name = '{0}.server.key'.format(unitname)
    cert = relation_get(cert_name)
    key = relation_get(key_name)
    ca = relation_get('ca')

    if not cert or not key:
        log("tls-certificates client's relation data is not fully available")
        cert = key = None

    tls_changed(cert, key, ca)


@hooks.hook('tls-certificates-relation-departed')
def tls_certificates_relation_departed():
    tls_changed(None, None, None)


@hooks.hook("update-status")
def update_status():
    update_vrouter_provision_status()
    update_unit_status()


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log("Unknown hook {} - skipping.".format(e))


if __name__ == "__main__":
    main()
