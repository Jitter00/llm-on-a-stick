# Tasks

A task is one job for an AI model (or a person) to do in the lab, plus the code checks that grade it. Every task:

- states the **goal and the required output format, never the commands**: choosing the right commands is part of
  what's being tested;
- plants random **canary** values on the devices before the attempt, so a memorised or invented answer can't pass;
- checks that **nothing else was changed** on any device;
- ships a **reference solution** (`oracle.sh`) and is proven sound by `stick task validate`: the reference solution
  must pass, and doing nothing must not.

```bash
uv run stick task list                       # all tasks
uv run stick task start running-config-cli-frr   # prints the instructions; then the agent (or you) works
uv run stick grade                           # grades the attempt
```

Every attempt starts from the same state. The lab stays up between attempts, tasks, sections and models (only
`stick env up` / `env down` deploy or remove it), so `stick task start` resets it first:

1. the services the task lists under `reset_services` go back to their seeded snapshot (NetBox: ~20 s);
2. **every router goes back to the config it booted with**, without a restart, so BGP stays up:
   - SR Linux reverts to `clab-initial`, the checkpoint containerlab takes once the startup config is applied;
   - FRR runs `frr-reload.py` against its startup config, `configs/frr/<node>/frr.conf`;
   - it takes about 2 s for the four routers, and the times are in the run's `restore.log`;
3. the task's `setup.sh` plants this run's canaries (or a fault);
4. the baseline is taken, for `no_change_outside` and `netbox_unchanged`.

## cfg-mgmt: getting configuration right

These five tasks test whether a model can *retrieve* configuration correctly, across two vendors (Nokia SR Linux and
FRRouting) and two interfaces (CLI and NETCONF), before it's ever asked to change anything.

| Task | Tier | What the agent must do | What can go wrong (and is detected) |
|---|---|---|---|
| `running-config-cli-frr` | basic | Save frr2's complete running config | Pager or cut-off output, invented lines, wrong command |
| `running-config-cli-srl` | basic | Save srl1's complete running config in SR Linux "flat" (`set / ...`) format | Using the tree format, cutting the output short, Cisco-style commands |
| `config-section-bgp` | intermediate | Save only the BGP part of srl2's and frr1's configs | Saving everything (`unfiltered-output`), missing the address-family block, invented neighbours |
| `netconf-filtered-bgp` | advanced | NETCONF `<get-config>` with a filter returning only BGP neighbours | No filter (whole config returned), a wrong filter (no neighbours), wrong namespaces |
| `consistency-cli-netconf-oxidized` | advanced | Compare srl1's config via CLI, NETCONF and its Oxidized backup; say which is outdated and what differs | Triggering a new backup, confusing interface elements in the NETCONF tree, blaming the wrong source |

Requirements: the lab running (`uv run stick env up`); `consistency-cli-netconf-oxidized` also needs Oxidized
(`uv run stick svc up oxidized`). `stick task start` refuses to start a task whose requirements aren't met.

## netbox: the source of truth

These tasks use NetBox 4.x through its REST API. Its API changed in ways that trip models trained on older
versions: `role` instead of `device_role`, `nbt_` tokens sent as `Bearer`, required `status` fields, and an IP
address that must be assigned to an interface before it can be a device's primary IP.

| Task | Tier | What the agent must do | What can go wrong (and is detected) |
|---|---|---|---|
| `netbox-query-interface` | basic | Find the interface with a given description on a device, and its IP address | No token or the wrong header, the distractor address, a changed NetBox |
| `netbox-register-node` | intermediate | Document frr2 in NetBox: device, interfaces with the router's descriptions, mgmt IP as primary IPv4 | Wrong role/type/platform, descriptions not read off the router, primary IP not set (or set before it's assigned), edits to the seed |
| `netbox-drift` | intermediate | Report every difference between srl2 in NetBox and its running config | Missing the wrong address, inventing differences, "fixing" NetBox instead of reporting |
| `netbox-cables-lldp` | intermediate | Add NetBox cables for frr1's data links, from its LLDP neighbours (read with `lldpcli` over a Linux shell; the SR Linux neighbours carry this run's random host names in LLDP and in NetBox) | Guessing instead of reading LLDP, a cable for the management network, the pre-4.x cable payload (`termination_a_type`) instead of `a_terminations` |

