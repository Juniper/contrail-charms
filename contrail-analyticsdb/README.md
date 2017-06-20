Overview
--------

OpenContrail (www.opencontrail.org) is a fully featured Software Defined
Networking (SDN) solution for private clouds. It supports high performance
isolated tenant networks without requiring external hardware support. It
provides a Neutron plugin to integrate with OpenStack.

This charm provides the analytics DB node component which includes
cassandra, kafka and zookeeper services.

Only OpenStack Mitaka or newer is supported.
Only for Contrail 4.0 for now.
Juju 2.0 is required.

Usage
-----

Contrail Controller is prerequisite service to deploy.
Once ready, deploy and relate as follows:

    juju deploy contrail-analyticsdb
    juju add-relation contrail-analyticsdb contrail-controller

Resource
--------

The charm requires docker image with Contrail Analytics DB as a resource.
It can be provided as usual for Juju 2.0 in deploy command or
through attach-resource:

    juju attach contrail-analyticsdb contrail-analyticsdb="$PATH_TO_IMAGE"
