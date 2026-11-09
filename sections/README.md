# Sections

Built-in tasks live here, one directory per task: `sections/<section>/<task-id>/task.yaml`.

A **section** is a set of tasks you run together (`stick run --section netbox ...`), with at most five tasks each.
New tasks get one section per tool, so you can test only the tools you use; `cfg-mgmt` stays one section.

| Section | Tasks | What it covers |
|---|---|---|
| `cfg-mgmt` | 5 | config retrieval over clear-text CLI and NETCONF, Oxidized backups |
| `netbox` | 5 | NetBox 4.x REST API: queries, documenting a router, drift between NetBox and a device, cables from LLDP, the next free IP configured on a router |
| `nautobot` | 5 | Nautobot 3.x REST and GraphQL APIs: queries, documenting a router, one GraphQL query for a location, cables from LLDP, the next free IP in a namespace configured on a router |

## Groupings

The wider areas the sections belong to, for orientation only (nothing in `task.yaml` refers to them):

| Grouping | Sections (planned ones in italics) |
|---|---|
| Lab management | *lab-mgmt* (containerlab, later CML) |
| Configuration management | `cfg-mgmt`, *gitea* (GitOps) |
| Source of truth and DDI | `netbox`, `nautobot`, *powerdns*, *kea* |
| Validation and observability | *batfish*, *suzieq*, *gnmic-prometheus*, *syslog*, *librenms*, *zabbix*, *pyats* (Cisco/CML only) |
| Troubleshooting | *troubleshooting*: injected faults, correlating events across tools |

The schema is `src/llm_on_a_stick/data/task.schema.json`. Check tasks with `stick task lint`.
Your own tasks can live anywhere: `stick task lint ./my-tests`.

`_lib/common.sh` holds helpers for setup and oracle scripts. Prove a task is sound with `stick task validate`.
Which tasks are kept (at most five per section, none obvious): `docs/tasks.md`.
