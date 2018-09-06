Overview
--------

OpenContrail (www.opencontrail.org) is a fully featured Software Defined
Networking (SDN) solution for private clouds. It supports high performance
isolated tenant networks without requiring external hardware support. It
provides a Neutron plugin to integrate with OpenStack.

This charm is designed to be used in conjunction with the rest of the OpenStack
related charms in the charm store to virtualize the network that Nova Compute
instances plug into.

This subordinate charm provides the vRouter component which
contains the contrail-vrouter-agent service. It can be related to any charm
to provide vRouter functionality on the node. For OpenStack it should be
nova-compute application to provide vRouter functionality for OpenStack.

Only OpenStack Mitaka or newer is supported.
Only for Contrail 4.0 for now.
Juju 2.0 is required.

Usage
-----

Contrail Controller are prerequisite service to deploy.

Once ready, deploy and relate as follows:

    juju deploy contrail-agent
    juju add-relation contrail-agent:juju-info nova-compute:juju-info
    juju add-relation contrail-agent contrail-controller

Install Sources
---------------

The version of packages installed when deploying must be configured using the
'install-sources' option. This is a multilined value that may refer to PPAs or
Deb repositories.

Control Node Relation
---------------------

This charm is typically related to contrail-controller.
This instructs the Contrail vRouter agent to use the API endpoints for
locating needed information.


DPDK mode
---------

This charm supports DPDK mode of Contrail vrouter.
DPDK mode requires more than one ethernet adapters. User have to configure
control-network and physical-interface properly for correct work.
For example system has ens3 interface with network 10.0.0.0/24 and 
default gateway is in this network and ens4 interface.
Configuration can be applied as follows:

    juju config dpdk=True physical-interface=ens4 control-network=10.0.0.0/24

User have to configure hugepages and unset it in charm configuration
or let the charm configure amount of it.
User can provide coremask for DPDK driver.
Also user have to provide correct UIO driver's name. Charm tries to load
it at install stage and raises an error if kernel module can't be loaded.

Repository for this charm and for contrail-openstack charm must additionaly
contain Contrail's version for packages: nova-*, python-nova, libvirt*

List of options
---------------

Option   | Type| default | Description
---------|-----|---------|-------------
physical-interface | string | | Specify the interface to install vhost0 on. If left empty, vhost0 will be installed on the default gateway interface.
vhost-gateway | string | auto | Specify the gateway for vhost0, either an IPv4 address or keyword 'auto'. 'auto' will set gateway automatically based on host's existing routes.
remove-juju-bridge | boolean | true | Juju on MAAS creates bridges for deploying LXD/LXC and KVM workloads. Enable this to remove such a bridge if you want to install vhost0 directly on the underlying interface.
dpdk | boolean | false | Use user space DPDK vRouter
dpdk-driver | string | uio_pci_generic | DPDK driver to use for physical interface. Interface can be specified using vhost-interface.
dpdk-hugepages | string | 70% | Number of huge pages to reserve for use with DPDK vRouter and OpenStack instances. Value can be specified as percentage of system memory e.g. 70% or as number of huge pages e.g. 1434.
dpdk-coremask | string | 1 | vRouter CPU affinity mask. Determines on which CPUs DPDK vRouter will run. Value can be specified as either a hexidecimal bitmask e.g. 0xF or as a numbered list separated by commas e.g. 0,1 (ranges are also supported using '-' e.g. 0-2). It must specify only real cores cause contrail-vrouter-dpdk service will  | string | | Main packet pool size.
dpdk-main-mempool-size | string | | Main packet pool size.
dpdk-pmd-txd-size | string | | DPDK PMD Tx Descriptor size.
dpdk-pmd-rxd-size | string | | DPDK PMD Rx Descriptor size.
docker-registry | string | opencontrailnightly | URL of docker-registry
docker-registry-insecure | boolean | false | Is it docker-registry insecure and should docker be configured for it
docker-user | string | Login to the docker registry.
docker-password | string | | Password to the docker registry.
image-tag | type: string | latest | Tag of docker image.
log-level | string | SYS_NOTICE | Log level for contrail services. Valid values are: SYS_EMERG, SYS_ALERT, SYS_CRIT, SYS_ERR, SYS_WARN, SYS_NOTICE, SYS_INFO, SYS_DEBUG
