# Sections

Built-in tasks live here, one directory per task: `sections/<section>/<task-id>/task.yaml`.

A **section** is a set of tasks you run together (`stick run --section netbox ...`), with four tasks each: one basic, one
intermediate, one advanced, one expert. New tasks get one section per tool, so you can test only the tools you use;
`cfg-mgmt` stays one section. The model works through MCP servers (the tool's, and one that reaches the
routers), with no shell, except in `terraform`.

| Section | Tasks | What it covers |
|---|---|---|
| `cfg-mgmt` | 4 | Reading configuration off two vendors' routers through the routers' MCP server: one interface, the BGP configuration of two routers, BGP neighbours configured with the wrong AS; a prefix that two routers' policies keep from some routers |
| `netbox` | 4 | NetBox 4.x through its MCP server: a lookup, drift between NetBox and a router, documenting a router; cabling NetBox to match the lab's links |
| `nautobot` | 4 | Nautobot 3.x through its MCP server: a lookup, reserving the first free prefix, the next free IP in a namespace configured on a router; recording two routers' addresses, with a wrong link and a missing prefix |
| `aws` | 4 | AWS through AWS's API MCP server, against an emulated account (moto): a query, cleaning up unused resources, a web server unreachable for several reasons; an app server reaching a database in another VPC on one port |
| `terraform` | 4 | Terraform against the same account (shell): reading a plan, repairing a broken configuration, reconciling manual changes; moving resources into a module without recreating them |
| `librenms` | 4 | LibreNMS 26.10 through its MCP server, over SNMP-polled routers: a port query, fixing a device that went down, adding what NetBox lists as active; an alert rule for the one link that failed |
| `zabbix` | 4 | Zabbix 8.0 through its MCP server, over SNMP-polled routers: a host query, adding a host, a maintenance for the hosts of one NetBox tenant; a trigger on both ends of a failed link |
| `powerdns` | 4 | DNS zones in PowerDNS 5.1, through an MCP server made from its API description: every name that leads to an address, a second address for a name with its reverse record, the routers' records against the routers; reverse zones made to agree with the forward zones |
| `telemetry` | 4 | Streaming telemetry (gNMI) from the SR Linux routers in Prometheus, through Grafana's MCP server: ports that are enabled but down, a port that kept going down and the BGP session it took with it, three reasons sessions dropped; the path and rate of a traffic burst |
| `gitea` | 4 | A Git repository of router configurations in Gitea 28.3, through Gitea's MCP server: a setting on two branches, the commit that removed a BGP neighbour, a pull request for the file that drifted from its router; backporting one ticket to a release branch |
| `loki` | 4 | The routers' syslog in Loki, through Grafana's MCP server: failed logins for an account, a flapping link and the BGP session it takes down, the configuration change behind dropped sessions; a brute-force login and the change it made |

## Groupings

The wider areas the sections belong to, for orientation only (nothing in `task.yaml` refers to them):

| Grouping | Sections (planned ones in italics) |
|---|---|
| Lab management | *lab-mgmt* (containerlab, later CML) |
| Configuration management | `cfg-mgmt`, `gitea` (GitOps) |
| Source of truth and DDI | `netbox`, `nautobot`, `powerdns`, *kea* |
| Validation and observability | `librenms`, `zabbix`, `loki`, `telemetry`, *batfish*, *suzieq*, *pyats* (Cisco/CML only) |
| Cloud | `aws`, `terraform` (no lab devices: `topology: none`) |
| Troubleshooting | *troubleshooting*: injected faults, correlating events across tools |

The schema is `src/llm_on_a_stick/data/task.schema.json`. Check tasks with `stick task lint`.
Your own tasks can live anywhere: `stick task lint ./my-tests`.

`_lib/common.sh` holds helpers for setup and oracle scripts. Prove a task is sound with `stick task validate`.
Which tasks are kept (four per section, none obvious): `docs/tasks.md`.
