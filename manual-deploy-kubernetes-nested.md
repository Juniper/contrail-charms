Manual deploy for Contrail with Kubernetes in nested mode
=========================================================

Manual installation
-------------------

1. Prerequisites. Nested deployment is possible only in Contrail+OpenStack cluster. So you need to have:

- deployed Contrail with OpenStack in any way (on baremetal or inside qemu machines). It's not recommended to use public cloud to deploy Contrail with OpenStack - they have very slow nested virtualization that will be used.
- running VM-s in this cloud must have internet connectivity.
- Contrail in underlay must be configured to support nested mode - you need to choose an unused IP in the cluster and configure link-local. Please note that 10.10.10.5 here is the Service IP that was chosen by user. Here is an example:

| LL Service Name | Service IP | Service Port | Fabric IP | Fabric Port |
|--|--|--|--|--|
| K8s-cni-to-agent | 10.10.10.5 | 9091 | 127.0.0.1 | 9091 |

2. Make sure that you didn't forget to create the controller with `juju bootstrap` command. You can use openstack or manual cloud provider.

3. Create machines for Contrail, Kubernetes master, Kubernetes workers:

Configure machines for memory, cores and disk sizes. The following constraints are given for example as minimal requirments.

```bash
juju add-machine --constraints mem=8G cores=2 root-disk=50G --series=xenial # for all-in-one machine
```

Please refer to Juju documentation how to add machines in the cloud that you chose.
Please note that you can use both series - xenial or bionic.

4. Deploy Kubernetes services. Here and later the xenial series is used.

Some of applications may need an additional configuration. You can configure them by using a yaml-formatted file or or by passing options/values directly on the command line

[Application Configuration](https://docs.jujucharms.com/2.4/en/charms-config)

You must use the same docker version for Contrail and Kubernetes.

Deploy ntp, easyrsa, etcd, kubernetes-master, kubernetes-worker:

```bash
juju deploy --series xenial cs:ntp ntp

juju deploy --series xenial cs:~containers/easyrsa --to lxd:0

juju deploy --series xenial cs:~containers/etcd --to:0 --config channel="3.2/stable"

juju deploy --series xenial cs:~containers/kubernetes-master-696 --to:0 \
    --config channel="1.14/stable" \
    --config docker_runtime="custom" \
    --config docker_runtime_repo="deb [arch={ARCH}] https://download.docker.com/linux/ubuntu {CODE} stable" \
    --config docker_runtime_key_url="https://download.docker.com/linux/ubuntu/gpg" \
    --config docker_runtime_package="docker-ce"

juju deploy --series xenial cs:~containers/kubernetes-worker-550 --to:0 \
    --config channel="1.14/stable" \
    --config ingress="false" \
    --config docker_runtime="custom" \
    --config docker_runtime_repo="deb [arch={ARCH}] https://download.docker.com/linux/ubuntu {CODE} stable" \
    --config docker_runtime_key_url="https://download.docker.com/linux/ubuntu/gpg" \
    --config docker_runtime_package="docker-ce"
```

5. Deploy and configure Contrail services.

Deploy contrail-kubernets-master, contrail-kubernetes-node, contrail-agent from the charm store (you can use local source code if you have it downloaded).

Main thing in this deployment is a config of underlay that must be passed to contrail-kubernetes-master. For manual deploy it's simpler to create config file and pass it to deploy cmd. Here is an example of config:

```yaml
contrail-kubernetes-master:
    nested_mode: true
    cluster_project: "{'domain':'default-domain','project':'admin'}"
    cluster_network: "{'domain':'default-domain','project':'admin','name':'juju-net'}"
    service_subnets: '10.96.0.0/12'
    nested_mode_config: |
        {
        "CONTROLLER_NODES": "10.0.12.20",
        "AUTH_MODE": "keystone",
        "KEYSTONE_AUTH_ADMIN_TENANT": "admin",
        "KEYSTONE_AUTH_ADMIN_USER": "admin",
        "KEYSTONE_AUTH_ADMIN_PASSWORD": "password",
        "KEYSTONE_AUTH_URL_VERSION": "/v2.0",
        "KEYSTONE_AUTH_HOST": "10.0.12.122",
        "KEYSTONE_AUTH_PROTO": "http",
        "KEYSTONE_AUTH_PUBLIC_PORT":"5000",
        "KEYSTONE_AUTH_REGION_NAME": "RegionOne",
        "KEYSTONE_AUTH_INSECURE": "True",
        "KUBERNESTES_NESTED_VROUTER_VIP": "10.10.10.5"
        }
```

```bash
juju deploy --series xenial cs:~juniper-os-software/contrail-kubernetes-master \
    --config ./path-to-config.yaml

juju deploy --series xenial cs:~juniper-os-software/contrail-kubernetes-node
```

6. Add necessary relations.

```bash
juju add-relation "kubernetes-master:juju-info" "ntp:juju-info"
juju add-relation "kubernetes-worker:juju-info" "ntp:juju-info"

juju add-relation "kubernetes-master:kube-api-endpoint" "kubernetes-worker:kube-api-endpoint"
juju add-relation "kubernetes-master:kube-control" "kubernetes-worker:kube-control"
juju add-relation "kubernetes-master:certificates" "easyrsa:client"
juju add-relation "kubernetes-master:etcd" "etcd:db"
juju add-relation "kubernetes-worker:certificates" "easyrsa:client"
juju add-relation "etcd:certificates" "easyrsa:client"

juju add-relation "contrail-kubernetes-node:cni" "kubernetes-master:cni"
juju add-relation "contrail-kubernetes-node:cni" "kubernetes-worker:cni"
juju add-relation "contrail-kubernetes-master:kube-api-endpoint" "kubernetes-master:kube-api-endpoint"
juju add-relation "contrail-kubernetes-master:contrail-kubernetes-config" "contrail-kubernetes-node:contrail-kubernetes-config"
```

7. Apply SSL if needed

If Contrail in underlay cluster has SSL enabled then you need to provide same certificates to contrail-kubernetes-master.
