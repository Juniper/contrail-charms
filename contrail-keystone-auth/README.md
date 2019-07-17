Overview
--------

OpenContrail (www.opencontrail.org) is a fully featured Software Defined
Networking (SDN) solution for private clouds. It supports high performance
isolated tenant networks without requiring external hardware support. It
provides a Neutron plugin to integrate with OpenStack.

This charm is designed to be used in conjunction with the rest of the OpenStack
related charms in the charm store to virtualize the network that Nova Compute
instances plug into.

The charm provides ability to get auth information from keystone and pass it
to controller charm which uses it and passes to related charms.

Usage
-----

Deploy it and relate to other ends.

    juju deploy contrail-keystone-auth
    juju add-relation contrail-controller contrail-keystone-auth
    juju add-relation contrail-keystone-auth keystone
