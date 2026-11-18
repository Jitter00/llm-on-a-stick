# Tasks

A task is one job for an AI model (or a person) to do in the lab, plus the code checks that grade it. Every task:

- states the **goal and the required output format, never the commands**: choosing the right commands is part of
  what's being tested;
- plants random **canary** values on the devices before the attempt, so a memorised or invented answer can't pass;
- checks that **nothing else was changed** on any device;
- ships a **reference solution** (`oracle.sh`) and is proven sound by `stick task validate`: the reference solution
  must pass, and doing nothing must not;
- has one check for a [judge model](grading.md#the-judge-model) (`--judge-model`): *how* the model went about
  the task (read before writing, looked ids up or guessed them, confirmed its result). It is scored apart and
  never changes pass or fail; without a judge it shows as "not graded".

```bash
uv run stick task list                       # all tasks
uv run stick task start config-interface-frr     # prints the instructions; then the agent (or you) works
uv run stick grade                           # grades the attempt
```

Every attempt starts from the same state. The lab stays up between attempts, tasks, sections and models (only
`stick env up` / `env down` deploy or remove it), so `stick task start` resets it first:

1. **every router goes back to the config it booted with**, without a restart, so BGP stays up:
   - SR Linux reverts to `clab-initial`, the checkpoint containerlab takes once the startup config is applied;
   - FRR runs `frr-reload.py` against its startup config, `configs/frr/<node>/frr.conf`;
   - it takes about 2 s for the four routers, and the times are in the run's `restore.log`;
2. the services the task lists under `reset_services` go back to their baseline (NetBox's seeded snapshot:
   ~20 s, Nautobot's: ~25 s, LibreNMS's empty database: ~1 s, Zabbix's: ~10 s, Gitea's repository: ~6 s, Loki's empty store: ~5 s, Prometheus's: ~0.2 s, PowerDNS without zones: ~1 s, moto's
   empty account: ~0.2 s), after the routers, so that Loki doesn't keep what the restore itself logged;
3. the task's `setup.sh` plants this run's canaries (or a fault);
4. the baseline is taken, for `no_change_outside`, `netbox_unchanged`, `nautobot_unchanged`, `librenms_unchanged`,
   `zabbix_unchanged`, `gitea_unchanged`, `powerdns_unchanged` and `aws_unchanged`.

A task with `topology: none` (the `aws` and `terraform` sections, and the tasks that only read or change a
source of truth, such as `netbox-lookup`) uses no lab device: step 1 is skipped, and the lab doesn't need to be running at all.

## How the model reaches the tools

Agents reach network tools through MCP servers more and more, so the sections are built that way: the model
has **no shell and no files**, only the tools of the section's MCP server and `submit_answer` (see
[Running models](runner.md#mcp-servers-instead-of-a-shell)). The servers are the published ones, at pinned
versions, not ours: what their tools offer, how they name things and how much they return is part of what is
tested. So a result is about the model **and** the server as it is configured here; the transcript's first
entry lists the tools.

Large servers are cut down: a service's `mcp: allow:` list in its `service.yaml` names the tools the model is
shown (the AWS one is shown whole, except a tool that calls a hosted AWS service). Zabbix's 53
tools alone would cost about 18,000 tokens on every turn.

Each of these tasks has a `script.yaml` next to it: its reference solution as MCP calls
(`stick run netbox-lookup --model script/sections/netbox/netbox-lookup/script.yaml`), which the lab tests run
to prove the task can be solved with the tools the model gets. The first run builds the MCP server image
(`stick-mcp`, about 0.8 GB, a few minutes).

The routers have a server too, `routers` (`topologies/mcp.yaml`): Kirk Byers' `netmiko-mcp`, which logs in
over SSH and runs one CLI command per call. It is not a service: a task names it under `tools.mcp` and lists
the routers it needs under `requires.devices`.

- **FRR is reached as a Linux host**, so its CLI commands are `vtysh -c "<command>"`; SR Linux is reached
  in its own CLI. The prompts say so.
- **Only commands that start with `vtysh -c`, `show` or `info` are let through**, with at most one pipe to
  `grep`, `head`, `tail` or `wc`.
- **It has no tool that changes configuration.** `vtysh -c "configure terminal" -c "..."` starts with an
  allowed command, and that is how `nautobot-next-ip` configures frr2. SR Linux can't be changed through it:
  a change there needs several commands in one session.
- **No NETCONF or gNMI**: no published server offers them for SR Linux, so no task uses them.

Only `terraform` still gives the model a shell, for good: Terraform is a command and files in a directory.

What this gives up: whether a model can write the REST, GraphQL or JSON-RPC call itself, NETCONF, and
saving a whole configuration to a file (a tool result is cut at 4,000 characters).

## cfg-mgmt: getting configuration right

These four tasks test whether a model can *read* configuration correctly off two vendors' routers (Nokia
SR Linux and FRRouting), before it's ever asked to change anything. The model works through the `routers` MCP
server and answers with facts from the configuration, not with the configuration itself.

| Task | Tier | What the agent must do | What can go wrong (and is detected) |
|---|---|---|---|
| `config-interface-frr` | basic | Report the description and address configured on frr2's eth3 | A plain `show` sent to FRR's Linux shell, another interface's values, an invented description |
| `config-section-bgp` | intermediate | Report srl2's and frr1's BGP configuration: own AS, and each neighbour's address, AS and description | One vendor's syntax used on the other, a neighbour missed, descriptions swapped or invented |
| `bgp-peering-audit` | advanced | Across the four routers, find every BGP neighbour configured with an AS that the router at the other end doesn't have | Trusting neighbour descriptions instead of interface addresses, reporting only one vendor's mismatch, reporting the right AS as wrong |
| `bgp-prefix-trace` | expert | frr1 announces a prefix: for the other three routers, whether it is in BGP and its next hop, or the policy that drops it (router, name, direction) | A route-map out on FRR and an export policy on one SR Linux neighbour; a prefix-list that only looks as if it matches (`le 31`); a policy that rejects the prefix but is attached to nothing; reading only the router that lacks it |

Requirements: the lab running (`uv run stick env up`). `stick task start` refuses to start a task whose
requirements aren't met.

## netbox: the source of truth

These tasks use NetBox 4.x through the community server `netbox-mcp` (13 of its 22 tools), which can create,
update and delete objects; NetBox Labs' own server is read-only by design. Two of the tasks also read a
router, through the `routers` server. NetBox's data model still trips models trained on older versions
(`role` instead of `device_role`, required `status` fields, and an IP address that must be assigned to an
interface before it can be a device's primary IP).

| Task | Tier | What the agent must do | What can go wrong (and is detected) |
|---|---|---|---|
| `netbox-register-node` | advanced | Document frr2 in NetBox: device, interfaces with the router's descriptions, mgmt IP as primary IPv4 | Wrong role/type/platform, descriptions not read off the router, primary IP not set (or set before it's assigned), edits to the seed |
| `netbox-cable-links` | expert | The four routers are in NetBox under other names: make its cables match the lab's router-to-router links, worked out from the interface addresses | Names to match by management address; one right cable to keep, one wrong cable to delete (its port is taken); a description that points the wrong way; cabling host or management ports |
| `netbox-lookup` | basic | Find the device with a given asset tag, the rack it is in and the address on its eth1 | Reading the first page only (the server returns ten objects unless asked for more), a device whose tag merely contains the wanted one, eth0's address, an answer in the reply instead of `submit_answer` |
| `netbox-drift` | intermediate | Report every difference between srl2 in NetBox and its running config | Missing the wrong address, inventing differences, "fixing" NetBox instead of reporting |

Requirements: the lab and NetBox (`uv run stick env up`, `uv run stick svc up netbox`). Every attempt starts by
restoring NetBox's seeded snapshot (`reset_services: [netbox]`, about 20 s), and `netbox_unchanged` fails
attempts that change anything the task didn't ask for. Run them with `uv run stick run --section netbox ...`.

## nautobot: the other source of truth

Nautobot 3.x, through the community server `nautobot-mcp` (28 of its 77 tools), which can write. Nautobot forked
from NetBox but its data model has moved on (see [Services](services.md#nautobot)), so a model that answers from
NetBox habits fails here: sites instead of locations, choice strings instead of Status objects, IP addresses
outside a namespace, NetBox's `assigned_object_*` fields (silently ignored). `nautobot-next-ip` also configures
a router, through the `routers` server.

| Task | Tier | What the agent must do | What can go wrong (and is detected) |
|---|---|---|---|
| `nautobot-query-interface` | basic | Find the interface with a given description on a device, and its IP address (linked through `ip-address-to-interface`, so the interface list doesn't show it) | The distractor address, another device's interface, a changed Nautobot |
| `nautobot-carve-prefix` | intermediate | Reserve the first free /28 of a /24 in a namespace: the third one, a hole between taken blocks | "The one after the last", the same /24 in the Global namespace, a status or namespace given by name where the API wants a reference, more than one prefix |
| `nautobot-next-ip` | advanced | Take the lowest free address of the stick-lab loopback pool, record it as a /32 on frr2's `lo`, and configure it on frr2 | The same /24 in the Global namespace (more addresses taken there), "the highest plus one" (the pool has a gap), the /24 instead of /32, only one side done |
| `nautobot-ip-sync` | expert | Record every IPv4 address on frr1's and frr2's interfaces in namespace stick-lab, with its mask, assigned to its interface | An address linked to the wrong interface (relink, don't duplicate); copies in Global that don't count; a /24 that exists only in Global and has to be created first; the routers' canary loopbacks |

Requirements: Nautobot, and the lab for `nautobot-next-ip`. Every attempt starts
by restoring Nautobot's seeded snapshot (`reset_services: [nautobot]`, about 25 s), and `nautobot_unchanged` fails
attempts that change anything the task didn't ask for. Run them with `uv run stick run --section nautobot ...`.

## aws: cloud operations

AWS work against an emulated account ([moto](services.md#moto-emulated-aws)), through AWS's
`aws-api-mcp-server`: one tool that runs one AWS CLI command per call, with no pipes or `$(...)`, so ids go
from one call to the next by hand. The server downloads AWS's service reference each time it starts, so these
tasks need internet access. Tasks state the goal, not the commands, and are graded on the resources the account ends up with.
Apart from the floor task, none of them says what to create: the model has to find out what is there, and what
is wrong with it, first.

| Task | Tier | What the agent must do | What can go wrong (and is detected) |
|---|---|---|---|
| `aws-query-instance` | basic | Report an instance's private IP, its subnet's CIDR block and its security group's name | The other instance's values, the subnet id instead of its CIDR block, a changed account |
| `aws-orphan-cleanup` | intermediate | Delete a project's unattached volumes, unassociated Elastic IPs, and security groups that nothing uses or refers to | Deleting the group that another group's rule refers to, a stopped instance's volume, another project's or an untagged orphan (the emulator refuses none of these); leaving an orphan behind |
| `aws-unreachable` | advanced | A web server doesn't answer HTTPS from the internet: find every cause and fix it | Stopping at the first of four causes (no public address, no default route, a network ACL deny entry, a security group that allows 443 from 10/8 only); opening more than 443; a default route on the main route table |
| `aws-vpc-peering` | expert | An app server must reach a database in another VPC on 5432, and nothing else may: make it work | An old VPC with the app VPC's CIDR and a stopped server of the same name; a pending peering to it; routes on the subnets' tables, not the main ones; a NACL that blocks the replies; a batch server that must not get in; opening 22 |

Requirements: moto only (`uv run stick svc up moto`), not the lab. Every attempt starts from an empty account
(`reset_services: [moto]`, about 0.2 s), and `aws_unchanged` fails attempts that add, change or delete anything
the task didn't ask for. Run them with `uv run stick run --section aws ...`.

To try one by hand (`stick task start`, then work on your own machine), set the four `AWS_*` variables from
[Services](services.md#moto-emulated-aws) in your shell first.

## terraform: infrastructure as code

Terraform against the same emulated account, with a shell (the one section that stays that way). Each task gives a working directory under the workspace with a
configuration in it; the grader runs `terraform plan` and `terraform state list` there itself, and reads the
account.

| Task | Tier | What the agent must do | What can go wrong (and is detected) |
|---|---|---|---|
| `tf-plan-report` | basic | Say what applying an edited configuration would create, update, replace and delete, without applying | Applying it, calling a replacement an update, missing the resource that is only deleted |
| `tf-debug` | intermediate | Repair a configuration that never applied (a `for_each` reference without a key, two security groups in a dependency cycle, a subnet outside the VPC) and apply it | Fixing the first error only, breaking the cycle by dropping a rule, moving only some rules out of the groups (inline and separate rules fight: the plan is never clean), building the rest with the CLI |
| `tf-drift` | advanced | People worked by hand in a managed VPC: adopt the two approved changes (an instance resize, a new subnet), undo the rest (a rule on a managed group, a security group nobody manages) | A blind `terraform apply` (reverts the resize), `apply -refresh-only` (keeps the rule), stopping when the plan is clean (the plan shows neither the new subnet nor the new group), recreating the subnet instead of importing it, importing it without its tags |
| `tf-refactor` | expert | Move the network into a local module and from `count` to `for_each` by subnet name, with nothing destroyed, replaced or changed | Without `moved` blocks every resource is recreated (new ids); indexes that don't follow the names; references and outputs that break; a plan that isn't clean |

Requirements: moto only. Run them with `uv run stick run --section terraform ...`.

## librenms: monitoring

LibreNMS polls the routers over SNMP (see [Services](services.md#librenms)). These tasks drive it through the
community server `librenms-mcp` (33 of its 113 tools), and most of them relate what the NMS shows to what the devices do. The grader forces a poll before it
looks, so results never depend on the poller's timing.

| Task | Tier | What the agent must do | What can go wrong (and is detected) |
|---|---|---|---|
| `librenms-query-port` | basic | Find the port with a given description among the monitored devices; report the device's system name, the port name and its ifIndex | The distractor port with another description, an id instead of the system name, changing anything |
| `librenms-fix-monitoring` | intermediate | One router is down in LibreNMS since its community was changed on the device: find which, and fix LibreNMS's entry | Deleting and re-adding the device (new id, history lost), changing the router instead, "fixing" a healthy device |
| `librenms-netbox-sync` | advanced | Add to LibreNMS every device NetBox lists as active (random names, real addresses), by primary IPv4 | Adding the planned device, re-adding the one already monitored, using NetBox names LibreNMS can't resolve, changing NetBox |
| `librenms-link-down-alert` | expert | Add the router LibreNMS is missing, and one alert rule that fires for an enabled router link that is down, and for nothing else | A spare port that is up in config but leads nowhere; a planned link port that is disabled; a rule missing one of its three conditions alerts on srl1 too; forgetting the device the alert should be on |

Requirements: the lab and LibreNMS (`uv run stick env up`, `uv run stick svc up librenms`); `librenms-netbox-sync`
also needs NetBox. Every attempt starts from an empty LibreNMS (`reset_services: [librenms]`, about a second),
and `librenms_unchanged` fails attempts that add, change or delete anything the task didn't ask for. Run them
with `uv run stick run --section librenms ...`.

## zabbix: monitoring

Zabbix polls the routers over SNMP (see [Services](services.md#zabbix)). These tasks drive it through the
community server `zabbix-mcp` (16 of its 53 tools). Two of them are graded by what Zabbix then does: whether it
reaches the host, and which hosts it puts in maintenance. The grader forces the polls it needs.

| Task | Tier | What the agent must do | What can go wrong (and is detected) |
|---|---|---|---|
| `zabbix-query-host` | basic | Find the host with a given tag value among three; report its name and the address of its SNMP interface | No tag filter in the tool: the hosts' tags have to be asked for and read; a host whose tag value merely starts the same, no interface in the answer, changing anything |
| `zabbix-add-host` | intermediate | Add srl1 over SNMPv2c with this run's community, in a given group and with a given template, so that Zabbix really polls it | A wrong interface (`details`), names where ids are wanted, a wrong community (Zabbix takes it; the host is listed and never reached), touching frr1 |
| `zabbix-netbox-maintenance` | advanced | A 2-hour maintenance for exactly the Zabbix hosts of one NetBox tenant's devices; the names differ, the addresses match (uses NetBox's server too) | Joining on names, the tenant whose name starts the same, times that aren't epoch seconds or 2 hours apart, a host group instead of the two hosts, two maintenances |
| `zabbix-port-down-problem` | expert | One router-to-router link failed: add one High trigger on the operational status of the ports at both ends, in problem state now | Hosts under random names; a spare port that is down and cabled to nothing; item keys to look up from discovery; a trigger on one end only, or on more items |

Requirements: the lab and Zabbix; `zabbix-netbox-maintenance` needs NetBox instead of the lab. Every attempt starts
from a Zabbix with no hosts (`reset_services: [zabbix]`, about 10 s), and `zabbix_unchanged` fails attempts
that add, change or delete anything the task didn't ask for. Run them with
`uv run stick run --section zabbix ...`.

## telemetry: streaming telemetry from the routers

srl1 and srl2 stream the state and counters of their ports and BGP sessions over gNMI, and Prometheus keeps
them ([Services](services.md#telemetry)). The model has **no shell**: it reads them through Grafana's MCP
server (5 of its tools: finding the datasource, metric names, label names and values, PromQL queries). Each
setup waits until Prometheus has a starting point, makes real events on the routers, and waits until
Prometheus has them. In three of the four tasks everything is up again when the model starts: the answer is
only in the history.

| Task | Tier | What the agent must do | What can go wrong (and is detected) |
|---|---|---|---|
| `telemetry-idle-ports` | basic | On srl2: how many ports are enabled and up, and how many are enabled but down | Counting every port that is down (most are disabled); counting srl1's enabled port too; a result with all 68 ports, which is cut off; an answer in the reply instead of `submit_answer` |
| `telemetry-port-flaps` | intermediate | One port kept going down: the router, the port, how often it went down, and the neighbour of the BGP session that dropped with it | Another port that went down once; a session reset with no port down; counting every change of state (down and up) instead of every fall; a range query whose result is cut off |
| `telemetry-session-drops` | advanced | Three sessions dropped for three reasons (the port was disabled, the link failed, the session alone was reset): which is which, and how often the reset one came back | Taking a failed link for a disabled port (only the admin state tells them apart); matching sessions to ports by guessing instead of by time; counting the resets from `session_state`, which misses those that were over between two scrapes |
| `telemetry-traffic-path` | expert | A burst of traffic crossed one SR Linux router: which, the port in and the port out, and the average rate (within 25%) | A ping flood on the other router's port at the same time; reading counters instead of their `rate()`; in and out swapped; a result cut at 4,000 characters |

Requirements: the lab, the `telemetry` service (gNMIc, Prometheus: about 0.1 GB) and the `loki` service for
its Grafana. Answers go through `submit_answer`; each task has a `script.yaml` with its reference solution
as MCP calls. Only the SR Linux routers stream: FRR has no gNMI.

## gitea: a Git repository of router configurations

Gitea hosts the repository `netops/lab-configs` ([Services](services.md#gitea)). The model has **no shell
and no `git`**: it works through Gitea's own MCP server (12 of its tools: repositories, branches, commits,
files, pull requests). Each setup writes the repository's history for this run through Gitea's API, with
fixed authors and dates, so a history reads the same every time and only the canary values differ.

| Task | Tier | What the agent must do | What can go wrong (and is detected) |
|---|---|---|---|
| `gitea-blame-change` | basic | A BGP neighbour is gone from a file: the ticket and author of the commit that removed it | The commit whose message says it removes a neighbour removes another one; the right commit's message is about timers; commits to the other router's file with the same wording; answering from messages without reading a diff |
| `gitea-file-at-ref` | intermediate | A description in one file on `main` and on a named branch, and the files that differ between the two | Reading the default branch twice; another branch with a similar name that changes the same line; listing the files of that other branch; missing the file the branch adds; decoding the file by hand (the server returns it as base64 unless asked for numbered lines) |
| `gitea-drift-pr` | advanced | Four files record what four routers should run, and one is stale: find it by comparing with the routers, and open a pull request that corrects it | Committing to `main`; merging the pull request; rewriting the file instead of changing its one line; touching another file; a pull request with the stale value still in it; changing the router to match the file |
| `gitea-backport-pr` | expert | Backport one ticket's changes from `main` to `release/2026.11` as a pull request, keeping the release branch's own changes | The ticket has two commits among five; a decoy change on the line the release branch also changed; a README commit that names the ticket; committing to the release branch or merging |

Requirements: the `gitea` service (about 0.1 GB); only `gitea-drift-pr` needs the lab, and it gets the
`routers` server as well. Every attempt starts from the repository with one commit
(`reset_services: [gitea]`, about 6 s), and `gitea_unchanged` fails attempts that add, change or delete a
branch, a pull request or a repository the task didn't ask for; a commit shows as its branch changed.
Answers of the two read-only tasks go through `submit_answer`; each task has a `script.yaml` with its
reference solution as MCP calls.

## powerdns: DNS zones and records

PowerDNS is an authoritative DNS server with an HTTP API ([Services](services.md#powerdns)). It publishes no
MCP server, so the model works through one made from PowerDNS's own API description (6 tools: servers, zones,
one zone's records, changing record sets, deleting a zone, search). The model has **no shell and no `dig`**.
Each setup creates the zones of its run, with names and addresses that differ every time.

| Task | Tier | What the agent must do | What can go wrong (and is detected) |
|---|---|---|---|
| `powerdns-who-points-here` | basic | Every name that leads to one address: its A records in two zones, and the alias of one of them | Reading one zone only; missing the alias (a search for the address doesn't return it, and a search for its target with the dot at the end finds nothing); the neighbouring address; a TXT record that mentions the address; the alias of another name |
| `powerdns-add-address` | intermediate | A name has one address: add a second one with the same TTL, and the PTR record of the new address | Replacing the record set with only the new address (the API writes whole record sets); another TTL; the PTR record in the forward zone, with the octets in the wrong order or without the dot at the end of its target; the same name in another zone; a new zone |
| `powerdns-router-audit` | advanced | One A record per router should hold the service address on the router's loopback: compare the zone with the four routers and correct it | A record with an older address; a record that is right but disabled, so DNS doesn't answer it; a router with no record; taking the router's other loopback address; rewriting the record that was right; changing a router to match the zone |
| `powerdns-ptr-reconcile` | expert | Make the reverse zones agree with the A records in every forward zone: add, correct and delete PTR records | A name with two addresses; a PTR with an old name; an orphan PTR and a TXT record that mentions its address; a CNAME, which gets no PTR; an address outside both networks; a PTR that is already right |

Requirements: the `powerdns` service (about 50 MB); only `powerdns-router-audit` needs the lab, and it gets
the `routers` server as well. Every attempt starts from a PowerDNS without zones
(`reset_services: [powerdns]`, about 1 s). The write tasks are graded by **asking the DNS server** (`dns_record`), not
by reading the API back, and `powerdns_unchanged` fails attempts that add, change or delete a zone or a
record set the task didn't ask for. The answer of the read-only task goes through `submit_answer`; each task
has a `script.yaml` with its reference solution as MCP calls.

## loki: the routers' syslog

The four routers send their syslog to Loki ([Services](services.md#loki)). The model has **no shell**: it
reads the logs through Grafana's MCP server (6 of its tools: finding the datasource, labels, log queries,
statistics, patterns). Each setup makes real events on the routers (logins, a port going down, a commit), with other events
around them, and waits until Loki has the lines.

| Task | Tier | What the agent must do | What can go wrong (and is detected) |
|---|---|---|---|
| `loki-failed-logins` | basic | Somebody tried an account that doesn't exist: which router, from which address, how many attempts | Counting log lines (`sshd` writes several per attempt); another unknown account tried against the same router and another one; a good login from the same address; a query with no filter (SR Linux's once-a-second warning fills the result) |
| `loki-link-flap` | intermediate | One link flapped: the port, the router at the other end, how often it went down, both addresses of the BGP session over it | Another port that went down once; a BGP session reset with no link down; the two routers on the link are SR Linux and FRR, with different log formats, and each names only the other's address |
| `loki-root-cause` | advanced | BGP sessions dropped after a commit: on which router, by which account, from where, what value it set, and which sessions it took down | Another account's harmless commit just before; the same account logging in to another router and only looking; a session that dropped for another reason; the value is only in the logged command of that login session |
| `loki-compromised-login` | expert | The source with the most failed logins across the routers: its failures per router, the router it got into, the account and the value it changed | Needs counting per router (an aggregate query); another source failing a few times; another account's commit on the same router after the attacker's; SR Linux writing two lines per failure |

Requirements: the lab and the `loki` service (Loki, Alloy, Grafana: about 0.4 GB). Answers go through
`submit_answer`; each task has a `script.yaml` with its reference solution as MCP calls. A fourth task, one
that needs an aggregate query, is an open item in `TODO.md`.

## Which tasks are kept

Most models tested here run locally, where one attempt can take minutes, so every task has to earn its place.
Each section (a tool such as `netbox`, or a group such as `cfg-mgmt`; the wider groupings are in
`sections/README.md`) has **four tasks, one per tier** (basic, intermediate, advanced, expert), and each one must
tell models apart. Four keeps a full run short (44 tasks), at a price: with one attempt per task a section's result
moves in quarters, so compare sections only on runs with `--repeat 3` or more. Where the server can write, at
least one of the four changes something.

- **The expert tier is headroom.** Once the strongest local models passed every basic, intermediate and advanced
  task (Qwen, on Ollama and on Strata), the benchmark could no longer tell them from anything better. Each expert
  task chains more steps, joins two sources (or two vendors), and sets more traps than the section's advanced
  one. Small models are expected to fail it; it is re-checked, like every tier, when stronger models arrive.

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

Cut to three per section, and moved to MCP servers (0.20): 19 tasks went, among them the full-configuration
SR Linux task and the three-way consistency task (a full configuration doesn't fit in a tool result, and
Oxidized has no MCP server), the LLDP cabling tasks, `nautobot-graphql` (the server's GraphQL tool leaves little
to get wrong), and the `mcp` section, whose tasks moved into their tools' sections. With the routers on an MCP
server too (0.21), `running-config-cli-frr` and `netconf-filtered-bgp` went: a whole configuration doesn't fit
in a tool result and no published server speaks NETCONF to SR Linux. `config-interface-frr` and
`bgp-peering-audit` took their places, and `config-section-bgp` now asks for the BGP facts, not the lines.

## Writing a task

A task is a folder with a `task.yaml`, optional `setup.sh` (runs before the attempt) and `oracle.sh` (reference
solution). The fields are described in [Grading](grading.md); copying one of the tasks above is the quickest start.
A task gives the model a shell unless it says `tools: {mcp: [<service>, ...]}`: then the model gets only
those services' MCP servers and `submit_answer` (the services must be under `requires.services`; `routers`,
the lab's own server, needs the routers under `requires.devices` instead; a check that
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
| `STICK_LIB` | Folder with shared helpers: `source "$STICK_LIB/common.sh"` gives `srl_set`, `srl_cli`, `frr_conf`, `frr_cli`, `netconf_get_config`, `oxidized_backup_now`, `netbox_api`, `netbox_id`, `nautobot_api`, `nautobot_id`, `librenms_api`, `librenms_add_device(s)`, `librenms_poll`, `librenms_wait_snmp`, `srl_snmp_community`, `gitea_api`, `gitea_commit`, `gitea_branch`, `gitea_file`, `zabbix_api`, `zabbix_add_host`, `zabbix_group_id`, `zabbix_poll`, `zabbix_wait_available`, `zabbix_wait_items`, `snmp_wait`, `srl_commit` (several SR Linux commands in one commit), `ssh_login` (a password login from a lab node), `loki_count`, `loki_lines`, `loki_wait`, `prom_value`, `prom_labels`, `prom_wait`, `telemetry_ready`, `pdns_api`, `pdns_zone`, `pdns_rrset`, `pdns_delete`, `pdns_records` |

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
- `sr_cli -ec` takes one command: several in one commit go through `srl_commit`. A new SR Linux user can log
  in only when its role has `services [ cli ]`, and a few seconds after the commit.
- OpenSSH 9.8 and later turns a source away after a few failed logins (`PerSourcePenalties`): a setup that
  needs each failure logged has to switch that off on the target, or stay under the threshold.
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
