# Sections

Built-in tasks live here, one directory per task: `sections/<section>/<task-id>/task.yaml`.

| Section | What it covers |
|---|---|
| `lab-mgmt` | containerlab (and later CML) lab lifecycle |
| `cfg-mgmt` | config retrieval (clear-text CLI, NETCONF), changes, Oxidized, GitOps via Gitea |
| `sot-ddi` | NetBox, Nautobot, PowerDNS, Kea |
| `validation-observability` | Batfish, SuzieQ, pyATS (Cisco/CML only), gNMIc + Prometheus, syslog, LibreNMS, Zabbix |
| `troubleshooting` | injected faults; correlating events across tools |

The schema is `src/llm_on_a_stick/data/task.schema.json`. Check tasks with `stick task lint`.
Your own tasks can live anywhere: `stick task lint ./my-tests`.

Tasks so far: seven in `cfg-mgmt` (config retrieval over CLI and NETCONF), described in `docs/tasks.md`.
`_lib/common.sh` holds helpers for setup and oracle scripts. Prove a task is sound with `stick task validate`.
