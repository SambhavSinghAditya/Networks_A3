#!/bin/bash
# netcfg/client.sh  -- usage: client.sh IF_A IF_D
set -e
[ $# -eq 2 ] || { echo "usage: $0 IF_A IF_D" >&2; exit 1; }
IF_A="$1"; IF_D="$2"

ip addr add 10.10.1.10/24 dev "$IF_A"
ip link set dev "$IF_A" up
ip addr add 10.10.4.2/30 dev "$IF_D"
ip link set dev "$IF_D" up

# A2: everything towards LAN B / LAN C goes through r1
ip route add 10.10.2.0/24 via 10.10.1.1 dev "$IF_A"
ip route add 10.10.3.0/24 via 10.10.1.1 dev "$IF_A"

# A4: host, never forwards
sysctl -w net.ipv4.ip_forward=0

# A7: replies from LAN B/C come back over Link D (A3) but our route to them is via IF_A
sysctl -w net.ipv4.conf."$IF_A".rp_filter=1
sysctl -w net.ipv4.conf."$IF_D".rp_filter=2
