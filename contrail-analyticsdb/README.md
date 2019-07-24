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

External Docker repository
--------------------------

Istead of attaching resource with docker image charm can accept image from remote docker repository.
docker-registry should be specified if the registry is only accessible via http protocol (insecure registry).
docker-user / docker-password can be specified if registry requires authentification.
And image-name / image-tag are the parameters for the image itself.

SSL
---

This charm supports relation to easyrsa charm to obtain certificates for XMPP and Sandesh connections:

    juju add-relation contrail-analyticsdb easyrsa

Please note that in this case all charms must be related to easyrsa. Components require CA certificate for communication.
