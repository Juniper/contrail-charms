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

External Docker repository
--------------------------

Istead of attaching resource with docker image charm can accept image from remote docker repository.
docker-registry should be specified if the registry is only accessible via http protocol (insecure registry).
docker-user / docker-password can be specified if registry requires authentification.
And image-name / image-tag are the parameters for the image itself.

High Availability (HA)
----------------------

Multiple units of this charm can be deployed to support HA deployments:

    juju add-unit contrail-controller

Relating to haproxy charm (http-services relation) allows multiple units to be
load balanced:

    juju add-relation contrail-controller:http-services haproxy
    juju add-relation contrail-controller:https-services haproxy

The charm can tell to haproxy list of backends via two relations: http-services and https-services.
It passes unsecured backend (like contrail-api:8082) via http-services and secured (like webUI:8143) via https-services.
Such option allows to relate this charm to different haproxy applications.

For https connections there are two modes - tcp and http. Mode tcp means that haproxy will be configured in pass-through mode and mode http mode means that haproxy will be configured in termination mode. By default tcp mode (webui) is used. If you want to implement ssl-termination for HAproxy for webui you can configure it:

    juju config contrail-controller haproxy-https-mode=http
    juju config haproxy ssl_cert=SELFSIGNED

For http connections there are two modes - http and https. Both modes configure haproxy in http mode (termination). Mode https additionaly configure haproxy to use SSL for frontend. By default http mode is used. To confugire haproxy in https mode you can run:

    juju config contrail-controller haproxy-http-mode=https

Or another certificate is also can be used for haproxy charm. Please check its manual for more information.

SSL
---

This charm supports relation to easyrsa charm to obtain certificates for XMPP and Sandesh connections:

    juju add-relation contrail-controller easyrsa

Please note that in this case all charms must be related to easyrsa. Components require CA certificate for communication.

External RabbitMQ
-----------------

Charm can be related to RabbitMQ:

    juju add-relation contrail-controller rabbitmq-server:amqp

In this case internal RabbitMQ server will not be run and Contrail software will be configured
to use external one.
