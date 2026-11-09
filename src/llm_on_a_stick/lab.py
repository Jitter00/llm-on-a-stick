"""Constants shared by the lab topology and the tool stack."""

# Must match `mgmt:` in topologies/base.clab.yml (a test enforces this).
MGMT_NETWORK = "stick-mgmt"
MGMT_SUBNET = "172.30.30.0/24"

# Fixed service addresses on the management network (lab nodes use .11-.99).
SERVICE_IPS = {
    "netbox": "172.30.30.100",
    "oxidized": "172.30.30.101",
    "nautobot": "172.30.30.102",
    "moto": "172.30.30.103",
    "librenms": "172.30.30.104",
}
# Further containers of a service that need the management network (LibreNMS's dispatcher polls from it).
SERVICE_EXTRA_IPS = {
    "librenms": ["172.30.30.105"],
}
