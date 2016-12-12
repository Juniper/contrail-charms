
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
2. Deploy the bundle using the command 'juju deploy <bundle_yaml_file>'.

##3.4 UI changes
####Describe any UI changes

##3.5 Notification impact
####Describe any log, UVE, alarm changes


#4. Implementation
Once the contrail-charms have been deployed the user can check the status of the deployment using the 'juju status' command.
Orchestrator:
Juju is the orechestration tool that will be used for deploying the charms.
There will be one charm per docker container image
The docker container images will be stored in the Juju Controller repository as a centrail placeholder uisng the Juju resources feature. The charms will get the resource from the controller and then load and run it.


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
##9.1 Unit tests
##9.2 Dev tests
##9.3 System tests

#10. Documentation Impact

#11. References
