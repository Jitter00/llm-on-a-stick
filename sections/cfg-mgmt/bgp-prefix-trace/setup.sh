#!/bin/bash
# frr1 announces this run's /32 (on lo, through `redistribute connected`). Two filters stop it:
#   - frr1's route-map out towards srl1 denies it, so srl1 never gets it;
#   - srl2's export policy towards frr2 alone (a neighbour-level override of its group's) rejects it, so frr2
#     doesn't get it either, while srl2 has it from frr1.
# Decoys that look like they stop it and don't:
#   - frr1's route-map out towards srl2 denies a prefix-list of the same /24 that ends at /31 ("le 31");
#   - srl1 has a policy that rejects exactly this prefix, attached to nothing.
set -euo pipefail
source "$STICK_LIB/common.sh"
prefix="${STICK_CANARY_POOL}.${STICK_CANARY_HOST}/32"

frr_conf "$STICK_NODE_FRR1" "interface lo" "ip address ${prefix}" \
    "ip prefix-list ${STICK_CANARY_FRR_PL} seq 5 permit ${prefix}" \
    "ip prefix-list ${STICK_CANARY_DECOY_PL} seq 5 permit ${STICK_CANARY_POOL}.0/24 le 31" \
    "route-map ${STICK_CANARY_FRR_RM} deny 10" "match ip address prefix-list ${STICK_CANARY_FRR_PL}" "exit" \
    "route-map ${STICK_CANARY_FRR_RM} permit 20" "exit" \
    "route-map ${STICK_CANARY_DECOY_RM} deny 10" "match ip address prefix-list ${STICK_CANARY_DECOY_PL}" "exit" \
    "route-map ${STICK_CANARY_DECOY_RM} permit 20" "exit" \
    "router bgp 65101" "address-family ipv4 unicast" \
    "neighbor 10.0.1.0 route-map ${STICK_CANARY_FRR_RM} out" \
    "neighbor 10.0.2.0 route-map ${STICK_CANARY_DECOY_RM} out"

srl_commit "$STICK_NODE_SRL2" \
    "set / routing-policy prefix-set ${STICK_CANARY_SRL_PS} prefix ${prefix} mask-length-range exact" \
    "set / routing-policy policy ${STICK_CANARY_SRL_POL} statement 10 match prefix prefix-set ${STICK_CANARY_SRL_PS}" \
    "set / routing-policy policy ${STICK_CANARY_SRL_POL} statement 10 action policy-result reject" \
    "set / routing-policy policy ${STICK_CANARY_SRL_POL} statement 20 match protocol local" \
    "set / routing-policy policy ${STICK_CANARY_SRL_POL} statement 20 action policy-result accept" \
    "set / routing-policy policy ${STICK_CANARY_SRL_POL} default-action policy-result accept" \
    "set / network-instance default protocols bgp neighbor 10.0.2.3 export-policy [ ${STICK_CANARY_SRL_POL} ]"

srl_commit "$STICK_NODE_SRL1" \
    "set / routing-policy prefix-set ${STICK_CANARY_DECOY_PS} prefix ${prefix} mask-length-range exact" \
    "set / routing-policy policy ${STICK_CANARY_DECOY_POL} statement 10 match prefix prefix-set ${STICK_CANARY_DECOY_PS}" \
    "set / routing-policy policy ${STICK_CANARY_DECOY_POL} statement 10 action policy-result reject" \
    "set / routing-policy policy ${STICK_CANARY_DECOY_POL} default-action policy-result accept"

# Wait until BGP has settled: srl2 has the prefix from frr1, and frr2 and srl1 don't.
for _ in $(seq 60); do
    if srl_cli "$STICK_NODE_SRL2" "show network-instance default protocols bgp routes ipv4 prefix ${prefix}" |
            grep -q "BGP next-hop *: 10.0.2.1" &&
        ! frr_cli "$STICK_NODE_FRR2" "show ip bgp ${prefix}" | grep -q "best" &&
        ! srl_cli "$STICK_NODE_SRL1" "show network-instance default protocols bgp routes ipv4 prefix ${prefix}" |
            grep -q "Received Paths: [1-9]"; then
        exit 0
    fi
    sleep 1
done
echo "BGP did not settle on the expected state for ${prefix}" >&2
exit 1
