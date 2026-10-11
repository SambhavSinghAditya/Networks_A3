#!/bin/bash
# netcfg/r1.sh  -- usage: r1.sh IF_A IF_B
set -e
[ $# -eq 2 ] || { echo "usage: $0 IF_A IF_B" >&2; exit 1; }
IF_A="$1"; IF_B="$2"

ip addr add 10.10.1.1/24 dev "$IF_A"
ip link set dev "$IF_A" up
ip addr add 10.10.2.1/24 dev "$IF_B"
ip link set dev "$IF_B" up

# A5: one route covers every non-attached network (LAN C, Link D) -> r2
ip route add default via 10.10.2.2 dev "$IF_B"

# A4: router
sysctl -w net.ipv4.ip_forward=1

# A7: r1 stays strict (traffic is symmetric through r1)
sysctl -w net.ipv4.conf."$IF_A".rp_filter=1
sysctl -w net.ipv4.conf."$IF_B".rp_filter=1
