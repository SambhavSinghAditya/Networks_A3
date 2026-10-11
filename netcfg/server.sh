#!/bin/bash
# netcfg/server.sh  -- usage: server.sh IF_C
set -e
[ $# -eq 1 ] || { echo "usage: $0 IF_C" >&2; exit 1; }
IF_C="$1"

ip addr add 10.10.3.10/24 dev "$IF_C"
ip link set dev "$IF_C" up

# everything not on LAN C goes through r2
ip route add default via 10.10.3.1 dev "$IF_C"

# A4: host, never forwards
sysctl -w net.ipv4.ip_forward=0

# A7: server stays strict (single interface, everything is symmetric)
sysctl -w net.ipv4.conf."$IF_C".rp_filter=1
