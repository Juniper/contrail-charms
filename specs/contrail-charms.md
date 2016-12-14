
#1. Introduction
Contrail 4.0 would provide support for Docker containers. The existing contrail components, which run as services on a BMS or VM, would be running within a Docker container in contrail 4.0. 
This document describes how to deploy contrail 4.0 Docker containers, which would be running the several contrail service components using contrail-charms

#2. Problem statement
The rationale behind the decision to containerize the contrail subsystems can be found [here]( https://github.com/Juniper/contrail-docker/blob/master/specs/contrail-docker.md). Contrail-charms 3.x or earlier provides functionality to provision each contrail component in separate lxd containers. With contrail 4.0, the contrail services would be contained in Docker containers. This necessitates change in contrail-charms to support the new mode of contrail deployment and support the deployment of the contrail docker images

#3. Proposed solution
Contrail Docker containers will be built to include all the packages needed to run the processes within the container. Also included in the containers will be Ansible playbooks to create the configuration files and provision the services within the container. Any provisioning tool to deploy these containers, including contrail-charm, will need to perform 2 simple steps:

1.   Create a configuration file containing parameter values, one config file per container.
2.   Deploy the container.

When deployed the container will pick the configuration parameters and execute ansible scripts within the container to provision and bring up processes within the container.
##3.1 Alternatives considered
####Describe pros and cons of alternatives considered.

##3.2 API schema changes
####Describe api schema changes and impact to the REST APIs.

##3.3 User workflow impact
As a pre-requisite to installing the charm software the user will have to do the following:

1. Set up the MAAS and Juju environment as mentioned in the document https://docs.google.com/document/d/1imrCiYCsfNmo4fOlTbnxbTQaym1tG6FdfO7nljMCQzM/edit
2. Download the Contrail container docker images into the juju-api-client container that was setup in step 1.

On the above prerequisite steps are done the user will have to do the following:

1. Modify the Juju deployment bundle yaml file to point to machines in which the contrail-charms should be deployed (sample given in Appendex A)
2. Specify the contrail docker container image that you want to deployed using charms in the bundle yaml file
3. Deploy the bundle using the command 'juju deploy <bundle_yaml_file>'.

##3.4 UI changes
####Describe any UI changes

##3.5 Notification impact
####Describe any log, UVE, alarm changes


#4. Implementation
Once the contrail-charms have been deployed the user can check the status of the deployment using the 'juju status' command.
Orchestrator:

Juju is the orechestration tool that will be used for deploying the charms.

There will be one charm per contrail docker container image

The 'docker.io' package will be installed as part of the 'install' hook

The docker container images will be stored in the Juju Controller repository as a centrail placeholder uisng the Juju resources feature. The charms will get the resource from the controller and then load and run it. The docker containers will be load and run using the native 'docker load' and 'docker run' command in that machine.

Once the charm is installed all the relations specified in the bundle yaml file will be added and the corresponding hooks excuted. The configurations that is generated in the relation hooks will be written into the corresponding configuration file under '/etc/contrailctl'

The user can supply the configufing using an yaml file and apply the configuration using the command 'juju config <application_name> --file <input_yaml_file>'

Any changes in the configuraion file will be applied to the container by firing the corresponding 'contrailctl config sync' command 


#5. Performance and scaling impact
##5.1 API and control plane
####Scaling and performance for API and control plane

##5.2 Forwarding performance
####Scaling and performance for API and forwarding

#6. Upgrade
####Describe upgrade impact of the feature
####Schema migration/transition

#7. Deprecations
####If this feature deprecates any older feature or API then list it here.

#8. Dependencies
####Describe dependent features or components.

#9. Testing
1. Setup the lab environment as described in the Lab solutions guide link given above

2. Deploy the charms using the bundle yaml file

3. Apply configuration to the charms using the 'juju config' command

#10. Documentation Impact

#11. References

#12. Appendix A (contrail-docker-bundle.yaml)

series: trusty
services:
  contrail-analytics:
    charm: /home/ubuntu/contrail-analytics
    num_units: 3
    to: [ "1", "2", "3" ]
    
  contrail-analyticsdb:
    charm: /home/ubuntu/contrail-analyticsdb
    num_units: 3
    to: [ "1", "2", "3" ]
    
  contrail-control:
    charm: /home/ubuntu/contrail-controller
    num_units: 3
    to: [ "1", "2", "3" ]
    
  contrail-agent:
    charm: /home/ubuntu/contrail-agent
    num_units: 1
    to:
      - '4'
      
   contrail-lb:
    charm: /home/ubuntu/contrail-lb
    num_units: 1
    to:
      - '5'

relations:
  - [ "contrail-control", "contrail-lb:contrail-control" ]
  - [ "contrail-analytics", "contrail-lb:contrail-analytics" ]
  
machines:

  "1":
    series: trusty
    #constraints: mem=15G root-disk=40G
    constraints: tags=contrail-controller-vm-1
    
  "2":
    series: trusty
    #constraints: mem=15G root-disk=40G
    constraints: tags=contrail-controller-vm-2
    
  "3":
    series: trusty
    #constraints: mem=15G root-disk=40G
    constraints: tags=contrail-controller-vm-3
    
  "4":
    series: trusty
    #constraints: mem=4G root-disk=20G
    constraints: tags=compute-storage-1
    
  "5":
    series: trusty
    #constraints: mem=4G root-disk=20G
    constraints: tags=compute-storage-2
