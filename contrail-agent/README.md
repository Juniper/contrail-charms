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

Plugin option
-------------

This charm can be linked with any plugin by vrouter-plugin relation.
With option wait-for-external-plugin code will wait for ready flag in the relation.
This charm accepts 'settings' value as a serialized dict to json in relation.
All these option will be serilized to container settings and then
into contrail-vrouter-agent.conf.
Example of dict: {"DEFAULT": {"key1": "value1"}, "SECTION_2": {"key1": "value1"}}

Kubernetes
----------

This charm can be used with The Charmed Distribution Of Kubernetes.
In this case relation must be set to Kubernetes Worker instead of the nova-compute:

```
juju add-relation contrail-agent:juju-info kubernetes-worker:juju-info
```

SSL
---

This charm supports relation to easyrsa charm to obtain certificates for XMPP and Sandesh connections:

    juju add-relation contrail-agent easyrsa

Please note that in this case all charms must be related to easyrsa. Components require CA certificate for communication.
