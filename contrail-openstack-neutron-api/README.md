Overview
--------

OpenContrail (www.opencontrail.org) is a fully featured Software Defined
Networking (SDN) solution for private clouds. It supports high performance
isolated tenant networks without requiring external hardware support. It
provides a Neutron plugin to integrate with OpenStack.

This charm is designed to be used in conjunction with the rest of the OpenStack
related charms in the charm store to virtualize the network that Nova Compute
instances plug into.

This subordinate charm provides the Neutron API component which configures
neutron-server for OpenContrail.
Only OpenStack Mitaka or newer is supported.
Only for Contrail 4.0 for now.
Juju 2.0 is required.

Usage
-----

Neutron API, Contrail Controller are prerequisite services to
deploy.

Neutron API should be deployed with legacy plugin management set to false:

    neutron-api:
      manage-neutron-plugin-legacy-mode: false

Once ready, deploy and relate as follows:

    juju deploy contrail-openstack-neutron-api
    juju add-relation neutron-api contrail-openstack-neutron-api
    juju add-relation contrail-openstack-neutron-api contrail-controller

Install Sources
---------------

The version of OpenContrail installed when deploying can be changed using the
'install-sources' option. This is a multilined value that may refer to PPAs or
Deb repositories.
