#!/bin/sh -e
#
# Script used to configure vRouter interface

ARG_BRIDGE=b
ARG_HELP=h
OPTS=:${ARG_BRIDGE}${ARG_HELP}
USAGE="\
create-vrouter [-${ARG_BRIDGE}${ARG_HELP}] [interface]
Options:
  -$ARG_BRIDGE  remove bridge from interface if exists
  -$ARG_HELP  print this message"

configVRouter()
{
	cat juju-header
	if [ -s "$2" ]; then
		printf "\n%s\n" "auto $1"
		cat "$2"
	elif [ ! -e "$2" ]; then
		printf "\n%s\n%s\n" "auto $1" "iface $1 inet manual"
	fi
	printf "\n%s\n"	"auto vhost0"
	if [ -e "$3" ]; then
		cat "$3"
	else
		echo "iface vhost0 inet dhcp"
	fi
	cat <<-EOF
		    pre-up ip link add vhost0 address \$(cat /sys/class/net/$1/address) type vhost
		    pre-up vif --add $1 --mac \$(cat /sys/class/net/$1/address) --vrf 0 --vhost-phys --type physical
		    pre-up vif --add vhost0 --mac \$(cat /sys/class/net/$1/address) --vrf 0 --type vhost --xconnect $1
		    post-down vif --list | awk '/^vif.*OS: vhost0/ {split(\$1, arr, "\\/"); print arr[2];}' | xargs vif --delete
		    post-down vif --list | awk '/^vif.*OS: $1/ {split(\$1, arr, "\\/"); print arr[2];}' | xargs vif --delete
		    post-down ip link delete vhost0
		EOF
}

