#!/bin/sh -e
#
# Script used to determine physical interface of vhost0

mac=$(cat /sys/class/net/vhost0/address)
vif --list | awk -v mac=$mac 'BEGIN { RS="\n\n" }; $3 != "vhost0" && $0 ~ "HWaddr:" mac { print $3; exit 0 }'
