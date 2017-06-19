Overview
--------

OpenContrail (www.opencontrail.org) is a fully featured Software Defined
Networking (SDN) solution for private clouds. It supports high performance
isolated tenant networks without requiring external hardware support. It
provides a Neutron plugin to integrate with OpenStack.

This charm provides the Contrail Controller role that includes
configuration API server, control API server, WebUI and needed third-party
components.

Only OpenStack Mitaka or newer is supported.
Only for Contrail 4.0 for now.
Juju 2.0 is required.

Usage
-----

TODO

charm can tell to haproxy list of backends via two relations: http-services and https-services.
it tells unsecured backend (like contrail-api:8082 and webUI:8080) via http-services
and secured (like webUI:8143) via https-services.
it allows to relate this charm to different haproxy applications where first has ssl_cert/ssl_key in
configuration and makes SSL termination itself but second doesn't have SSL parameters and acts
as a proxy/load-balancer.