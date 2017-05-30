Overview
--------

OpenContrail (www.opencontrail.org) is a fully featured Software Defined
Networking (SDN) solution for private clouds. It supports high performance
isolated tenant networks without requiring external hardware support. It
provides a Neutron plugin to integrate with OpenStack.

This charm is designed to be used in conjunction with the rest of the OpenStack
related charms in the charm store to virtualize the network that Nova Compute
instances plug into.

This subordinate charm provides the Nova Compute vRouter component which
contains the contrail-vrouter-agent service.
Only OpenStack Mitaka or newer is supported.
Only for Contrail 4.0 for now.
Juju 2.0 is required.

Usage
-----

Nova Compute, Contrail Controller are prerequisite services to
deploy.

Nova Compute should be deployed with legacy plugin management set to false:

    nova-compute:
      manage-neutron-plugin-legacy-mode: false

Once ready, deploy and relate as follows:

    juju deploy contrail-openstack-compute
    juju add-relation nova-compute contrail-openstack-compute
    juju add-relation contrail-openstack-compute contrail-controller

Install Sources
---------------

The version of OpenContrail installed when deploying can be changed using the
'install-sources' option. This is a multilined value that may refer to PPAs or
Deb repositories.

Control Node Relation
---------------------

This charm is typically related to contrail-controller.
This instructs the Contrail vRouter agent to use the API endpoints for
locating needed information.

Nova Metadata
-------------

To use Nova Metadata with Nova Compute instances, a metadata service must first
be registered. Registration allows OpenContrail to create the appropriate
network config to proxy requests from instances to a nova-api service on the
network.

Option 'enable-metadata-server' controls if a local nova-api-metadata service is
started (per Compute Node) and registered to serve metadata requests. It is
the recommended approach for serving metadata to instances and is enabled by
default.
