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
