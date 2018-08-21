# contrail-charms
Juju charms for Contrail services.

# Overview
Contrail 4.0 would provide support for Docker containers. The existing contrail components, which run as services on a BMS or VM, would be running within a Docker container in contrail 4.0.
This document describes how to deploy contrail 4.0 Docker containers, which would be running the several contrail service components using contrail-charms

[Contrail-charms specs](specs/contrail-charms.md)

# Usage

To deploy as a bundle:

1. Create or modify the Juju deployment bundle yaml file to point to machines in which the contrail-charms should be deployed and to include options you need.
2. Specify the contrail docker container image that you want to deployed using charms in the bundle yaml file
3. Deploy the bundle using the command 'juju deploy <bundle_yaml_file>'.

# Configuration
- ## Contrail-agent
    [Contrail-agent specs](contrail-agent/README.md)
    ### List of options:
    Option   | Type| default | Description
    ---------|-----|---------|-------------
    install-sources | string | | Package sources for install
    install-keys | string |  | Apt keys for package install sources
    physical-interface | string | | Specify the interface to install vhost0 on. If left empty, vhost0 will be installed on the default gateway interface.
    vhost-gateway | string | auto | Specify the gateway for vhost0, either an IPv4 address or keyword 'auto'. 'auto' will set gateway automatically based on host's existing routes.
    remove-juju-bridge | boolean | true | Juju on MAAS creates bridges for deploying LXD/LXC and KVM workloads. Enable this to remove such a bridge if you want to install vhost0 directly on the underlying interface.
    dpdk | boolean | false | Use user space DPDK vRouter
    dpdk-driver | string | uio_pci_generic | DPDK driver to use for physical interface. Interface can be specified using vhost-interface.
    dpdk-hugepages | string | 70% | Number of huge pages to reserve for use with DPDK vRouter and OpenStack instances. Value can be specified as percentage of system memory e.g. 70% or as number of huge pages e.g. 1434.
    dpdk-coremask | string | 1 | vRouter CPU affinity mask. Determines on which CPUs DPDK vRouter will run. Value can be specified as either a hexidecimal bitmask e.g. 0xF or as a numbered list separated by commas e.g. 0,1 (ranges are also supported using '-' e.g. 0-2). It must specify only real cores cause contrail-vrouter-dpdk service will  | string | | Main packet pool size.
    dpdk-pmd-txd-size | string | | DPDK PMD Tx Descriptor size.
    dpdk-pmd-rxd-size | string | | DPDK PMD Rx Descriptor size.
    vhost-mtu | string | | MTU for vhost0 interface
    log-level | string | SYS_NOTICE | Log level for contrail services. Valid values are: SYS_EMERG, SYS_ALERT, SYS_CRIT, SYS_ERR, SYS_WARN, SYS_NOTICE, SYS_INFO, SYS_DEBUG

- ## Contrail-analytics
    [Contrail-analytics specs](contrail-analytics/README.md)
    ### List of options:
    Option   | Type| default | Description
    ---------|-----|---------|-------------
    control-network | string | | The IP address and netmask of the control network (e.g. 192.168.0.0/24). This network will be used for Contrail endpoints. If not specified, default network will be used.
    docker-registry | string | | URL of docker-registry. Should be passed only if registry is not secured and must be added to docker config to allow work with it.
    docker-user | string | | Login to the docker registry.
    docker-password | string | | Password to the docker registry.
    image-name | string | | Full docker's image name.
    image-tag | string | | Tag of docker image.
    log-level | string | SYS_NOTICE | Log level for contrail services. Valid values are: SYS_EMERG, SYS_ALERT, SYS_CRIT, SYS_ERR, SYS_WARN, SYS_NOTICE, SYS_INFO, SYS_DEBUG

