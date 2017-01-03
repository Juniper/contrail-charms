#!/bin/bash
gateway=$(route -n | awk '$1 == "0.0.0.0" { print $8 }')
cp /etc/network/interfaces-before-add-juju-bridge /etc/network/interfaces
ip link set $gateway down
brctl  delbr $gateway
ifdown -a
ifup -a
sleep 12
