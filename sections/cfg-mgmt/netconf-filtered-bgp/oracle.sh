#!/bin/bash
# Reference solution: get-config with a subtree filter selecting only the default network-instance's BGP neighbours.
set -euo pipefail
source "$STICK_LIB/common.sh"
filter=$(mktemp)
trap 'rm -f "$filter"' EXIT
cat > "$filter" <<'XML'
<network-instance xmlns="urn:nokia.com:srlinux:net-inst:network-instance">
  <name>default</name>
  <protocols><bgp xmlns="urn:nokia.com:srlinux:bgp:bgp"><neighbor/></bgp></protocols>
</network-instance>
XML
netconf_get_config "$STICK_NODE_SRL1_IP" "$filter" > "$STICK_WORKSPACE/srl1-bgp-neighbors.xml"