Requirements: the lab and NetBox (`uv run stick env up`, `uv run stick svc up netbox`). Every attempt starts by
restoring NetBox's seeded snapshot (`reset_services: [netbox]`, about 20 s), and `netbox_unchanged` fails
attempts that change anything the task didn't ask for. Run them with `uv run stick run --section netbox ...`.

## Which tasks are kept

Most models tested here run locally, where one attempt can take minutes, so every task has to earn its place.
Each section (a tool such as `netbox`, or a group such as `cfg-mgmt`; the wider groupings are in
`sections/README.md`) has **at most five tasks**, and each one must tell models apart:

- **No obvious tasks.** A task that every model tried passes every time measures nothing. The exception is one
  cheap "floor" task per section, kept on purpose: it shows that a model can use the tool at all, in seconds
  (in cfg-mgmt, `running-config-cli-frr`).
- **No task that a harder one already covers.** Keep the harder one.
- **Re-check after each comparison** and remove tasks that stopped telling models apart.

Removed after the first comparison (Strata deepseek-v4.1-flash, Ollama gemma4:26b and gemma4:12b, 3 attempts
each): `extract-facts-json` (passed 9 of 9; writing exact JSON is still tested by the consistency task) and
`netconf-get-config-srl` (passed 8 of 9; `netconf-filtered-bgp` needs the same `<get-config>`, plus a filter).
They're in the git history if a smaller model ever needs them.

## Writing a task

A task is a folder with a `task.yaml`, optional `setup.sh` (runs before the attempt) and `oracle.sh` (reference
solution). The fields are described in [Grading](grading.md); copying one of the tasks above is the quickest start.
Scripts get these environment variables:

| Variable | Meaning |
|---|---|
| `STICK_CANARY_<NAME>` | This run's canary values |
| `STICK_WORKSPACE` | Where the agent writes its files (`oracle.sh` writes its answer here) |
| `STICK_NODE_<NODE>` / `STICK_NODE_<NODE>_IP` | Container name / management IP of each lab node, e.g. `STICK_NODE_SRL1` |
| `STICK_<SERVICE>_URL` / `STICK_<SERVICE>_AUTH` | A service's host URL and, if it has an API token, its `Authorization` header value, e.g. `STICK_NETBOX_URL` |
| `STICK_LIB` | Folder with shared helpers: `source "$STICK_LIB/common.sh"` gives `srl_set`, `srl_cli`, `frr_conf`, `frr_cli`, `netconf_get_config`, `oxidized_backup_now`, `netbox_api`, `netbox_id` |

Prompts can use `{{ services.<name>.url }}` and, for services with an API token, `{{ services.<name>.token }}`.

Keep your own tasks in any folder and point `stick` at it with `--tasks-dir`:

```bash
uv run stick task lint ./my-tasks
uv run stick task validate --tasks-dir ./my-tasks my-task-id
```

`stick task validate` needs `sshpass` on the host for tasks whose reference solution uses NETCONF
(`sudo apt install sshpass`). Agents attempting the tasks don't need it.

Things learned while writing these tasks:

- On SR Linux, `sr_cli -ed "set ..."` does not commit; use `sr_cli -ec` (`srl_set` does).
- A full NETCONF reply from SR Linux is ~300 KB: pass it through files, not environment variables.
- SR Linux has `<interface>` elements in several places (network-instances, LLDP...) reusing interface names; take
  top-level interfaces from directly under `<data>`.
- Setups don't need to clean up after earlier runs: routers are restored to their boot config, and NetBox to its
  seeded snapshot (`reset_services: [netbox]`), before every setup.
- FRR's running config shows some defaults the startup file doesn't have. frr-reload then flips them on every
  reload (FRR 10.7: `use-underlays-nexthop-weight` / `bgp deterministic-med`). Listing the default in
  `configs/frr/*/frr.conf` keeps the restore stable.
- LLDP: every node also sees every other node on the management network (`mgmt0` / `eth0`). FRR has no LLDP
  of its own: `lldpd` runs beside it, read with `lldpcli` as the `netops` shell user (vtysh can't). FRR's
  `lldpd` sends its MAC as the port ID unless `lldpcli configure lldp portidsubtype ifname` is set. SR Linux
  sends its host name as the LLDP system name, every 30 s, so a setup that renames it waits up to a minute
  for the neighbours to hear it.