- ## Contrail-analyticsdb
    [Contrail-analyticsdb specs](contrail-analyticsdb/README.md)
    ### List of options:
    Option   | Type| default | Description
    ---------|-----|---------|-------------
    control-network | string | | The IP address and netmask of the control network (e.g. 192.168.0.0/24). This network will be used for Contrail endpoints. If not specified, default network will be used.
    cassandra-minimum-diskgb | string | 256 | Contrail has this as parameter and checks it at startup. If disk is smaller then status of DB is not good.
    docker-registry | string | | URL of docker-registry. Should be passed only if registry is not secured and must be added to docker config to allow work with it.
    docker-user | string | | Login to the docker registry.
    docker-password | string | | Password to the docker registry.
    image-name | string | | Full docker's image name.
    image-tag | string | | Tag of docker image.
    log-level | string | SYS_NOTICE | Log level for contrail services. Valid values are: SYS_EMERG, SYS_ALERT, SYS_CRIT, SYS_ERR, SYS_WARN, SYS_NOTICE, SYS_INFO, SYS_DEBUG

- ## Contrail-controller
    [Contrail-controller specs](contrail-controller/README.md)
    ### List of options:
    Option   | Type| default | Description
    ---------|-----|---------|-------------
    control-network | string | | The IP address and netmask of the control network (e.g. 192.168.0.0/24). This network will be used for Contrail endpoints. If not specified, default network will be used.
    cassandra-minimum-diskgb | string | 20 | Contrail has this as parameter and checks it at startup. If disk is smaller then status of DB is not good.
    auth-mode | string | rbac | It represents 'aaa_mode' configuration key of Contrail. Can be one of: 'rbac', 'cloud-admin' or 'no-auth' Authentication mode. Detailed information can be found in the Contrail documentation. https://github.com/Juniper/contrail-controller/wiki/RBAC In case of 'rbac' charm will configure Contrail to RBAC mode and administrator must configure RBAC rules to allow users to work. In case of 'cloud-admin' charm will configure Contrail in compatible mode.
    cloud-admin-role | string | admin | Role name in keystone for users that have full access to everything.
    global-read-only-role | string | | Role name in keystone for users that have read-only access to everything.
    vip | string | | Contrail API VIP to be used for configuring client-side software like neutron plugin. (to be set up also in KeepAlived charm configuration if it’s used for HA) Private IP of the first Contrail API unit will be used if not set.
    use-external-rabbitmq | boolean | false | Charm will wait for external AMQP relation if set. Charm will use internal RabbitMQ server if not set. **NOTE: Changing this flag after deployment is dangerous!**
    flow-export-rate | string | 0 | Defines how much flow records will be exported by vRouter agent to the Contrail Collector when a flow is created or deleted.
    docker-registry | string | | URL of docker-registry. Should be passed only if registry is not secured and must be added to docker config to allow work with it.
    docker-user | string | | Login to the docker registry.
    docker-password | string | | Password to the docker registry.
    image-name | string | | Full docker's image name.
    image-tag | string | | Tag of docker image.
    log-level | string | SYS_NOTICE | Log level for contrail services. Valid values are: SYS_EMERG, SYS_ALERT, SYS_CRIT, SYS_ERR, SYS_WARN, SYS_NOTICE, SYS_INFO, SYS_DEBUG

- ## Contrail-keystone-auth
    [Contrail-keystone specs](contrail-keystone/README.md)
    ### List of options:
    Option   | Type| default | Description
    ---------|-----|---------|-------------
    ssl_ca | string | | base64-encoded SSL CA to use with the certificate and key provided  to keystone - this is only required if you are providing a privately signed ssl_cert and ssl_key. This certificate will be provided to Contrail's keystone clients.

- ## Contrail-openstack
    [Contrail-openstack specs](contrail-openstack/README.md)
    ### List of options:
    Option   | Type| default | Description
    ---------|-----|---------|-------------
    install-sources | string | | Package sources for install
    install-keys | string |  | Apt keys for package install sources
    enable-metadata-server | boolean | true | Configures metadata shared secret and tells nova to run a local instance of nova-api-metadata for serving metadata to VMs.
    use-internal-endpoints | boolean | False | Openstack mostly defaults to using public endpoints for internal communication between services. If set to True this option will configure services to use internal endpoints where possible.
