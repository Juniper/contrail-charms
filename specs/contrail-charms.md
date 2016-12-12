
#1. Introduction
Contrail 4.0 would provide support for Docker containers. The existing contrail components, which run as services on a BMS or VM, would be running within a Docker container in contrail 4.0. 
This document describes how to deploy contrail 4.0 Docker containers, which would be running the several contrail service components using contrail-charms

#2. Problem statement
The rationale behind the decision to containerize the contrail subsystems can be found [here]( https://github.com/Juniper/contrail-docker/blob/master/specs/contrail-docker.md). Contrail-charms 3.x or earlier provides functionality to provision each contrail component in separate lxd containers. With contrail 4.0, the contrail services would be contained in Docker containers. This necessitates change in contrail-charms to support the new mode of contrail deployment and support the deployment of the contrail docker images

#3. Proposed solution
Contrail Docker containers will be built to include all the packages needed to run the processes within the container. Also included in the containers will be Ansible playbooks to create the configuration files and provision the services within the container. Any provisioning tool to deploy these containers, including server manager, will need to perform 2 simple steps:
##3.1 Alternatives considered
####Describe pros and cons of alternatives considered.

##3.2 API schema changes
####Describe api schema changes and impact to the REST APIs.

##3.3 User workflow impact
####Describe how users will use the feature.

##3.4 UI changes
####Describe any UI changes

##3.5 Notification impact
####Describe any log, UVE, alarm changes


#4. Implementation
##4.1 Work items
####Describe changes needed for different components such as Controller, Analytics, Agent, UI. 
####Add subsections as needed.

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
