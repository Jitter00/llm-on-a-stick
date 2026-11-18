#!/bin/bash
# h2 sends h1 a burst of UDP (iperf3, at this run's rate: RATE times 10 Mbit/s) through srl1: frr1 and frr2
# are told to prefer srl1 (BGP weight), so the burst doesn't split over both SR Linux routers. It comes in on
# srl1's ethernet-1/2 (from frr2) and leaves by ethernet-1/1 (to frr1). At the same time h2 pings srl2's
# ethernet-1/2 hard: traffic in and out of one port, through nothing.
set -euo pipefail
source "$STICK_LIB/common.sh"
from=$STICK_NODE_H2 to=$STICK_NODE_H1 to_ip=10.1.1.10 ping_ip=10.0.2.2
via=srl1 frr1_peer=10.0.1.0 frr2_peer=10.0.1.2
mbps=$((STICK_CANARY_RATE * 10))

telemetry_ready
frr_conf "$STICK_NODE_FRR1" "router bgp 65101" "neighbor $frr1_peer weight 100"
frr_conf "$STICK_NODE_FRR2" "router bgp 65102" "neighbor $frr2_peer weight 100"
for c in "$STICK_NODE_FRR1" "$STICK_NODE_FRR2"; do docker exec "$c" vtysh -c "clear bgp * soft in" >/dev/null; done
for _ in $(seq 30); do
    n1=$(docker exec "$STICK_NODE_FRR1" vtysh -c "show ip route 10.1.2.0/24" | grep -c '^  \*' || true)
    n2=$(docker exec "$STICK_NODE_FRR2" vtysh -c "show ip route 10.1.1.0/24" | grep -c '^  \*' || true)
    [[ $n1 == 1 && $n2 == 1 ]] && break
    sleep 1
done
[[ $n1 == 1 && $n2 == 1 ]] || { echo "the routes still go over both SR Linux routers" >&2; exit 1; }
sleep 10  # a few quiet samples before the burst

docker exec "$to" iperf3 -s -1 -D >/dev/null
sleep 1
docker exec -d "$from" ping -q -i 0.001 -s 1400 -w 30 "$ping_ip"
docker exec "$from" iperf3 -c "$to_ip" -u -b "${mbps}M" -l 1300 -t 30 >/dev/null
sleep 15  # until Prometheus has the last samples of the burst
prom_wait "count(rate(in_octets{source=\"$via\", interface_name=~\"ethernet-1/[12]\"}[30s]) > 100000) or vector(0)" 0 30
