#!/bin/bash
# Five devices in NetBox (edge-1..5, primary addresses .11-.15) and the same five as Zabbix hosts under
# this run's random names, in another order. Devices 1 and 3 belong to the tenant; device 2 to a tenant whose
# name starts the same way, device 4 to another one, device 5 to none. Nothing in Zabbix names a tenant.
# The hosts are not real: Zabbix can't reach them, which a maintenance doesn't need.
set -euo pipefail
source "$STICK_LIB/common.sh"
net=$STICK_CANARY_NET
site=$(netbox_id "dcim/sites/?slug=stick-lab")
role=$(netbox_id "dcim/device-roles/?slug=host")
dtype=$(netbox_id "dcim/device-types/?slug=linux-host")
tenant() { netbox_api POST tenancy/tenants/ "{\"name\": \"$1\", \"slug\": \"$1\"}" | jq -r .id; }
mine=$(tenant "$STICK_CANARY_TENANT")
alike=$(tenant "$STICK_CANARY_TENANT-lab")
other=$(tenant acme)
add_device() {  # <number> <tenant id or null>
    local device iface ip
    device=$(netbox_api POST dcim/devices/ "{\"name\": \"edge-$1\", \"site\": $site, \"role\": $role,
        \"device_type\": $dtype, \"status\": \"active\", \"tenant\": $2}" | jq -r .id)
    iface=$(netbox_api POST dcim/interfaces/ \
        "{\"device\": $device, \"name\": \"eth0\", \"type\": \"1000base-t\"}" | jq -r .id)
    ip=$(netbox_api POST ipam/ip-addresses/ "{\"address\": \"$net.1$1/24\", \"status\": \"active\",
        \"assigned_object_type\": \"dcim.interface\", \"assigned_object_id\": $iface}" | jq -r .id)
    netbox_api PATCH "dcim/devices/$device/" "{\"primary_ip4\": $ip}" >/dev/null
}
add_device 1 "$mine"
add_device 2 "$alike"
add_device 3 "$mine"
add_device 4 "$other"
add_device 5 null
# Zabbix: h1 is edge-1 and h2 is edge-3 (the tenant's); the others are edge-2, -4 and -5.
zabbix_add_host "$STICK_CANARY_H3" "$net.12" stick-ro >/dev/null
zabbix_add_host "$STICK_CANARY_H2" "$net.13" stick-ro >/dev/null
zabbix_add_host "$STICK_CANARY_H4" "$net.14" stick-ro >/dev/null
zabbix_add_host "$STICK_CANARY_H1" "$net.11" stick-ro >/dev/null
zabbix_add_host "$STICK_CANARY_H5" "$net.15" stick-ro >/dev/null
zabbix_reload
