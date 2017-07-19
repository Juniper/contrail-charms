#!/usr/bin/env python

import os
import sys

from charmhelpers.core.hookenv import (
    Hooks,
    UnregisteredHookError,
    config,
    log,
    relation_get,
    relation_ids,
    related_units,
    status_set,
    application_version_set,
)

from charmhelpers.fetch import (
    apt_install,
    apt_upgrade,
    configure_sources
)
from charmhelpers.core.host import service_restart, lsb_release
from charmhelpers.core.kernel import modprobe
from subprocess import (
    CalledProcessError,
    check_output,
)
from contrail_agent_utils import (
    configure_vrouter_interface,
    drop_caches,
    dkms_autoinstall,
    update_vrouter_provision_status,
    write_configs,
    update_unit_status,
    reprovision_vrouter,
)

PACKAGES = ["contrail-vrouter-dkms", "contrail-vrouter-agent",
            "contrail-vrouter-common", "contrail-setup",
            "contrail-utils"]

PACKAGES_DKMS_INIT = ["contrail-vrouter-init"]
PACKAGES_DPDK_INIT = ["contrail-vrouter-dpdk-init"]

hooks = Hooks()
config = config()


@hooks.hook("install.real")
def install():
    status_set("maintenance", "Installing...")

    configure_sources(True, "install-sources", "install-keys")
    apt_upgrade(fatal=True, dist=True)
    packages = list()
    packages.extend(PACKAGES)
    # TODO: support dpdk config option
    packages.extend(PACKAGES_DKMS_INIT)
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

    # supervisord must be started after installation
    release = lsb_release()["DISTRIB_CODENAME"]
    if release == 'trusty':
        # supervisord
        service_restart("supervisor-vrouter")

    try:
        log("Loading kernel module vrouter")
        modprobe("vrouter")
    except CalledProcessError:
        log("vrouter kernel module failed to load,"
            " clearing pagecache and retrying")
        drop_caches()
        modprobe("vrouter")
    dkms_autoinstall("vrouter")
    configure_vrouter_interface()
    config["vrouter-expected-provision-state"] = False
    status_set("blocked", "Missing relation to contrail-controller")


@hooks.hook("config-changed")
def config_changed():
    # Charm doesn't support changing of some parameters that are used only in
    # install hook.
    for key in ("remove-juju-bridge", "physical-interface"):
        if config.changed(key):
            raise Exception("Configuration parameter {} couldn't be changed"
                            .format(key))

    write_configs()
    if config.changed("control-network"):
        reprovision_vrouter()


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
    _update_config("api_vip", "api-vip")
    _update_config("ssl_ca", "ssl-ca")
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
