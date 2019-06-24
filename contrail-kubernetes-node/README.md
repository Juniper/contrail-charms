Overview
--------

OpenContrail (www.opencontrail.org) is a fully featured Software Defined
Networking (SDN) solution for private clouds. It supports high performance
isolated tenant networks without requiring external hardware support. It
provides a Contrail CNI plugin to integrate with Kubernetes.

This charm is designed to be used in conjunction with the rest of
[the Kubernetes related charms in the charm store](https://jaas.ai/canonical-kubernetes)
to create and configure network interfaces for a kubernetes pods.

This subordinate charm provides connectivity of Contrail to the Kubernetes master and workers components
to create and configure network interfaces.

[The Charmed Distribution Of Kubernetes](https://jaas.ai/canonical-kubernetes) is supported.
Only for Contrail 5.0 for now.
Juju 2.0 is required.

Usage
-----

Kubernetes Master and Kubernetes Worker are prerequisite service to deploy.

Once ready, deploy and relate as follows:

    juju deploy contrail-kubernetes-node
    juju add-relation kubernetes-master contrail-kubernetes-node
    juju add-relation kubernetes-worker contrail-kubernetes-node
    juju add-relation contrail-kubernetes-master contrail-kubernetes-node

External Docker repository
--------------------------

Istead of attaching resource with docker image charm can accept image from remote docker repository.
docker-registry should be specified if the registry is only accessible via http protocol (insecure registry).
docker-user / docker-password can be specified if registry requires authentification.
And image-name / image-tag are the parameters for the image itself.

List of options
---------------

Option   | Type| default | Description
---------|-----|---------|-------------
docker_runtime | string | upstream | Docker runtime to install valid values are "upstream" (Docker PPA), "apt" (Ubuntu archive), "auto" (Ubuntu archive), or "custom" (must have set `docker_runtime_repo` URL, `docker_runtime_key_url` URL and `docker_runtime_package` name).
docker_runtime_key_url | string | | Custom Docker repository validation key URL.
docker_runtime_package | string | | Custom Docker repository package name.
docker_runtime_repo | string | | Custom Docker repository, given in deb format. Use `{ARCH}` to determine architecture at runtime. Use `{CODE}` to set release codename. E.g. `deb [arch={ARCH}] https://download.docker.com/linux/ubuntu {CODE} stable`.
docker-registry | string | opencontrailnightly | URL of docker-registry.
docker-registry-insecure | boolean | false | Is it docker-registry insecure and should docker be configured for it.
docker-user | string | | Login to the docker registry.
docker-password | string | | Password to the docker registry.
image-tag | string | latest | Tag of docker image.
http_proxy | string | | URL to use for HTTP_PROXY to be used by Docker.
https_proxy | string | | URL to use for HTTPS_PROXY to be used by Docker.
no_proxy | string | | Comma-separated list of destinations that should be directly accessed, by opposition of going through the proxy defined above. Must be less than 2023 characters long.
