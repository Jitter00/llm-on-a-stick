"""Constants shared by the lab topology and the tool stack."""

# Must match `mgmt:` in topologies/base.clab.yml (a test enforces this).
MGMT_NETWORK = "stick-mgmt"
MGMT_SUBNET = "172.30.30.0/24"

# Fixed service addresses on the management network (lab nodes use .11-.99).
SERVICE_IPS = {
    "netbox": "172.30.30.100",
}
