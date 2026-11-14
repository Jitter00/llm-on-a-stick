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
    "zabbix": "172.30.30.106",
    "loki": "172.30.30.108",  # Alloy, the syslog receiver; Loki and Grafana are reached from the host
    "telemetry": "172.30.30.109",  # gNMIc, which subscribes to the SR Linux routers
}
# Further containers of a service that need the management network (LibreNMS's dispatcher polls from it;
# Zabbix's server polls from the first address, its web frontend has the API).
SERVICE_EXTRA_IPS = {
    "librenms": ["172.30.30.105"],
    "zabbix": ["172.30.30.107"],
    "loki": ["172.30.30.111"],  # Grafana, which reads the telemetry service's Prometheus over this network
    "telemetry": ["172.30.30.110"],  # Prometheus
}
