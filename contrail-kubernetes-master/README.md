Overview
--------

OpenContrail (www.opencontrail.org) is a fully featured Software Defined
Networking (SDN) solution for private clouds. It supports high performance
isolated tenant networks without requiring external hardware support. It
provides a Contrail CNI plugin to integrate with Kubernetes.

This charm is designed to be used in conjunction with the rest of
[the Kubernetes related charms in the charm store](https://jaas.ai/canonical-kubernetes)
to create and configure network interfaces for a kubernetes pods.

This charm provides connectivity of Contrail to the Kubernetes Master charm to obtain a Kubernetes API configuration.

[The Charmed Distribution Of Kubernetes](https://jaas.ai/canonical-kubernetes) is supported.
Only for Contrail 5.0 for now.
Juju 2.0 is required.

Usage
-----

Contrail Controller and Kubernetes Master are prerequisite service to deploy.

Once ready, deploy and relate as follows:

    juju deploy contrail-kubernetes-master
    juju add-relation contrail-controller contrail-kubernetes-master
    juju add-relation kubernetes-master contrail-kubernetes-master

Nested mode installation
------------------------

[Example of bundle.yaml file](../examples/contrail-bundle-k8s-nested-mode.yaml) to install charm in nested mode.

Prerequisite:

- Virtual machines in an Openstack cluster must be created with connectivity to the Internet and a underlay network with Contrail components.
- The link-local services for vRouter Agent should be created in Contrail (Service IP: 10.10.10.5, Service Port: 9091, Fabric IP: 127.0.0.1, Fabric Port: 9091). Note: Here 10.10.10.5 is the Service IP that was chosen by user. This can be any unused IP in the cluster.

Notes:

- The Project name and the network name of charm config should be the same as Openstack project name and Openstack network name (parameters cluster_project and cluster_network)
- The service_subnets config variable is same as the service-cidr kubererntes-master config variable
- KUBERNESTES_NESTED_VROUTER_VIP in the nested_mode_config variable is same as Service IP of link-local services
- It is not recommended to deploy charm in nested-mode in the AWS cloud since AWS uses slow qemu virtualization

External Docker repository
--------------------------

Istead of attaching resource with docker image charm can accept image from remote docker repository.
docker-registry should be specified if the registry is only accessible via http protocol (insecure registry).
docker-user / docker-password can be specified if registry requires authentification.
And image-name / image-tag are the parameters for the image itself.

SSL
---

This charm supports relation to easyrsa charm to obtain certificates for XMPP and Sandesh connections:

    juju add-relation contrail-kubernetes-master easyrsa

Please note that in this case all charms must be related to easyrsa. Components require CA certificate for communication.
