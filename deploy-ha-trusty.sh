#!/bin/sh -e
my_file="$(readlink -e "$0")"
my_dir="$(dirname $my_file)"
juju deploy "$my_dir/contrail-docker-bundle-ha-trusty.yaml"

BUILD="3065"
juju attach contrail-controller contrail-controller="/home/ubuntu/contrail-controller-ubuntu14.04-4.0.0.0-$BUILD.tar.gz"
juju attach contrail-analytics contrail-analytics="/home/ubuntu/contrail-analytics-ubuntu14.04-4.0.0.0-$BUILD.tar.gz"
juju attach contrail-analyticsdb contrail-analyticsdb="/home/ubuntu/contrail-analyticsdb-ubuntu14.04-4.0.0.0-$BUILD.tar.gz"
