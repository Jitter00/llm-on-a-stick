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

1. the services the task lists under `reset_services` go back to their baseline (NetBox's seeded snapshot:
   ~20 s, Nautobot's: ~25 s, LibreNMS's empty database: ~1 s, moto's empty account: ~0.2 s);
2. **every router goes back to the config it booted with**, without a restart, so BGP stays up:
   - SR Linux reverts to `clab-initial`, the checkpoint containerlab takes once the startup config is applied;
   - FRR runs `frr-reload.py` against its startup config, `configs/frr/<node>/frr.conf`;
   - it takes about 2 s for the four routers, and the times are in the run's `restore.log`;
3. the task's `setup.sh` plants this run's canaries (or a fault);
4. the baseline is taken, for `no_change_outside`, `netbox_unchanged`, `nautobot_unchanged`, `librenms_unchanged`
   and `aws_unchanged`.

A task with `topology: none` (the `aws` and `terraform` sections) uses no lab device: step 2 is skipped, and the
lab doesn't need to be running at all.

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
| `netbox-next-ip` | advanced | Take the lowest free address of a NetBox loopback pool, record it as a /32 on frr2's `lo` in NetBox, and configure it on frr2 | Taking "the highest plus one" (the pool has a gap), the prefix's /24 instead of /32, recording it in NetBox but not on the router (or the other way round), touching anything else |

Requirements: the lab and NetBox (`uv run stick env up`, `uv run stick svc up netbox`). Every attempt starts by
restoring NetBox's seeded snapshot (`reset_services: [netbox]`, about 20 s), and `netbox_unchanged` fails
attempts that change anything the task didn't ask for. Run them with `uv run stick run --section netbox ...`.

## nautobot: the other source of truth

The same jobs as the NetBox section, against Nautobot 3.x. Nautobot forked from NetBox but its data model has
moved on (see [Services](services.md#nautobot)), so a model that answers from NetBox habits fails here: `Bearer`
instead of `Token`, sites instead of locations, choice strings instead of Status objects, IP addresses outside a
namespace, NetBox's `assigned_object_*` fields (silently ignored), and NetBox 4's cable payload. The drift task is
replaced by a GraphQL one, a Nautobot feature that NetBox's tasks don't cover.

| Task | Tier | What the agent must do | What can go wrong (and is detected) |
|---|---|---|---|
| `nautobot-query-interface` | basic | Find the interface with a given description on a device, and its IP address (linked through `ip-address-to-interface`, so the interface list doesn't show it) | `Bearer` instead of `Token`, the distractor address, a changed Nautobot |
| `nautobot-register-node` | intermediate | Document frr2: device in location stick-lab, interfaces with the router's descriptions, mgmt IP in the stick-lab namespace as primary IPv4 | No status on the device or interfaces, `site` instead of `location`, the address in the wrong namespace, `assigned_object_*` (address left unlinked, so it can't be the primary IP) |
| `nautobot-graphql` | intermediate | Save one GraphQL query returning every device at a location with its interfaces and addresses, and list the addresses in answer.json | NetBox's GraphQL schema (`device_list`, `site`, `device_role`), a query without the location filter (a distractor device), REST instead (the saved query is run) |
| `nautobot-cables-lldp` | intermediate | Add Nautobot cables for frr1's data links, from its LLDP neighbours (random host names, as in the NetBox task) | Guessing instead of reading LLDP, a cable for the management network, NetBox 4's `a_terminations`, a missing or lower-case status |
| `nautobot-next-ip` | advanced | Take the lowest free address of the stick-lab loopback pool, record it as a /32 on frr2's `lo`, and configure it on frr2 | The same /24 in the Global namespace (more addresses taken there), "the highest plus one" (the pool has a gap), the /24 instead of /32, only one side done |

Requirements: the lab and Nautobot (`uv run stick env up`, `uv run stick svc up nautobot`). Every attempt starts
by restoring Nautobot's seeded snapshot (`reset_services: [nautobot]`, about 25 s), and `nautobot_unchanged` fails
attempts that change anything the task didn't ask for. Run them with `uv run stick run --section nautobot ...`.

## aws: cloud operations with the AWS CLI

AWS work against an emulated account ([moto](services.md#moto-emulated-aws)), with the `aws` CLI or boto3: the
model chooses. Tasks state the goal, not the commands, and are graded on the resources the account ends up with.

| Task | Tier | What the agent must do | What can go wrong (and is detected) |
|---|---|---|---|
| `aws-query-instance` | basic | Report an instance's private IP, its subnet's CIDR block and its security group's name | The other instance's values, the subnet id instead of its CIDR block, a changed account |
| `aws-vpc-build` | intermediate | Build a VPC with a public and a private subnet, an internet gateway, and a route table for the public subnet only | Gateway created but not attached, the default route put on the main route table (the private subnet gets it too), the route table not associated, no public addresses at launch |
| `aws-sg-tighten` | intermediate | SSH to an instance is open to the world: allow it from one network only, on the group that opens it | Editing the wrong one of the instance's two groups, deleting and recreating the group (new id), losing the group's other rules, adding the new rule without removing the open one |
| `aws-orphan-cleanup` | intermediate | Delete a project's unattached volumes and unassociated Elastic IPs | Deleting the attached volume or associated address, another project's or an untagged orphan, leaving one orphan behind |
| `aws-iam-role` | advanced | A role EC2 can assume, with an inline policy for `s3:GetObject` under one prefix and `s3:ListBucket` on the bucket, and an instance profile | Wildcard actions or resources, `ListBucket` on the object ARN, a trust policy copied from the over-broad existing role, a managed policy, no instance profile |

Requirements: moto only (`uv run stick svc up moto`), not the lab. Every attempt starts from an empty account
(`reset_services: [moto]`, about 0.2 s), and `aws_unchanged` fails attempts that add, change or delete anything
the task didn't ask for. Run them with `uv run stick run --section aws ...`.

To try one by hand (`stick task start`, then work on your own machine), set the four `AWS_*` variables from
[Services](services.md#moto-emulated-aws) in your shell first: `stick run` sets them in the model's toolbox, but
your shell doesn't have them.

## terraform: infrastructure as code

Terraform against the same emulated account. Each task gives a working directory under the workspace, most with
a configuration that the setup already applied; the grader runs `terraform plan` and `terraform state list` there
itself, and reads the account.

| Task | Tier | What the agent must do | What can go wrong (and is detected) |
|---|---|---|---|
| `tf-plan-report` | basic | Say what applying an edited configuration would create, update, replace and delete, without applying | Applying it, calling a replacement an update, missing the resource that is only deleted |
| `tf-write-vpc` | intermediate | Write and apply a configuration for a VPC, two subnets and a security group with two rules | Resources made with the CLI instead (not in the state), a plan that isn't clean on the second run, SSH open to the world |
| `tf-import` | advanced | Bring a hand-made VPC, subnet and security group under Terraform without changing them | Recreating instead of importing, a configuration that doesn't match the real settings (DNS hostnames, public addresses, the group's description and rules), "fixing" the difference with an apply |
| `tf-drift` | advanced | Two manual changes since the last apply: keep the instance's new type (and put it in the configuration), revert the extra security-group rule | A blind `terraform apply` (reverts both), `apply -refresh-only` (keeps both), replacing the instance |
| `tf-refactor-moved` | advanced | Turn two subnet resources into one `for_each` resource and add a third, without recreating the two | Destroy and create instead of `moved` blocks or `state mv`, wrong keys, the new subnet missing |

Requirements: moto only. Run them with `uv run stick run --section terraform ...`.

## librenms: monitoring

LibreNMS polls the routers over SNMP (see [Services](services.md#librenms)). These tasks drive it through its
REST API, and most of them relate what the NMS shows to what the devices do. The grader forces a poll before it
looks, so results never depend on the poller's timing.

| Task | Tier | What the agent must do | What can go wrong (and is detected) |
|---|---|---|---|
| `librenms-query-port` | basic | Find the port with a given description among the monitored devices; report the device's system name, the port name and its ifIndex | Wrong token header, the distractor port with another description, changing anything |
| `librenms-add-device` | intermediate | Add srl1 over SNMPv2c with this run's community, so that LibreNMS really polls it | A wrong payload (`hostname`, `version`, `community`), `force_add` hiding a wrong community (device listed but down), touching frr1 |
| `librenms-fix-monitoring` | intermediate | One router is down in LibreNMS since its community was changed on the device: find which, and fix LibreNMS's entry | Deleting and re-adding the device (new id, history lost), changing the router instead, "fixing" a healthy device |
| `librenms-alert-rule` | advanced | Create a critical rule for ports with a given description that are down; it must fire for exactly one port (another port with the description is up, dozens of undescribed ports are down) | A rule that never fires (bad builder JSON), one that fires for every down port, a duplicate rule after the API's misleading error, wrong severity |
| `librenms-netbox-sync` | advanced | Add to LibreNMS every device NetBox lists as active (random names, real addresses), by primary IPv4 | Adding the planned device, re-adding the one already monitored, using NetBox names LibreNMS can't resolve, changing NetBox |

Requirements: the lab and LibreNMS (`uv run stick env up`, `uv run stick svc up librenms`); `librenms-netbox-sync`
also needs NetBox. Every attempt starts from an empty LibreNMS (`reset_services: [librenms]`, about a second),
and `librenms_unchanged` fails attempts that add, change or delete anything the task didn't ask for. Run them
with `uv run stick run --section librenms ...`.

## Which tasks are kept

Most models tested here run locally, where one attempt can take minutes, so every task has to earn its place.
Each section (a tool such as `netbox`, or a group such as `cfg-mgmt`; the wider groupings are in
`sections/README.md`) has **at most five tasks**, and each one must tell models apart:

- **No obvious tasks.** A task that every model tried passes every time measures nothing. The exception is one
  cheap "floor" task per section, kept on purpose: it shows that a model can use the tool at all, in seconds
  (in cfg-mgmt, `running-config-cli-frr`). It is marked `floor: true` in its `task.yaml` (a test checks there is
  exactly one per section), and CI validates it whenever shared code changes.
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
| `AWS_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` | Only for tasks that require `moto`: what the AWS tools need to reach the emulator |
| `STICK_LIB` | Folder with shared helpers: `source "$STICK_LIB/common.sh"` gives `srl_set`, `srl_cli`, `frr_conf`, `frr_cli`, `netconf_get_config`, `oxidized_backup_now`, `netbox_api`, `netbox_id`, `nautobot_api`, `nautobot_id`, `librenms_api`, `librenms_add_device(s)`, `librenms_poll`, `librenms_wait_snmp`, `srl_snmp_community` |

Prompts can use `{{ services.<name>.url }}` and, for services with an API token, `{{ services.<name>.token }}`
(the value after `Bearer`/`Token`, or the whole `X-Auth-Token` for LibreNMS).

Keep your own tasks in any folder and point `stick` at it with `--tasks-dir`:

```bash
uv run stick task lint ./my-tasks
uv run stick task validate --tasks-dir ./my-tasks my-task-id
```

`stick task validate` needs `sshpass` on the host for tasks whose reference solution uses NETCONF
(`sudo apt install sshpass`). Agents attempting the tasks don't need it.

The cloud tasks' scripts need neither `aws` nor `terraform` on the host: `aws_cli ...` and `tf <dir> ...` run
them in the toolbox image, with the workspace at `/work` as in a run. Each call starts a container (about half a
second), so a setup with many commands sends one script instead:
`toolbox_run . bash -euo pipefail -s <<'SCRIPT' ... SCRIPT`.

Things learned while writing these tasks:

- On SR Linux, `sr_cli -ed "set ..."` does not commit; use `sr_cli -ec` (`srl_set` does).
- SR Linux startup configs (`configs/srl/*.cli`) take no `#` comment lines: containerlab stops applying the
  file at the first one, silently.
- SR Linux publishes a configuration change (a description, a community) over SNMP a few seconds later;
  `librenms_wait_snmp` waits for it before LibreNMS reads the device.
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
