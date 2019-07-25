Manual installation
-------------------

0. Make sure that you didn't forget to create the controller with `juju bootstrap` command.

1. Create machines for Contrail, Kubernetes master, Kubernetes workers:

    Configure machines for memory, cores and disk sizes. The following constraints are given for example as minimal requirments.
    ```
    juju add-machine --constraints mem=16G cores=2 root-disk=50G --series=xenial # for all-in-one machine
    ```

2. Deploy Kubernetes services. Here and later the xenial series are used, if you use others you may change it.

    Some of applications may need an additional configuration. You can configure it 
    by using a yaml-formatted file or or by passing options/values directly on the command line

    [Application Configuration](https://docs.jujucharms.com/2.4/en/charms-config)

    You must use the same docker version for Contrail and Kubernetes.

    Deploy ntp, easyrsa, etcd, kubernetes-master, kubernetes-worker:

    ```
    juju deploy cs:xenial/ntp ntp

    juju deploy cs:~containers/easyrsa easyrsa --to lxd:0

    juju deploy cs:~containers/etcd etcd \
        --resource etcd=3 \
        --resource snapshot=0
    juju set etcd channel="3.2/stable"

    juju deploy cs:~containers/kubernetes-master kubernetes-master \
        --resource cdk-addons=0 \
        --resource kube-apiserver=0 \
        --resource kube-controller-manager=0 \
        --resource kube-proxy=0 \
        --resource kube-scheduler=0 \
        --resource kubectl=0
    juju set kubernetes-master channel="1.14/stable" \
        enable-dashboard-addons="false" \
        enable-metrics="false" \
        dns-provider="none" \
        docker_runtime="custom" \
        docker_runtime_repo="deb [arch={ARCH}] https://download.docker.com/linux/ubuntu {CODE} stable" \
        docker_runtime_key_url="https://download.docker.com/linux/ubuntu/gpg" \
        docker_runtime_package="docker-ce"

    juju deploy cs:~containers/kubernetes-worker kubernetes-worker \
        --resource kube-proxy="0" \
        --resource kubectl="0" \
        --resource kubelet="0"
    juju set kubernetes-worker channel="1.14/stable" \
        ingress="false" \
        docker_runtime="custom" \
        docker_runtime_repo="deb [arch={ARCH}] https://download.docker.com/linux/ubuntu {CODE} stable" \
        docker_runtime_key_url="https://download.docker.com/linux/ubuntu/gpg" \
        docker_runtime_package="docker-ce"
    ```

3. Deploy and configure Contrail services.

    Deploy contrail-analyticsdb, contrail-analytics, contrail-controller,
    contrail-kubernets-master, contrail-kubernetes-node, contrail-agent from the directory you have downloaded the charms.

    The "auth-mode" parameter of the contrail-controller charm must be set to “no-auth” if Contrail is deployed without a keystone.

    ```
    juju deploy contrail-analytics contrail-analytics

    juju deploy contrail-analyticsdb contrail-analyticsdb
    juju set contrail-analyticsdb cassandra-minimum-diskgb="4" cassandra-jvm-extra-opts="-Xms1g -Xmx2g"

    juju deploy contrail-controller contrail-controller
    juju set contrail-controller cassandra-minimum-diskgb="4" cassandra-jvm-extra-opts="-Xms1g -Xmx2g" auth-mode="no-auth"

    juju deploy contrail-kubernetes-master contrail-kubernetes-master

    juju deploy contrail-kubernetes-node contrail-kubernetes-node

    juju deploy contrail-agent contrail-agent
    ```

4. Expose applications to be publicly available.

    ```
    juju expose kubernetes-master
    juju expose kubernetes-worker
    ```

    Expose contrail-controller and contrail-analytics if you DO NOT use haproxy.
    ```
    juju expose contrail-controller
    juju expose contrail-analytics
    ```

5. Apply SSL if needed

    To use SSL with contrail services deploy easyrsa service and add the relations to contrail-controller and contrail-agent services.

    ```
    juju add-relation easyrsa contrail-controller
    juju add-relation easyrsa contrail-analytics
    juju add-relation easyrsa contrail-analyticsdb
    juju add-relation easyrsa contrail-kubernetes-master
    juju add-relation easyrsa contrail-agent
    ```

6. Add necessary relations.

    ```
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
    juju add-relation "contrail-agent:juju-info" "kubernetes-worker:juju-info"
    juju add-relation "contrail-kubernetes-master:contrail-kubernetes-config" "contrail-kubernetes-node:contrail-kubernetes-config"
    ```
