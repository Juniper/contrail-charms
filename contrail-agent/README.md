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
