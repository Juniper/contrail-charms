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
Only OpenStack Icehouse or newer is supported.
Juju 1.23.2+ required.

Usage
-----

Nova Compute, Contrail Configuration and Keystone are prerequisite services to
deploy.

Nova Compute should be deployed with legacy plugin management set to false:

    nova-compute:
      manage-neutron-plugin-legacy-mode: false

Once ready, deploy and relate as follows:

    juju deploy neutron-contrail
    juju add-relation nova-compute neutron-contrail
    juju add-relation neutron-contrail:contrail-discovery contrail-configuration:contrail-discovery
    juju add-relation neutron-contrail:contrail-api contrail-configuration:contrail-api
    juju add-relation neutron-contrail keystone

Install Sources
---------------

The version of OpenContrail installed when deploying can be changed using the
'install-sources' option. This is a multilined value that may refer to PPAs or
Deb repositories.

Control Node Relation
---------------------

This charm is typically related to contrail-configuration:contrail-discovery.
This instructs the Contrail vRouter agent to use the discovery service for
locating control nodes. This is the recommended approach.

Should the user wish to use vRouter configuration that specifies the location
of control nodes explicitly, not using the discovery service, they can relate
to a contrail-control charm:

    juju add-relation neutron-contrail contrail-control

Nova Metadata
-------------

To use Nova Metadata with Nova Compute instances, a metadata service must first
be registered. Registration allows OpenContrail to create the appropriate
network config to proxy requests from instances to a nova-api service on the
network.

Option 'local-metadata-server' controls if a local nova-api-metadata service is
started (per Compute Node) and registered to serve metadata requests. It is
the recommended approach for serving metadata to instances and is enabled by
default.

Alternatively, relating to a charm implementing neutron-metadata interface will
use this external metadata service:

    juju add-relation neutron-contrail neutron-metadata-charm

contrail-configuration charm also needs to be related to the same charm to
register the metadata service:

    juju add-relation contrail-configuration neutron-metadata-charm

Virtual Gateways
----------------

For launched instances to be able to access external networks e.g. the Internet
a gateway is required that allows virtual network traffic to traverse an IP
network.

For production setups, this is typically a hardware gateway. For testing
purposes OpenContrail provides a software gateway (Simple Gateway) that runs on
Compute Node(s) and provides this function.

Option 'virtual-gateways' allows specifying of one or more software gateways.
The value is a YAML encoded string using a list of maps, where each map
consists of the following attributes:

    project - project name
    network - network name
    interface - interface to use (will be created)
    subnets - list of virtual subnets to route
    routes - list of routes gateway will make available to virtual subnets,
             0.0.0.0/0 selects all routes

For example to create a gateway for virtual subnet 10.0.10.0/24 on
'admin:public' network using local interface vgw for routing:

    juju set neutron-contrail \
      "virtual-gateways=[ { project: admin, network: public, interface: vgw, subnets: [ 10.0.10.0/24 ], routes: [ 0.0.0.0/0 ] } ]"

Previously specified gateways will be removed.

The routing of external IP networks needs to be updated if virtual network
traffic will traverse it. Traffic flow from the IP network should be directed to
one of the Compute Nodes.

For example a static route could be added to the router of the Compute Node
network:

    // assuming it's a linux box
    sudo ip route add 10.0.10.0/24 via <compute ip>

The virtual-gateways option can be used with 'floating-ip-pools' option of the
contrail-configuration charm to create a typical Neutron setup of launched
instances attached to a private network, each with an assigned public/external
floating IP.

Using the running example above, you would use Neutron to create an external
network with subnet 10.0.10.0/24 and a private network of 10.0.5.0/24. You would
set the virtual-gateways option (as above) and the floating-ip-pools option.
You would attach launched instances to the private network and then assign them
floating IPs from the external network. vRouter will automatically perform 1:1
NAT of an external address to a private one. (Note: security groups may still
need to be updated to allow traffic flow).
