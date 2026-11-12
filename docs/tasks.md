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
   ~20 s, Nautobot's: ~25 s, LibreNMS's empty database: ~1 s, Zabbix's: ~10 s, moto's empty account: ~0.2 s);
2. **every router goes back to the config it booted with**, without a restart, so BGP stays up:
   - SR Linux reverts to `clab-initial`, the checkpoint containerlab takes once the startup config is applied;
   - FRR runs `frr-reload.py` against its startup config, `configs/frr/<node>/frr.conf`;
   - it takes about 2 s for the four routers, and the times are in the run's `restore.log`;
3. the task's `setup.sh` plants this run's canaries (or a fault);
4. the baseline is taken, for `no_change_outside`, `netbox_unchanged`, `nautobot_unchanged`, `librenms_unchanged`,
   `zabbix_unchanged` and `aws_unchanged`.

A task with `topology: none` (the `aws` and `terraform` sections, and three of the `mcp` tasks) uses no lab
device: step 2 is skipped, and the lab doesn't need to be running at all.

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

Each of these tasks also has one check for a [judge model](grading.md#the-judge-model) (`--judge-model`): how
the model went about the task (read before writing, looked ids up, confirmed its result). It is scored apart
and never changes pass or fail; without a judge it shows as "not graded". The other sections have none yet.

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
Apart from the floor task, none of them says what to create: the model has to find out what is there, and what
is wrong with it, first.

| Task | Tier | What the agent must do | What can go wrong (and is detected) |
|---|---|---|---|
| `aws-query-instance` | basic | Report an instance's private IP, its subnet's CIDR block and its security group's name | The other instance's values, the subnet id instead of its CIDR block, a changed account |
| `aws-ssh-exposure` | intermediate | Report every instance whose security groups let SSH in from the whole internet | Looking only for a rule on port 22 from 0.0.0.0/0: missing the port range that covers 22, the all-protocols rule, the `::/0` rule and the stopped instance; listing UDP 22, port 2222, a rule from another group, an outbound rule, or a group no instance uses |
| `aws-orphan-cleanup` | intermediate | Delete a project's unattached volumes, unassociated Elastic IPs, and security groups that nothing uses or refers to | Deleting the group that another group's rule refers to, a stopped instance's volume, another project's or an untagged orphan (the emulator refuses none of these); leaving an orphan behind |
| `aws-unreachable` | advanced | A web server doesn't answer HTTPS from the internet: find every cause and fix it | Stopping at the first of four causes (no public address, no default route, a network ACL deny entry, a security group that allows 443 from 10/8 only); opening more than 443; a default route on the main route table |
| `aws-iam-least-privilege` | advanced | Replace an over-broad role's permissions with one inline policy for the six operations the application performs, on exact ARNs | An API operation's name that is not an IAM action (`s3:ListObjectsV2` for `s3:ListBucket`), `ListBucket` on the object ARN, `ssm:GetParameters`, the KMS alias ARN instead of the key's, the dead-letter queue, a wildcard, the old inline or managed policies left on the role, the managed policy deleted (another role uses it), the role recreated |

Requirements: moto only (`uv run stick svc up moto`), not the lab. Every attempt starts from an empty account
(`reset_services: [moto]`, about 0.2 s), and `aws_unchanged` fails attempts that add, change or delete anything
the task didn't ask for. Run them with `uv run stick run --section aws ...`.

To try one by hand (`stick task start`, then work on your own machine), set the four `AWS_*` variables from
[Services](services.md#moto-emulated-aws) in your shell first: `stick run` sets them in the model's toolbox, but
your shell doesn't have them.

## terraform: infrastructure as code

Terraform against the same emulated account. Each task gives a working directory under the workspace with a
configuration in it; the grader runs `terraform plan` and `terraform state list` there itself, and reads the
account.

| Task | Tier | What the agent must do | What can go wrong (and is detected) |
|---|---|---|---|
| `tf-plan-report` | basic | Say what applying an edited configuration would create, update, replace and delete, without applying | Applying it, calling a replacement an update, missing the resource that is only deleted |
| `tf-debug` | intermediate | Repair a configuration that never applied (a `for_each` reference without a key, two security groups in a dependency cycle, a subnet outside the VPC) and apply it | Fixing the first error only, breaking the cycle by dropping a rule, moving only some rules out of the groups (inline and separate rules fight: the plan is never clean), building the rest with the CLI |
| `tf-import` | advanced | Bring a hand-made VPC, subnet, security group, internet gateway and route table under Terraform without changing them | Recreating instead of importing, a configuration that doesn't match the real settings (DNS hostnames, public addresses, the group's description and rules, tags), the table's route written as a separate resource that is never imported, "fixing" the difference with an apply |
| `tf-drift` | advanced | People worked by hand in a managed VPC: adopt the two approved changes (an instance resize, a new subnet), undo the rest (a rule on a managed group, a security group nobody manages) | A blind `terraform apply` (reverts the resize), `apply -refresh-only` (keeps the rule), stopping when the plan is clean (the plan shows neither the new subnet nor the new group), recreating the subnet instead of importing it, importing it without its tags |
| `tf-refactor-module` | advanced | Move two subnet resources into a local module with one `for_each` resource and add a third, without recreating the two | Destroy and create instead of `moved` blocks or `state mv`, the wrong module address or keys, the module not initialised, the new subnet missing |

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

## zabbix: monitoring

Zabbix polls the routers over SNMP (see [Services](services.md#zabbix)). These tasks drive it through its
JSON-RPC API. Three of them are graded by what Zabbix then does: whether it reaches the host, whether the
trigger raises a problem, which hosts it puts in maintenance. The grader forces the polls it needs.

| Task | Tier | What the agent must do | What can go wrong (and is detected) |
|---|---|---|---|
| `zabbix-query-host` | basic | Find the host with a given tag value among three; report its name and the address of its SNMP interface | The `auth` property instead of the header, a host whose tag value merely starts the same, no interface in the answer (`selectInterfaces`), changing anything |
| `zabbix-add-host` | intermediate | Add srl1 over SNMPv2c with this run's community, in a given group and with a given template, so that Zabbix really polls it | A wrong interface (`details`), names where ids are wanted, a wrong community (Zabbix takes it; the host is listed and never reached), touching frr1 |
| `zabbix-fix-monitoring` | intermediate | One router can't be polled since its community was changed on the device: find which, and fix its host in Zabbix | Deleting and re-adding the host (new id, history lost), changing the router instead, the global macro instead of the host's, "fixing" a healthy host |
| `zabbix-trigger` | advanced | Create one High trigger for the port with a given description that is down (a port with the same description is up on the other router); it must raise a problem | A trigger on the wrong router or port (no problem), a bad expression, one trigger per router, wrong severity |
| `zabbix-maintenance` | advanced | Put exactly the hosts of one host group in a 2-hour maintenance without data collection, starting now | A group whose name merely contains the wanted one, "with data collection" (the default), times that aren't epoch seconds or a period that isn't 2 hours, no time period, editing the hosts instead |

Requirements: the lab and Zabbix (`uv run stick env up`, `uv run stick svc up zabbix`). Every attempt starts
from a Zabbix with no hosts (`reset_services: [zabbix]`, about 10 s), and `zabbix_unchanged` fails attempts
that add, change or delete anything the task didn't ask for. Run them with
`uv run stick run --section zabbix ...`.

## mcp: the same tools through MCP servers

In the other sections the model has a shell and writes its own `curl`, `aws` or Python. Here it has **no shell
and no files**: its only tools are those of an MCP server (see
[Running models](runner.md#mcp-servers-instead-of-a-shell)), the way many agents reach these tools in practice.
There is one task per server, from easy to hard. The servers are the published ones, at pinned versions, not
ours: what their tools offer, how they name things and how much they return is part of what is tested.

| Task | Tier | Server | What the agent must do | What can go wrong (and is detected) |
|---|---|---|---|---|
| `mcp-netbox-lookup` | basic | NetBox Labs' `netbox-mcp-server` (4 read-only tools) | Find the device with a given asset tag, the rack it is in and the address on its eth1 | Reading the first page only (the server returns five objects unless asked for more), a device whose tag merely contains the wanted one, eth0's address, an answer in the reply instead of `submit_answer` |
| `mcp-aws-move-eip` | intermediate | AWS's `aws-api-mcp-server` (one tool: an AWS CLI command per call) | Move an Elastic IP from a stopped instance to a named running one | No pipes or `$(...)`: ids go from one call to the next by hand. Associating without `--allow-reassociation`, moving the other address (its Name tag starts the same), starting or terminating an instance |
| `mcp-nautobot-carve-prefix` | intermediate | `nautobot-mcp` (28 of 77 tools) | Reserve the first free /28 of a /24 in a namespace: the third one, a hole between taken blocks | "The one after the last", the same /24 in the Global namespace, a status or namespace given by name where the API wants a reference, more than one prefix |
| `mcp-librenms-ip-owner` | intermediate | `librenms-mcp` (33 of 113 tools) | Which device and port carries an address, and every IPv4 address on that port | The address list ties addresses to ports only by id: three lookups to join. Stopping at the first address, the other router's port (it has an extra address too), ifDescr or an id instead of ifName |
| `mcp-zabbix-netbox-maintenance` | advanced | `zabbix-mcp` (16 of 53 tools) and NetBox's | A 2-hour maintenance for exactly the Zabbix hosts of one NetBox tenant's devices; the names differ, the addresses match | Joining on names, the tenant whose name starts the same, times that aren't epoch seconds or 2 hours apart, a host group instead of the two hosts, two maintenances |

Requirements: the five services, and the lab for `mcp-librenms-ip-owner` only; `stick run --section mcp ...`
starts what is missing, and builds the MCP server image the first time (`stick-mcp`, about 0.8 GB, a few minutes).
The AWS server downloads AWS's service reference each time it starts, so `mcp-aws-move-eip` needs internet
access. Each task also has a `script.yaml`: its reference solution as MCP calls
(`stick run mcp-netbox-lookup --model script/sections/mcp/mcp-netbox-lookup/script.yaml`), which the lab tests
run to prove the task can be solved with the tools the model gets.

Large servers are cut down: a service's `mcp: allow:` list in its `service.yaml` names the tools the model is
shown (NetBox's and the AWS one are shown whole, except a tool that calls a hosted AWS service). Zabbix's 53
tools alone would cost about 18,000 tokens on every turn. So a result here is about the server as it is
configured in this repository, at that version; the transcript's first entry lists the tools.

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

Rewritten after the second comparison: the first `aws` and `terraform` tasks said exactly what to build, and
the smallest model tried (gemma4:12b) passed all ten. Eight were replaced by tasks where the model has to find
out what is there first (`aws-vpc-build`, `aws-sg-tighten`, `aws-iam-role` and `tf-write-vpc` are gone;
`aws-orphan-cleanup`, `tf-import`, `tf-drift` and the refactoring task got harder). On the new ones gemma4:12b
passes about four attempts in ten (the floor tasks nearly always, `aws-unreachable`, `tf-import` and `tf-drift`
never in six attempts), and Claude Haiku with thinking off about nineteen in twenty.

## Writing a task

A task is a folder with a `task.yaml`, optional `setup.sh` (runs before the attempt) and `oracle.sh` (reference
solution). The fields are described in [Grading](grading.md); copying one of the tasks above is the quickest start.
A task gives the model a shell unless it says `tools: {mcp: [<service>, ...]}`: then the model gets only
those services' MCP servers and `submit_answer` (the services must be under `requires.services`; a check that
reads the answer uses `path: answer.json`), and a `script.yaml` next to the task holds its solution as tool
calls. A check of type `llm_judge` is scored by a judge model against a rubric you write, apart from the
score ([Grading](grading.md#judge-checks-in-a-task)). Scripts get these environment variables:

| Variable | Meaning |
|---|---|
| `STICK_CANARY_<NAME>` | This run's canary values |
| `STICK_WORKSPACE` | Where the agent writes its files (`oracle.sh` writes its answer here) |
| `STICK_NODE_<NODE>` / `STICK_NODE_<NODE>_IP` | Container name / management IP of each lab node, e.g. `STICK_NODE_SRL1` |
| `STICK_<SERVICE>_URL` / `STICK_<SERVICE>_AUTH` | A service's host URL and, if it has an API token, its `Authorization` header value, e.g. `STICK_NETBOX_URL` |
| `AWS_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` | Only for tasks that require `moto`: what the AWS tools need to reach the emulator |
| `STICK_LIB` | Folder with shared helpers: `source "$STICK_LIB/common.sh"` gives `srl_set`, `srl_cli`, `frr_conf`, `frr_cli`, `netconf_get_config`, `oxidized_backup_now`, `netbox_api`, `netbox_id`, `nautobot_api`, `nautobot_id`, `librenms_api`, `librenms_add_device(s)`, `librenms_poll`, `librenms_wait_snmp`, `srl_snmp_community`, `zabbix_api`, `zabbix_add_host`, `zabbix_group_id`, `zabbix_poll`, `zabbix_wait_available`, `zabbix_wait_items`, `snmp_wait` |

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
  `librenms_wait_snmp` waits for it before LibreNMS reads the device (`snmp_wait` does the same from the toolbox
  image, with numeric OIDs: the image has no MIB files).
- Zabbix's `discoveryrule.get` ignores a `host` parameter (it lists every template's rules): pass `hostids`.
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
