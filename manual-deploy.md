Manual installation
-------------------

0. Make sure that you didn't forget to create the controller with `juju bootstrap` command.

1. Create machines for openstack, compute and contrail:

    Configure machines for memory, cores and disk sizes. The following constraints are given for example as minimal requirments.
    ```
    juju add-machine --constraints mem=8G cores=2 root-disk=40G --series=xenial   #for openstack machine(s) 0
    juju add-machine --constraints mem=7G cores=4 root-disk=40G --series=xenial   #for compute machine(s) 1,(3)
    juju add-machine --constraints mem=15G cores=2 root-disk=300G --series=xenial #for contrail  machine 2
    ```

2. Deploy openstack services. Here and later the xenial series are used, if you use others you may change it.

    Some of applications may need an additional configuration. You can configure it 
    - by using a yaml-formatted file

        An example of `nova-compute-config.yaml`:
        ```
        nova-compute:
            openstack-origin: cloud:xenial-ocata
            virt-type: qemu 
            enable-resize: True
            enable-live-migration: True
            migration-auth-type: ssh
        ```
        To deploy:
        ```
        juju deploy cs:xenial/nova-compute --config ./nova-compute-config.yaml
        ```

    - or by passing options/values directly on the command line
        ```
        juju deploy cs:xenial/nova-cloud-controller --config console-access-protocol=novnc --config openstack-origin=cloud:xenial-ocata
        ```

    - You also use the combination of the above.

        [Application Configuration](https://docs.jujucharms.com/2.4/en/charms-config)

    Deploy ntp, rabbitmq-server, percona-cluster, openstack-dashboard, nova-cloud-controller, glance, keystone, neutron to OpenStack machines.

    **NOTE: OpenStack services should be set on different machines or on different containers to prevent haproxy conflicts from applications.** You should point machine or container to which you want to deploy the application by `--to <machine number>` option.
    ```
    juju deploy cs:xenial/ntp
    juju deploy cs:xenial/rabbitmq-server --to lxd:0
    juju deploy cs:xenial/percona-cluster mysql --config root-password=<root-password> --config max-connections=1500 --to lxd:0
    juju deploy cs:xenial/openstack-dashboard --config openstack-origin=cloud:xenial-ocata --to lxd:0
    juju deploy cs:xenial/nova-cloud-controller --config console-access-protocol=novnc --config openstack-origin=cloud:xenial-ocata --config network-manager=Neutron --to lxd:0
    juju deploy cs:xenial/neutron-api --config manage-neutron-plugin-legacy-mode=false --config openstack-origin=cloud:xenial-ocata --config neutron-security-groups=true --to lxd:0
    juju deploy cs:xenial/glance --config openstack-origin=cloud:xenial-ocata --to lxd:0
    juju deploy cs:xenial/keystone --config admin-password=<admin-password> --config admin-role=admin --config openstack-origin=cloud:xenial-ocata --to lxd:0
    ```

3.  Deploy and configure nova-compute.

    Deploy nova-compute to compute machine or machines.
    ```
    juju deploy cs:xenial/nova-compute --config ./nova-compute-config.yaml --to 1
    ```

    If you need additional computes you can  add them by
    ```
    juju add-unit nova-compute --to 3 # Add one more unit
    ```

4. Deploy and configure Contrail services.

    Deploy contrail-keystone-auth, contrail-controller, contrail-analyticsdb, contrail-analytics, contrail-openstack, contrail-agent from the directory you have downloaded the charms.
    ```
    juju deploy --series=xenial $CHARMS_DIRECTORY/contrail-charms/contrail-keystone-auth --to 2
    juju deploy --series=xenial $CHARMS_DIRECTORY/contrail-charms/contrail-controller --config auth-mode=rbac --config cassandra-minimum-diskgb=4 --config cassandra-jvm-extra-opts="-Xms1g -Xmx2g" --to 2
    juju deploy --series=xenial $CHARMS_DIRECTORY/contrail-charms/contrail-analyticsdb cassandra-minimum-diskgb=4 --config cassandra-jvm-extra-opts="-Xms1g -Xmx2g" --to 2
    juju deploy --series=xenial $CHARMS_DIRECTORY/contrail-charms/contrail-analytics --to 2
    juju deploy --series=xenial $CHARMS_DIRECTORY/contrail-charms/contrail-openstack
    juju deploy --series=xenial $CHARMS_DIRECTORY/contrail-charms/contrail-agent
    ```

5. Expose applications to be publicly available.
    ```
    juju expose openstack-dashboard
    juju expose nova-cloud-controller
    juju expose neutron-api
    juju expose glance
    juju expose keystone
    ```

    Expose contrail-controller and contrail-analytics if you DO NOT use haproxy.
    ```
    juju expose contrail-controller
    juju expose contrail-analytics
    ```

6. Apply SSL if needed

    To use SSL with contrail services deploy easyrsa service and add the relations to contrail-controller and contrail-agent services.

    ```
    juju deploy cs:~containers/xenial/easyrsa --to 0
    juju add-relation easyrsa contrail-controller
    juju add-relation easyrsa contrail-analytics
    juju add-relation easyrsa contrail-analyticsdb
    juju add-relation easyrsa contrail-agent
    ```

7. HA configuration (optional).

    If you are using several controllers and want to expose just one IP(VIP) for config API or analytics API to client then we suggest the following HA solution using haproxy and keepalived.

    Deploy haproxy and keepalived services. Haproxy is deployed on the machines with contrail-controllers.
    Keepalived is a subordinate charm to haproxy and does not require `to` option.
    Haproxy charm must have peering_mode set to active-active. In active-passive mode it creates additional listeners on the same ports as other Contrail services and system doesn't work due to port conflicts.
    ```
    juju deploy cs:xenial/haproxy --to <first contrail-controller machine> --config peering_mode=active-active
    juju add-unit haproxy --to <another contrail-controller machine>
    juju deploy cs:~containers/keepalived --config virtual_ip=<vip>
    ```

    Expose haproxy to be available. Do not expose contrail-controller and contrail-analytics in this case.
    ```
    juju expose haproxy
    ```

    Add necessary relations.
    ```
    juju add-relation haproxy:juju-info keepalived:juju-info
    juju add-relation contrail-analytics:http-services haproxy
    juju add-relation contrail-controller:http-services haproxy
    juju add-relation contrail-controller:https-services haproxy
    ```

    Configure contrail-controller with vip.
    ```
    juju set contrail-controller vip=<vip>
    ```

8. Add necessary relations.

    ```
    juju add-relation keystone:shared-db mysql:shared-db
    juju add-relation glance:shared-db mysql:shared-db
    juju add-relation keystone:identity-service glance:identity-service
    juju add-relation nova-cloud-controller:image-service glance:image-service
    juju add-relation nova-cloud-controller:identity-service keystone:identity-service
    juju add-relation nova-cloud-controller:cloud-compute nova-compute:cloud-compute
    juju add-relation nova-compute:image-service glance:image-service
    juju add-relation nova-compute:amqp rabbitmq-server:amqp
    juju add-relation nova-cloud-controller:shared-db mysql:shared-db
    juju add-relation nova-cloud-controller:amqp rabbitmq-server:amqp
    juju add-relation openstack-dashboard:identity-service keystone

    juju add-relation neutron-api:shared-db mysql:shared-db
    juju add-relation neutron-api:neutron-api nova-cloud-controller:neutron-api
    juju add-relation neutron-api:identity-service keystone:identity-service
    juju add-relation neutron-api:amqp rabbitmq-server:amqp

    juju add-relation contrail-controller ntp
    juju add-relation nova-compute:juju info ntp:juju-info

    juju add-relation contrail-controller contrail-keystone-auth
    juju add-relation contrail-keystone-auth keystone
    juju add-relation contrail-controller contrail-analytics
    juju add-relation contrail-controller contrail-analyticsdb
    juju add-relation contrail-analytics contrail-analyticsdb

    juju add-relation contrail-openstack neutron-api
    juju add-relation contrail-openstack nova-compute
    juju add-relation contrail-openstack contrail-controller

    juju add-relation contrail-agent:juju info nova-compute:juju-info
    juju add-relation contrail-agent contrail-controller
    ```
