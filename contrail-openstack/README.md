Overview
--------

OpenContrail (www.opencontrail.org) is a fully featured Software Defined
Networking (SDN) solution for private clouds. It supports high performance
isolated tenant networks without requiring external hardware support. It
provides a Neutron plugin to integrate with OpenStack.

This charm is designed to be used in conjunction with the rest of the OpenStack
related charms in the charm store to virtualize the network that Nova Compute
instances plug into.

This subordinate charm provides connectivity of Contrail to the Neutron API component
and Nova Compute component and configures neutron-server and nova-compute.

Only OpenStack Mitaka or newer is supported.
Only for Contrail 4.0 for now.
Juju 2.0 is required.

Usage
-----

Contrail Controller are prerequisite service to deploy.

Neutron API and Nova Compute should be deployed with legacy plugin management set to false:

    nova-compute:
      manage-neutron-plugin-legacy-mode: false
    neutron-api:
      manage-neutron-plugin-legacy-mode: false

Once ready, deploy and relate as follows:

    juju deploy contrail-openstack
    juju add-relation contrail-openstack neutron-api
    juju add-relation contrail-openstack nova-compute
    juju add-relation contrail-openstack contrail-controller

Install Sources
---------------

The version of packages installed when deploying must be configured using the
'install-sources' option. This is a multilined value that may refer to PPAs or
Deb repositories.

Nova Metadata
-------------

Option 'enable-metadata-server' controls if a local nova-api-metadata service is
started (per Compute Node) and registered to serve metadata requests. It is
the recommended approach for serving metadata to instances and is enabled by
default.
