Manual deploy for Contrail with Kubernetes
==========================================

Manual installation
-------------------

1. Make sure that you didn't forget to create the controller with `juju bootstrap` command. You can use any cloud provide that you want.

2. Create machines for Contrail, Kubernetes master, Kubernetes workers:

Configure machines for memory, cores and disk sizes. The following constraints are given for example as minimal requirments.

```bash
juju add-machine --constraints mem=32G cores=8 root-disk=150G --series=xenial # for all-in-one machine
```

Please note that you can use both series - xenial or bionic.

3. Deploy Kubernetes services. Here and later the xenial series is used.

Some of applications may need an additional configuration. You can configure it by using a yaml-formatted file or or by passing options/values directly on the command line

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
    --config docker_runtime="custom" \
    --config docker_runtime_repo="deb [arch={ARCH}] https://download.docker.com/linux/ubuntu {CODE} stable" \
    --config docker_runtime_key_url="https://download.docker.com/linux/ubuntu/gpg" \
    --config docker_runtime_package="docker-ce"
```

4. Deploy and configure Contrail services.

Deploy contrail-analyticsdb, contrail-analytics, contrail-controller, contrail-kubernets-master, contrail-kubernetes-node, contrail-agent from the charm store (you can use local source code if you have it downloaded).

The "auth-mode" parameter of the contrail-controller charm must be set to “no-auth” if Contrail is deployed without a keystone (without OpenStack).

```bash
juju deploy --series xenial cs:~juniper-os-software/contrail-controller --to:0 \
    --config cassandra-minimum-diskgb="4" --config cassandra-jvm-extra-opts="-Xms1g -Xmx2g" --config auth-mode="no-auth"

juju deploy --series xenial cs:~juniper-os-software/contrail-analyticsdb --to:0 \
    --config cassandra-minimum-diskgb="4" --config cassandra-jvm-extra-opts="-Xms1g -Xmx2g"

juju deploy --series xenial cs:~juniper-os-software/contrail-analytics --to:0

juju deploy --series xenial cs:~juniper-os-software/contrail-kubernetes-master

juju deploy --series xenial cs:~juniper-os-software/contrail-kubernetes-node

juju deploy --series xenial cs:~juniper-os-software/contrail-agent contrail-agent
```

5. Add necessary relations.

```bash
juju add-relation "contrail-controller" "contrail-analytics"
juju add-relation "contrail-controller" "contrail-analyticsdb"
juju add-relation "contrail-analytics" "contrail-analyticsdb"
juju add-relation "contrail-agent" "contrail-controller"
juju add-relation "contrail-controller" "ntp"

juju add-relation "kubernetes-master:kube-api-endpoint" "kubernetes-worker:kube-api-endpoint"
juju add-relation "kubernetes-master:kube-control" "kubernetes-worker:kube-control"
juju add-relation "kubernetes-master:certificates" "easyrsa:client"
juju add-relation "kubernetes-master:etcd" "etcd:db"
juju add-relation "kubernetes-worker:certificates" "easyrsa:client"
juju add-relation "etcd:certificates" "easyrsa:client"

juju add-relation "contrail-kubernetes-node:cni" "kubernetes-master:cni"
juju add-relation "contrail-kubernetes-node:cni" "kubernetes-worker:cni"
juju add-relation "contrail-kubernetes-master:contrail-controller" "contrail-controller:contrail-controller"
juju add-relation "contrail-kubernetes-master:kube-api-endpoint" "kubernetes-master:kube-api-endpoint"
juju add-relation "contrail-agent:juju-info" "kubernetes-master:juju-info"
juju add-relation "contrail-agent:juju-info" "kubernetes-worker:juju-info"
juju add-relation "contrail-kubernetes-master:contrail-kubernetes-config" "contrail-kubernetes-node:contrail-kubernetes-config"
```

6. Expose applications to be publicly available.

Expose contrail-controller and contrail-analytics if you DO NOT use haproxy and want to access them outside.

```bash
juju expose contrail-controller
juju expose contrail-analytics
```

7. Apply SSL if needed

To use SSL with contrail services deploy easyrsa service and add the relations to contrail-controller and contrail-agent services.

```bash
juju add-relation easyrsa contrail-controller
juju add-relation easyrsa contrail-analytics
juju add-relation easyrsa contrail-analyticsdb
juju add-relation easyrsa contrail-kubernetes-master
juju add-relation easyrsa contrail-agent
```
