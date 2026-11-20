#!/bin/sh
# Start SuzieQ's poller against the lab's FRR routers.
#
# SuzieQ polls a Linux router with commands meant for a full Linux server: `sudo vtysh`, `systemctl` and
# `hostnamectl`. The lab's FRR containers (Alpine) have none of those, and the poller's account (netops) may
# run vtysh and lldpctl without sudo. So the poller gets a copy of SuzieQ's own command definitions with
# exactly those three changes; everything else (the tables, their parsers) is SuzieQ's unchanged.
# Without them the bgp, device and lldp tables stay empty ("Command Not Found").
set -eu

src=$(python -c 'import os, suzieq; print(os.path.join(os.path.dirname(suzieq.__file__), "config"))')
dst=/home/suzieq/services
rm -rf "$dst"
cp -r "$src" "$dst"
# YAML: the device command must not contain ": " (a mapping), hence \072 for the colons printf writes.
# shellcheck disable=SC2016  # $PRETTY_NAME and $(uname -m) are for the router's shell, not this one
sed -i \
    -e 's/sudo vtysh/vtysh/g' \
    -e 's/if systemctl status lldpd > \/dev\/null 2>&1; then sudo lldpctl; fi/lldpctl/' \
    -e 's/; hostnamectl$/; . \/etc\/os-release; printf "Chassis\\072 container\\nOperating System\\072 %s\\nArchitecture\\072 %s\\n" "$PRETTY_NAME" "$(uname -m)"/' \
    "$dst"/*.yml

# The routers' addresses depend on the lab instance (172.30.<30+N>.0/24), so the inventory is written here.
cat > /tmp/inventory.yml <<EOF
sources:
- name: lab
  hosts:
  - url: ssh://${STICK_MGMT_PREFIX}.21
  - url: ssh://${STICK_MGMT_PREFIX}.22
devices:
- name: frr
  ignore-known-hosts: true
auths:
- name: netops
  username: netops
  password: plain:netops
namespaces:
- name: lab
  source: lab
  device: frr
  auth: netops
EOF

exec sq-poller -I /tmp/inventory.yml -c /home/suzieq/suzieq-cfg.yml --no-coalescer
