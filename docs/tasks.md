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

## Which tasks are kept

Most models tested here run locally, where one attempt can take minutes, so every task has to earn its place.
Each section has **at most five tasks**, and each one must tell models apart:

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
| `STICK_LIB` | Folder with shared helpers: `source "$STICK_LIB/common.sh"` gives `srl_set`, `srl_cli`, `frr_conf`, `frr_cli`, `netconf_get_config`, `oxidized_backup_now` |

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
- Canaries stay on the devices until the lab is redeployed; a setup that adds rather than overwrites (like a loopback
  address) must remove earlier runs' canaries first.
