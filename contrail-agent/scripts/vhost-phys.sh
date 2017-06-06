#!/bin/sh -e
#
# Script used to determine physical interface of vhost0

iface="$1"
mac=$(cat /sys/class/net/$iface/address)
vif --list | awk -v mac=$mac -v iface=$iface 'BEGIN { RS="\n\n" }; $3 != iface && $0 ~ "HWaddr:" mac { print $3; exit 0 }'
