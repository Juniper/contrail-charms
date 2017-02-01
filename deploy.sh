#!/bin/sh -e
juju deploy contrail-docker-bundle.yaml
juju attach contrail-control contrail-control="/home/ubuntu/contrail-controller-4.0.0.0-3016.tar.gz"
juju attach contrail-analytics contrail-analytics="/home/ubuntu/contrail-analytics-4.0.0.0-3016.tar.gz"
juju attach contrail-analyticsdb contrail-analyticsdb="/home/ubuntu/contrail-analyticsdb-4.0.0.0-3016.tar.gz"
juju attach contrail-agent contrail-agent="/home/ubuntu/contrail-agent-4.0.0.0-3013.tar.gz"
