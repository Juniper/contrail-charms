#!/bin/sh -e
juju deploy contrail-docker-bundle-ha.yaml
juju attach contrail-control contrail-control="/home/ubuntu/contrail-controller-u16.04-4.0.0.0-3034.tar.gz"
juju attach contrail-analytics contrail-analytics="/home/ubuntu/contrail-analytics-u16.04-4.0.0.0-3034.tar.gz"
juju attach contrail-analyticsdb contrail-analyticsdb="/home/ubuntu/contrail-analyticsdb-u16.04-4.0.0.0-3034.tar.gz"
juju attach contrail-lb contrail-lb="/home/ubuntu/contrail-lb-u16.04-4.0.0.0-3034.tar.gz"
