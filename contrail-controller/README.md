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
It tells unsecured backend (like contrail-api:8082 and webUI:8080) via http-services
and secured (like webUI:8143) via https-services.
Such option allows to relate this charm to different haproxy applications
where first haproxy app has ssl_cert/ssl_key in configuration and makes SSL termination itself
but second doesn't have SSL parameters and acts as a proxy/load-balancer.

SSL
---

This charm supports relation to easyrsa charm to obtain certificates for XMPP and Sandesh connections:

    juju add-relation contrail-controller easyrsa
    juju add-relation contrail-agent easyrsa

This mode supports only deployment where analitics and analiticsdb containers deployed
on the same machines as controller container.

External RabbitMQ
-----------------

Charm can be related to RabbitMQ:

    juju add-relation contrail-controller rabbitmq-server:amqp

In this case internal RabbitMQ server will not be run and Contrail software will be configured
to use external one.

List of options
---------------

Option   | Type| default | Description
---------|-----|---------|-------------
control-network | string | | The IP address and netmask of the control network (e.g. 192.168.0.0/24). This network will be used for Contrail endpoints. If not specified, default network will be used.
auth-mode | string | rbac | It represents 'aaa_mode' configuration key of Contrail. Can be one of: 'rbac', 'cloud-admin' or 'no-auth' Authentication mode. Detailed information can be found in the [Contrail documentation](https://github.com/Juniper/contrail-controller/wiki/RBAC) In case of 'rbac' charm will configure Contrail to RBAC mode and administrator must configure RBAC rules to allow users to work. In case of 'cloud-admin' charm will configure Contrail in compatible mode.
cassandra-minimum-diskgb | string | 20 | Contrail has this as parameter and checks it at startup. If disk is smaller then status of DB is not good.
auth-mode | string | rbac | It represents 'aaa_mode' configuration key of Contrail. Can be one of: 'rbac', 'cloud-admin' or 'no-auth' Authentication mode. Detailed information can be found in the Contrail documentation. https://github.com/Juniper/contrail-controller/wiki/RBAC In case of 'rbac' charm will configure Contrail to RBAC mode and administrator must configure RBAC rules to allow users to work. In case of 'cloud-admin' charm will configure Contrail in compatible mode.
cassandra-jvm-extra-opts | string | | Memory limits for Java process of Cassandra.
cloud-admin-role | string | admin | Role name in keystone for users that have full access to everything.
global-read-only-role | string | | Role name in keystone for users that have read-only access to everything.
vip | string | | Contrail API VIP to be used for configuring client-side software like neutron plugin. (to be set up also in KeepAlived charm configuration if it’s used for HA) Private IP of the first Contrail API unit will be used if not set.
use-external-rabbitmq | boolean | false | Charm will wait for external AMQP relation if set. Charm will use internal RabbitMQ server if not set. **NOTE: Changing this flag after deployment is dangerous!**
flow-export-rate | string | 0 | Defines how much flow records will be exported by vRouter agent to the Contrail Collector when a flow is created or deleted.
docker-registry | string | | URL of docker-registry. Should be passed only if registry is not secured and must be added to docker config to allow work with it.
docker-registry-insecure | boolean | false | Is it docker-registry insecure and should docker be configured for it
docker-user | string | | Login to the docker registry.
docker-password | string | | Password to the docker registry.
image-tag | string | | Tag of docker image.
log-level | string | SYS_NOTICE | Log level for contrail services. Valid values are: SYS_EMERG, SYS_ALERT, SYS_CRIT, SYS_ERR, SYS_WARN, SYS_NOTICE, SYS_INFO, SYS_DEBUG
http_proxy | string | | URL to use for HTTP_PROXY to be used by Docker.
https_proxy | string | | URL to use for HTTPS_PROXY to be used by Docker.
no_proxy | string | | Comma-separated list of destinations that should be directly accessed, by opposition of going through the proxy defined above. Must be less than 2023 characters long
