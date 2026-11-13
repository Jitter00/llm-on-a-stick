# Sections

Built-in tasks live here, one directory per task: `sections/<section>/<task-id>/task.yaml`.

A **section** is a set of tasks you run together (`stick run --section netbox ...`), with three tasks each: one basic, one
intermediate, one advanced. New tasks get one section per tool, so you can test only the tools you use;
`cfg-mgmt` stays one section. The model works through the tool's MCP server, with no shell, except in
`terraform` and in the tasks that touch a router (until the routers have a server too).

| Section | Tasks | What it covers |
|---|---|---|
| `cfg-mgmt` | 3 | config retrieval over clear-text CLI and NETCONF (shell) |
| `netbox` | 3 | NetBox 4.x: a lookup through its MCP server; drift between NetBox and a device and documenting a router (shell and REST API) |
| `nautobot` | 3 | Nautobot 3.x through its MCP server: a lookup, reserving the first free prefix; the next free IP in a namespace configured on a router (shell and REST API) |
| `aws` | 3 | AWS through AWS's API MCP server, against an emulated account (moto): a query, cleaning up unused resources, a web server unreachable for several reasons |
| `terraform` | 3 | Terraform against the same account (shell): reading a plan, repairing a broken configuration, reconciling manual changes |
| `librenms` | 3 | LibreNMS 26.10 through its MCP server, over SNMP-polled routers: a port query, fixing a device that went down, adding what NetBox lists as active |
| `zabbix` | 3 | Zabbix 8.0 through its MCP server, over SNMP-polled routers: a host query, adding a host, a maintenance for the hosts of one NetBox tenant |
| `loki` | 3 | The routers' syslog in Loki, through Grafana's MCP server: failed logins for an account, a flapping link and the BGP session it takes down, the configuration change behind dropped sessions |

## Groupings

The wider areas the sections belong to, for orientation only (nothing in `task.yaml` refers to them):

| Grouping | Sections (planned ones in italics) |
|---|---|
| Lab management | *lab-mgmt* (containerlab, later CML) |
| Configuration management | `cfg-mgmt`, *gitea* (GitOps) |
| Source of truth and DDI | `netbox`, `nautobot`, *powerdns*, *kea* |
| Validation and observability | `librenms`, `zabbix`, `loki`, *batfish*, *suzieq*, *gnmic-prometheus*, *pyats* (Cisco/CML only) |
| Cloud | `aws`, `terraform` (no lab devices: `topology: none`) |
| Troubleshooting | *troubleshooting*: injected faults, correlating events across tools |

The schema is `src/llm_on_a_stick/data/task.schema.json`. Check tasks with `stick task lint`.
Your own tasks can live anywhere: `stick task lint ./my-tests`.

`_lib/common.sh` holds helpers for setup and oracle scripts. Prove a task is sound with `stick task validate`.
Which tasks are kept (three per section, none obvious): `docs/tasks.md`.