configureInterfaces()
{
	for cfg in /etc/network/interfaces /etc/network/interfaces.d/*.cfg \
	    /etc/network/*.config; do
		# for each network interfaces config, extract the config for
		# the chosen interface whilst commenting it out in the
		# subsequent replacement config
		[ -e "$cfg" ] || continue
		awk -v interface=$1 -v interface_cfg=$TMP/interface.cfg \
		    -v vrouter_cfg=$TMP/vrouter.cfg -f vrouter-interfaces.awk \
		    "$cfg" > $TMP/interfaces.cfg
		if ! diff $TMP/interfaces.cfg "$cfg" > /dev/null; then
			# create backup
			mv "$cfg" "$cfg.save"
			# substitute replacement config for original config
			{ cat juju-header; echo; cat $TMP/interfaces.cfg; } > "$cfg"
		fi
	done
	if [ -e $TMP/interface.cfg ]; then
		# strip whitespace
		sed -En -e '1h;1!H;${g;s/[[:space:]]+$//;p}' -i \
		    $TMP/interface.cfg
	fi
}

configureInterfacesDir()
{
	# add interfaces.d source line to /etc/network/interfaces
	if ! grep -q '^[[:blank:]]*source /etc/network/interfaces\.d/\*\.cfg[[:blank:]]*$' \
	    /etc/network/interfaces; then
		printf "\n%s\n" "source /etc/network/interfaces.d/*.cfg" \
		    >> /etc/network/interfaces
		# it's possible for conflicting network config to exist in
		# /etc/network/interfaces.d when we start sourcing it
		# so disable any config as a precautionary measure
		for cfg in /etc/network/interfaces.d/*.cfg; do
			[ -e "$cfg" ] || continue
			mv "$cfg" "$cfg.old"
		done
	fi
	mkdir -p /etc/network/interfaces.d
}

configureVRouter()
{
	if [ $# = 1 ]; then
		iface_down=$1
		iface_delete=$1
		iface_up=$1
		iface_cfg=$TMP/interface.cfg
	else
		iface_down="$1 $2"
		iface_delete=$2
		iface_up=$1
		iface_cfg=/dev/null
	fi
	ifacedown $iface_down vhost0; sleep 5
	configureInterfacesDir
	configureInterfaces $iface_delete
	configVRouter $iface_up $iface_cfg $TMP/vrouter.cfg \
	    > /etc/network/interfaces.d/vrouter.cfg
	ifaceup $iface_up vhost0
	restoreRoutes
}

ifacebridge()
{
	for cfg in /etc/network/interfaces /etc/network/interfaces.d/*.cfg \
	    /etc/network/*.config; do
		# extract all the bridges with interface as port
		# and all interfaces marked auto
		[ -e "$cfg" ] || continue
		awk -v interface=$1 \
		    -v auto_interfaces=$TMP/auto_interfaces \
		    -v bridge_interfaces=$TMP/bridge_interfaces \
		    -f bridges.awk "$cfg"
	done
	if [ -e $TMP/bridge_interfaces ]; then
		# output the bridge marked auto
		grep -m 1 -f $TMP/bridge_interfaces $TMP/auto_interfaces
	fi
}

ifacedown()
{
	for iface; do
		# ifdown interface
		# if bridge, save list of interfaces
		# if bond, save list of slaves
		if [ ! -e /sys/class/net/$iface ]; then
			continue
		fi
		[ -d /sys/class/net/$iface/bridge ] && saveIfaces $iface
		[ -d /sys/class/net/$iface/bonding ] && saveSlaves $iface
		ifdown -v --force $iface
	done
}

ifaceup()
{
	for iface; do
		# ifup interface
		# if bridge, restore list of interfaces
		# restore list of slaves if exists (bond)
		restoreSlaves $iface
		ifup -v $iface
		[ -d /sys/class/net/$iface/bridge ] && restoreIfaces $iface
	done
	return 0
}

restoreRoutes()
{
	if [ -e /etc/network/routes ]; then
		service networking-routes stop
		service networking-routes start
	fi
}

restoreIfaces()
{
	if [ -e $TMP/$1.ifaces ]; then
		cat $TMP/$1.ifaces | xargs -n 1 brctl addif $1 || true
	fi
}

restoreSlaves()
{
	if [ -e $TMP/$1.slaves ]; then
		cat $TMP/$1.slaves | xargs ifup
	fi
}

saveIfaces()
{
	if [ -z "$(find /sys/class/net/$1/brif -maxdepth 0 -empty)" ]; then
		find /sys/class/net/$1/brif | tail -n +2 | xargs -n 1 basename \
		    > $TMP/$1.ifaces
	fi
}

saveSlaves()
{
	if [ -s /sys/class/net/$1/bonding/slaves ]; then
		cat /sys/class/net/$1/bonding/slaves | tr " " "\n" \
		    > $TMP/$1.slaves
	fi
}

usage()
{
	if [ $# -gt 0 ]; then
		fd=$1
	else
		fd=1
	fi
	echo "$USAGE" >&$fd
}

usageError()
{
	echo "$1" >&2
	usage 2
	exit 1
}

while getopts $OPTS opt; do
	case $opt in
	$ARG_BRIDGE)
		remove_bridge=true
		;;
	$ARG_HELP)
		usage
		exit 0
		;;
	"?")
		usageError "Unknown argument: $OPTARG"
		;;
	esac
done
shift $(($OPTIND - 1))

if [ $# -gt 1 ]; then
	usageError "Too many arguments"
fi

TMP=$(mktemp -d /tmp/create-vrouter.XXX)

if [ $# -ne 0 ]; then
	bridge=$(ifacebridge $1)
	if [ -n "$bridge" ]; then
		if [ -n "$remove_bridge" ]; then
			configureVRouter $1 $bridge
		else
			configureVRouter $bridge
		fi
	else
		configureVRouter $1
	fi
else
	# use default gateway interface
	gateway=$(route -n | awk '$1 == "0.0.0.0" { print $8 }')
	if [ -d /sys/class/net/$gateway/bridge ] \
	    && [ -z "$(find /sys/class/net/$gateway/brif -maxdepth 0 -empty)" ] \
	    && [ -n "$remove_bridge" ]; then
		interface=$(find /sys/class/net/$gateway/brif | sed -n -e '2p' | xargs basename)
		configureVRouter $interface $gateway
	else
		configureVRouter $gateway
	fi
fi

rm -rf $TMP
