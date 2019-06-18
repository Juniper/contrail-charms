Overview
--------

OpenContrail (www.opencontrail.org) is a fully featured Software Defined
Networking (SDN) solution for private clouds. It supports high performance
isolated tenant networks without requiring external hardware support. It
provides a Neutron plugin to integrate with OpenStack.

This charm provides the analytics node component which includes
contrail-collector, contrail-query-engine and contrail-analytics-api services.

Only OpenStack Mitaka or newer is supported.
Only for Contrail 4.0 for now.
Juju 2.0 is required.

Usage
-----

Contrail Controller and Contrail AnalyticsDB are prerequisite services to deploy.
Once ready, deploy and relate as follows:

    juju deploy contrail-analytics
    juju add-relation contrail-analytics contrail-analyticsdb
    juju add-relation contrail-analytics contrail-controller

Resource
--------

The charm requires docker image with Contrail Analytics as a resource.
It can be provided as usual for Juju 2.0 in deploy command or
through attach-resource:

    juju attach contrail-analytics contrail-analytics="$PATH_TO_IMAGE"

External Docker repository
--------------------------

Istead of attaching resource with docker image charm can accept image from remote docker repository.
docker-registry should be specified if the registry is only accessible via http protocol (insecure registry).
docker-user / docker-password can be specified if registry requires authentification.
And image-name / image-tag are the parameters for the image itself.

High Availability (HA)
----------------------

Multiple units of this charm can be deployed to support HA deployments:

    juju add-unit contrail-analytics

Relating to haproxy charm (http-services relation) allows multiple units to be
load balanced:

    juju add-relation contrail-analytics haproxy

For this http connection there are two modes - http and https. Both modes configure haproxy in http mode (termination). Mode https additionaly configure haproxy to use SSL for frontend. By default http mode is used. To confugire haproxy in https mode you can run:

    juju config contrail-analytics haproxy-http-mode=https

List of options
---------------

Option   | Type| default | Description
---------|-----|---------|-------------
control-network | string | | The IP address and netmask of the control network (e.g. 192.168.0.0/24). This network will be used for Contrail endpoints. If not specified, default network will be used.
docker-registry | string | | URL of docker-registry. Should be passed only if registry is not secured and must be added to docker config to allow work with it.
docker-registry-insecure | boolean | false | Is it docker-registry insecure and should docker be configured for it
docker-user | string | | Login to the docker registry.
docker-password | string | | Password to the docker registry.
image-tag | string | | Tag of docker image.
log-level | string | SYS_NOTICE | Log level for contrail services. Valid values are: SYS_EMERG, SYS_ALERT, SYS_CRIT, SYS_ERR, SYS_WARN, SYS_NOTICE, SYS_INFO, SYS_DEBUG
http_proxy | string | | URL to use for HTTP_PROXY to be used by Docker.
https_proxy | string | | URL to use for HTTPS_PROXY to be used by Docker.
no_proxy | string | | Comma-separated list of destinations that should be directly accessed, by opposition of going through the proxy defined above. Must be less than 2023 characters long
haproxy-http-mode | string | http | Mode for haproxy for http connections - http or https
