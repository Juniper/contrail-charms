Overview
--------

OpenContrail (www.opencontrail.org) is a fully featured Software Defined
Networking (SDN) solution for private clouds. It supports high performance
isolated tenant networks without requiring external hardware support. It
provides a Neutron plugin to integrate with OpenStack.

This charm provides the Contrail Controller role that includes
configuration API server, control API server, WebUI and required third-party
components.

Only OpenStack Mitaka or newer is supported.
Only for Contrail 4.0 for now.
Juju 2.0 is required.

Usage
-----

Contrail Analytics is prerequisite service to deploy.
Once ready, deploy and relate as follows:

    juju deploy contrail-controller
    juju add-relation contrail-analytics contrail-controller

Resource
--------

The charm requires docker image with Contrail Controller as a resource.
It can be provided as usual for Juju 2.0 in deploy command or
through attach-resource:

    juju attach contrail-controller contrail-controller="$PATH_TO_IMAGE"

High Availability (HA)
----------------------

Multiple units of this charm can be deployed to support HA deployments:

    juju add-unit contrail-controller

Relating to haproxy charm (http-services relation) allows multiple units to be
load balanced:

    juju add-relation contrail-controller:http-services haproxy
    juju add-relation contrail-controller:https-services haproxy

The charm can tell to haproxy list of backends via two relations: http-services and https-services.
It tells unsecured backend (like contrail-api:8082 and webUI:8080) via http-services
and secured (like webUI:8143) via https-services.
Such option allows to relate this charm to different haproxy applications
where first haproxy app has ssl_cert/ssl_key in configuration and makes SSL termination itself
but second doesn't have SSL parameters and acts as a proxy/load-balancer.
