#!/bin/bash
# netcfg/r2.sh  -- usage: r2.sh IF_B IF_C IF_D
set -e
[ $# -eq 3 ] || { echo "usage: $0 IF_B IF_C IF_D" >&2; exit 1; }
IF_B="$1"; IF_C="$2"; IF_D="$3"

ip addr add 10.10.2.2/24 dev "$IF_B"
ip link set dev "$IF_B" up
ip addr add 10.10.3.1/24 dev "$IF_C"
ip link set dev "$IF_C" up
ip addr add 10.10.4.1/30 dev "$IF_D"
ip link set dev "$IF_D" up

# A3: the client itself is reached over Link D (longest prefix wins over the /24)
ip route add 10.10.1.10/32 via 10.10.4.2 dev "$IF_D"
# A1: rest of LAN A (r1) via r1.  A6: no default route.
ip route add 10.10.1.0/24 via 10.10.2.1 dev "$IF_B"

# A4: router
sysctl -w net.ipv4.ip_forward=1

# A7: client->server packets (src 10.10.1.10) arrive on IF_B, but our route back to
# 10.10.1.10 is via IF_D -> strict RPF would drop them, so loose on IF_B only.
sysctl -w net.ipv4.conf."$IF_B".rp_filter=2
sysctl -w net.ipv4.conf."$IF_C".rp_filter=1
sysctl -w net.ipv4.conf."$IF_D".rp_filter=1
