#!/bin/sh -e
juju deploy contrail-docker-bundle-ha.yaml
juju attach contrail-control contrail-control="/home/ubuntu/contrail-controller-u14.04-4.0.0.0-3023.tar.gz"
juju attach contrail-analytics contrail-analytics="/home/ubuntu/contrail-analytics-u14.04-4.0.0.0-3023.tar.gz"
juju attach contrail-analyticsdb contrail-analyticsdb="/home/ubuntu/contrail-analyticsdb-u14.04-4.0.0.0-3023.tar.gz"
juju attach contrail-agent contrail-agent="/home/ubuntu/contrail-agent-u14.04-4.0.0.0-3023.tar.gz"
juju attach contrail-lb contrail-lb="/home/ubuntu/contrail-lb-u14.04-4.0.0.0-3023.tar.gz"
