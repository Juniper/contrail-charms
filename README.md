# contrail-charms
Juju charms for Contrail services.

Overview
--------

Please note that master branch contains code for Contrail R4.x. For R5.x code please look into R5 branch https://github.com/Juniper/contrail-charms/tree/R5

Contrail 4.0 would provide support for Docker containers. The existing contrail components, which run as services on a BMS or VM, would be running within a Docker container in contrail 4.0.
This document describes how to deploy contrail 4.0 Docker containers, which would be running the several contrail service components using contrail-charms

[Contrail-charms specs](specs/contrail-charms.md)

Deploying Contrail charms
-------------------------

1. Install cloud and juju on the dedicated machine from where the deploy is started:
```
    sudo apt-get update
    sudo apt-get upgrade
    sudo apt-get install juju
```
[Installing juju](https://docs.jujucharms.com/2.4/en/getting-started)

2. Configure juju:
```
juju add-cloud <cloud-name>
juju add-credential <cloud name>
```

You can see possible clouds that you can use with `juju clouds` command.
```
$ juju clouds
Cloud        Regions  Default          Type        Description
aws               15  us-east-1        ec2         Amazon Web Services
aws-china          1  cn-north-1       ec2         Amazon China
aws-gov            1  us-gov-west-1    ec2         Amazon (USA Government)
azure             26  centralus        azure       Microsoft Azure
azure-china        2  chinaeast        azure       Microsoft Azure China
cloudsigma         5  hnl              cloudsigma  CloudSigma Cloud
google            13  us-east1         gce         Google Cloud Platform
joyent             6  eu-ams-1         joyent      Joyent Cloud
oracle             5  uscom-central-1  oracle      Oracle Cloud
rackspace          6  dfw              rackspace   Rackspace Cloud
localhost          1  localhost        lxd         LXD Container Hypervisor
```

You can add private or custom clouds for the following provider types:
```
$ juju add-cloud
Cloud Types
  maas
  manual
  openstack
  oracle
  vsphere
```

As an example for maas:
```
juju add-cloud mymaas       #select cloud type: maas, enter the API endpoint url)
juju add-credential mymaas  #add credentials
```

[Using MAAS with Juju](https://docs.jujucharms.com/2.4/en/clouds-maas)

As an example for amazon:
```
juju add-credential aws   #add credentials
```

[Using Amazon with Juju](https://docs.jujucharms.com/2.4/en/help-aws)

3. Create controller:
```
juju bootstrap --bootstrap-series=xenial <cloud name> <controller name>
```
[Bootstrapping controller](https://docs.jujucharms.com/2.4/en/controllers-creating)

4. Download charms:
```
git clone https://github.com/Juniper/contrail-charms
```

5. Deploy Contrail:

  You can deploy charms in bundle or manually.

  [Charm bundles documentation](https://docs.jujucharms.com/2.4/en/charms-bundles)

- With bundle:
    - Example bundles can be found [here](./examples)
    - Create or modify the Juju deployment bundle yaml file to point to machines in which the contrail-charms should be deployed and to include options you need.
    - Deploy the bundle using the command `juju deploy <bundle_yaml_file>`
    - [Example of bundle.yaml file for deployment of OpenStack and Contrail in Amazon environment.](./examples/contrail-docker-bundle-ha.yaml)

- Manually

    [How to deploy Contail with OpenStack](./manual-deploy.md)

    [Using the Manual cloud with Juju](https://docs.jujucharms.com/2.4/en/clouds-manual)

6. You can check the status of your deployment using `juju status` command.
[Unit status](https://docs.jujucharms.com/2.4/en/reference-status)

Configuration
-------------

- ## Contrail-agent
    [Contrail-agent specs](contrail-agent/README.md)

- ## Contrail-analytics
    [Contrail-analytics specs](contrail-analytics/README.md)

- ## Contrail-analyticsdb
    [Contrail-analyticsdb specs](contrail-analyticsdb/README.md)

- ## Contrail-controller
    [Contrail-controller specs](contrail-controller/README.md)

- ## Contrail-keystone-auth
    [Contrail-keystone specs](contrail-keystone/README.md)

- ## Contrail-openstack
    [Contrail-openstack specs](contrail-openstack/README.md)
