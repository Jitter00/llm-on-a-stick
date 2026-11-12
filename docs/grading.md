# Grading

The grader looks at the **live lab** after an agent has worked on a task and decides, check by check, whether the
work was done, and if not, *why not*. It reads device state directly from the containers (`docker exec`), never
through the agent's own path, so a broken SSH session or API call can't hide or fake anything.

## Grading policy: code first

Results must not depend on which AI model does the grading, so **code decides pass or fail** wherever it can.

1. **Code checks for everything that leaves a trace**: device config and state, NetBox/DNS/DHCP objects, backups,
   files the agent wrote, and changes it shouldn't have made. Every task has these, and only these decide its
   `outcome` and `score`.
2. **Structured answers instead of prose.** A diagnosis task asks for a machine-readable answer, for example
   `answer.json` with `{"device": "frr2", "interface": "eth1", "cause": "mtu-mismatch"}` from a fixed list of causes,
   graded exactly by `json_file_matches`. A free-text explanation can be asked for as well, but it's extra.
3. **An AI judge only where code can't grade**: the quality of a written explanation, a change plan or a ticket
   summary; parts of *how* the agent worked that a log can't show (a safe approach, asking before doing something
   ambiguous or risky); and plain-language failure summaries for the report (these aren't scored).
4. **Rules for the judge** (see [The judge model](#the-judge-model) for what exists):
    - it is **never the model being tested**: refused, and there is no option to allow it;
    - it **never overrides code**: if the code says the BGP session is down, no judge turns that into a pass;
    - its score is reported **separately** from the code score, never mixed in;
    - it grades against a written rubric (and a reference answer, when the task gives one), **without knowing
      which model** produced the answer;
    - it repeats each judgement, so disagreement shows up, at temperature 0 where the server takes one;
    - the judge model and the settings sent to it are recorded in `result.json`;
    - it's optional: without a judge, judge-only checks show as "not graded" and the code score stands.
5. **Calibration**: a small set of human-graded examples per kind of judged check, to measure how often a judge
   agrees with people before its scores are trusted. **Not built yet**: until it is, read judge scores as one
   model's opinion.

## The flow

```bash
uv run stick task start <task>    # prepares a run and prints the prompt for the agent
# ... any agent (or you) does the work ...
uv run stick grade                # grades the latest run and writes result.json
```

This works with any agent: a model driven by llm-on-a-stick's own runner (coming next), an external agent such as
NetClaw or Claude Code, or a person.

`stick task start` creates a run folder under `runs/`:

| Path | What it is |
|---|---|
| `run.json` | Task id, canary values, the rendered prompt, timestamps |
| `work/` | The agent's workspace: files the task asks for go here |
| `baseline/` | Every router's config right after setup, used to spot changes the agent shouldn't have made |
| `setup.log` | Output of the task's setup script |
| `result.json` | Written by `stick grade` |

`stick grade` exits with 0 for a pass, 1 for a fail or partial, and 2 if grading itself failed (lab down, bad task).

## Try it yourself: be the agent

With the lab running, start the simplest real task (see [Tasks](tasks.md) for all of them):

```bash
uv run stick task start running-config-cli-frr
```

Follow the printed prompt yourself: SSH to frr2 and save its running config into the workspace file it names, for
example:

```bash
ssh admin@clab-stick-base-frr2 "show running-config" > runs/<run folder>/work/frr2.cfg   # password: admin
uv run stick grade
```

Then try failing on purpose: save only part of the config, or add a made-up line, and grade again.

## Canary values

Each run generates random values (an ASN, an IP, a description...) that the task's setup script puts on the devices
before the agent starts. Checks then expect those exact values back, so a model can't pass by reciting a typical
config from memory or inventing a plausible one.

| Kind | Example | Use |
|---|---|---|
| `asn` | `65123` | a private 2-byte ASN |
| `ipv4` | `198.18.42.7` | an address (RFC 2544 benchmarking range, 198.18.0.0/16) |
| `description` | `stick-3fa9c01e` | interface or neighbour descriptions |
| `hostname` | `stick-qkzpta` | device names (NetBox, LLDP system names) |
| `net24` | `198.19.117` | the first three octets of a /24 pool: `{{ canaries.pool }}.0/24` (198.19.0.0/16, never overlaps `ipv4`) |
| `net16` | `10.93` | the first two octets of a /16 for a VPC: `{{ canaries.vpc }}.0.0/16` (10.64 to 10.127) |

## Outcomes and scores

- **pass**: every check passed.
- **partial** / **fail**: some or none passed. `score` is the weighted share of passed checks (0 to 1).
- **error**: a check couldn't run (lab down, service not running, mistake in the task). Not the model's fault, and
  excluded from model comparisons.

## Failure hints

Every failed check says what it expected, what it found, and gives one or more hints:

| Hint | Meaning |
|---|---|
| `no-output` | The expected file was missing or empty |
| `truncated-output` | The output is a strict subset of the real config (cut off, pager not handled) |
| `hallucinated-value` | The output contains lines or values the device doesn't have |
| `wrong-format` | The output barely resembles what was asked for (wrong command, error text, wrong format) |
| `unfiltered-output` | Asked for one part, got more (the whole config instead of the BGP section, an unfiltered NETCONF reply) |
| `incomplete-config` | The device is missing configuration the task asked for |
| `wrong-config` | Device state differs from what was asked (e.g. a BGP session isn't established) |
| `collateral-change` | A device the task didn't allow to change was changed |
| `missing-object` | An expected object wasn't found (NetBox object, Oxidized backup) |
| `env-error` | The grader or lab failed; not counted against the model |

`stick run` adds hints from the transcript ([Running models](runner.md)):

| Hint | Meaning |
|---|---|
| `max-turns` | The model was still working when it ran out of turns |
| `timeout` | The attempt hit its token limit, or the 1-hour safety time limit (a hung server or a very slow machine) |
| `model-error` | The model server failed (HTTP error, unreachable, no tool support) |
| `refusal` | The model declined the task |
| `tool-call-error` | Malformed tool calls: arguments that aren't JSON, an unknown tool |
| `no-tool-use` | The model answered without running a single command |
| `output-limit` | A reply hit the output-token cap; the model got one nudge to continue (see [Running models](runner.md#when-a-reply-is-cut-off-loops)) |
| `repetition-loop` | The cut-off reply was the model repeating itself |
| `empty-reply` | A reply with no text and no command; the model got one nudge to continue |
| `context-full` | The conversation filled the model's context window; the attempt ended there |
| `answer-in-reply` | No output, but the final reply quotes this attempt's canary: the answer was found, not delivered |

It also reads **what the model did**: these rules look at the commands and their output in
`transcript.jsonl` (`grading/transcript.py`). They are **hints only**: they never change `outcome` or `score`, so
a passed attempt can carry one too ("passed, but never checked its output").

| Hint | Meaning |
|---|---|
| `wrong-dialect` | It sent another OS's CLI syntax to a node (e.g. `show configuration` to SR Linux) and the node rejected it, at least twice. One rejected probe that the model then corrects is exploring, not a dialect problem |
| `attempted-change` | On a task with `no_change_outside`, it sent config-mode commands (`enter candidate`, `commit now`, `conf t`, `write memory`, NETCONF `<edit-config>`) to a node it may not change, whether or not the change stuck. Search patterns (`grep 'commit'`) don't count |
| `no-verification` | A file the checks read was written (`>`, `tee`, `-o`, `sed -i`, Python `open(..., 'w')`) and never read back afterwards (`cat`, `head`, `wc`, `grep`, `jq`, `ls -l`, Python `open(...)`...). Not for files that ended up missing or empty: `no-output` says that |
| `ignored-error` | The model said it had finished although a file the checks read holds an error message, or the last command writing it failed (timed out, or its output shows a device, NETCONF, shell or Python error). Exit codes alone don't count: `grep -c` with no match exits 1 |

`stick hints <run folders>` shows these for past attempts without changing their `result.json`.

More (giving up, hallucinated APIs...) can come from the same transcripts; the classes still to do are in TODO.md
("Failure classifier").

## The judge model

A second model that reads a finished attempt and does two things code can't:

- **Scores the task's `llm_judge` checks** against their rubrics. Today the five NetBox tasks have one each,
  about *how* the model worked: did it read before writing, look ids up or guess them, confirm its result.
- **Says why an attempt didn't pass**, in a few sentences, for every attempt whose outcome isn't `pass`. This
  summary is not scored.

```bash
uv run stick run --section netbox --model ollama/gemma4:12b --judge-model anthropic/claude-haiku-5-5
uv run stick judge runs/compare --judge-model anthropic/claude-haiku-5-5   # attempts you already have
uv run stick grade --judge-model anthropic/claude-haiku-5-5                # after an attempt made by hand
```

`stick run` and `stick vs` call the judge after each attempt is graded. `stick judge` does the same for run
folders made earlier: it needs no lab, because it only reads the folder (the prompt, `transcript.jsonl`, the
workspace, `result.json`). It skips attempts this judge has judged already; `--force` judges them again. A
judge on a paid API costs money: the commands print how many times the judge will be asked before they start
(each `llm_judge` check `--judge-repeats` times, 3 by default, plus one summary per attempt).

What the code guarantees:

- **Code decides.** `outcome`, `score`, `checks` and `failure_hints` are never changed by the judge. Its answers
  go into `result.json` under `judge`, and reports show them under their own heading and in their own column.
- **Never the tested model.** A judge with the same model name as the model that made the attempt is refused,
  also through another provider (`ollama/x` and `strata/x`). No option turns this off. An attempt made by hand
  (`stick task start`) records no model, so there is nothing to compare with.
- **Blind.** The judge gets the task prompt and what the candidate did and saw; not the model's name, the
  metrics, the outcome or the score. For the failure summary it also gets the failed checks and the hints.
- **Repeated.** Each check is asked `--judge-repeats` times. The score is the median; `scores` lists every
  repeat and `agreement` is the share that gave the most common score (1.0: all agreed).
- **Recorded.** `judge.model`, `judge.sampling` (what was really sent: temperature 0 for servers that take a
  temperature; Claude models take none and run with thinking off), tokens and cost.
- **Optional.** Without `--judge-model` the task's judge checks are listed as `not-graded`.

Limits to keep in mind: there is no calibration set yet, so nobody has measured how often a judge agrees with
people. A transcript longer than about 120,000 characters is given to the judge with its middle turns left out
(each command output is cut to 2,000 characters first), so the judge can miss what happened there.

### Judge checks in a task

```yaml
checks:
  - type: llm_judge
    name: how it went about the lookup
    params:
      artifact: transcript        # or `reply` (the final reply), or a file in the workspace, e.g. notes.md
      rubric: |
        Judge how the candidate went about the task, not whether the end result is right (code checks that).
        5: found the device with targeted API queries and checked the file it wrote.
        3: got to an answer by reading long unfiltered lists, or never checked what it wrote.
        1: guessed or invented values instead of reading them.
        Use 2 and 4 for attempts in between.
      reference: "..."            # optional: what a good answer looks like
      scale: 5                    # optional: scores run from 1 to this (2 to 10)
```

`rubric` and `reference` can use `{{ canaries.<name> }}` and `{{ workspace }}`. A task needs at least one code
check next to its judge checks, `weight` has no effect on a judge check, and `stick task validate` ignores
them (the reference solution has no transcript). When the artifact doesn't exist (the file wasn't written, the
run has no transcript), the check stays `not-graded` and says why.

## Built-in checks

Use these in a task's `checks:` list. Parameters can use `{{ canaries.<name> }}`, `{{ workspace }}` and
`{{ nodes.<node>.mgmt_ip }}`.

| Check | Parameters | Passes when |
|---|---|---|
| `file_exists` | `path` | The workspace file exists and isn't empty |
| `file_contains` | `path`, `lines` | Every line appears in the file (whitespace-insensitive) |
| `file_matches_running_config` | `node`, `path`, `format` (`flat` or `tree`, SR Linux only), `ignore` (regexes) | The file is the node's complete running config: same lines, any order |
| `json_file_matches` | `path`, `expected` (object) | The file is a JSON object with those keys and values (extra keys allowed; list and key order don't matter) |
| `file_matches_config_section` | `node`, `path`, `section` | The file is exactly one section of the running config: SR Linux flat lines starting with `section`, or FRR's block starting with `section` up to its `exit` |
| `xml_file_xpath` | `path`, `expect` (XPath → text, `"*"` = exists) | The file is a NETCONF reply (bare `<data>`, `<rpc-reply>` or a session dump) and each path finds that text; namespaces are ignored |
| `xml_file_absent` | `path`, `xpaths` | None of the paths match: proves a NETCONF filter was really used |
| `running_config_contains` | `node`, `lines`, `format` | The device's running config contains every line |
| `bgp_session` | `node`, `peer`, `state` (default `established`) | The BGP session to `peer` is in that state |
| `no_change_outside` | `allowed` (list of nodes) | No other router changed since `stick task start` |
| `oxidized_has_backup` | `node`, `min_versions`, `contains` | Oxidized has a successful backup (with that many versions, containing those lines) |
| `netbox_object` | `endpoint`, `filters`, `count` or `min`, or `expect` | NetBox has exactly `count` (or at least `min`) matching objects. With `expect` (`{"role.slug": leaf, "primary_ip4.address": ...}`), exactly one matches and has those values (dotted paths into the API's JSON; choice fields such as `status` compare their value) |
| `netbox_unchanged` | `allow_new` (endpoints, e.g. `[dcim/devices]`) | Nothing in NetBox changed or was deleted since `stick task start`, and nothing was added except on `allow_new`. Needs `netbox` in the task's `requires.services` (the start saves `baseline/netbox.json`) |
| `nautobot_object` | as `netbox_object` | The same, against Nautobot. Related objects are expanded one level (`?depth=1`), so `expect` names them (`{"role.name": Leaf, "status.name": Active}`); `filters: {depth: 2}` goes one level further (`cable_peer.device.name`) |
| `nautobot_unchanged` | `allow_new` | As `netbox_unchanged`, for Nautobot (`baseline/nautobot.json`; e.g. `allow_new: [ipam/ip-address-to-interface]`) |
| `nautobot_graphql` | `path`, `must_contain`, `must_not_contain` | The workspace file `path` holds a GraphQL query that Nautobot answers without errors, and its result holds every `must_contain` value and none of `must_not_contain` (any field, anywhere in the result) |
| `aws_query` | `command`, `query` (JMESPath), and one of `expect`, `count`, `min` | `aws <command>` against the emulated account, reduced with `query`, equals `expect` (lists in any order), or is a list of exactly `count` or at least `min` items. An AWS error (no such resource) fails. The command runs in bash, so it can look up an id: `--filters Name=vpc-id,Values=$(aws ec2 describe-vpcs ... --output text)` |
| `aws_policy_grants` | `command`, `query`, `grants` (list of `[effect, action, resource or principal]`), `resolve` | The IAM policy document found there grants exactly those permissions: none missing, none more (a wildcard is more). Statements may be split or merged; conditions are ignored. Works for a trust policy: `[Allow, "sts:AssumeRole", ec2.amazonaws.com]`. For an ARN only the account knows, `resolve` maps a name to an `aws` command that prints it (`CMK: kms describe-key --key-id alias/x --query KeyMetadata.Arn`) and the grants write `<CMK>` |
| `aws_reachable` | `instance` (Name tag), `port`, `source` (an internet address, default `198.51.100.10`), `reachable` (default `true`) | A TCP connection from `source` to `port` on that running instance would get through, judging by the account's state (the emulator carries no packets): the instance has a public address, its subnet's route table sends `source` to an internet gateway attached to the VPC, the subnet's network ACL lets the port in and the replies (TCP 1024-65535) out, and one of the instance's security groups allows it. However it was fixed counts. With `reachable: false`: it would not get through |
| `aws_unchanged` | `allow_new`, `allow_changed`, `allow_deleted` | Nothing in the account was added, changed or deleted since `stick task start`, except what the lists allow: a kind (`ec2/subnets`) or one resource as `kind:label` (`ec2/security-groups:web`), the label being its Name tag, else its name, else its id. Kinds: `ec2/vpcs`, `subnets`, `route-tables`, `internet-gateways`, `security-groups`, `network-acls`, `instances`, `volumes`, `snapshots`, `images`, `addresses`; `iam/roles`, `policies`, `instance-profiles`, `users`; `s3/buckets`; `sqs/queues`. Needs `moto` in `requires.services` (`baseline/moto.json`) |
| `terraform_plan_clean` | `path` (a workspace directory) | `terraform plan` there reports no changes: configuration, state and account agree (it refreshes, so manual changes show). A plan that fails (not initialised, invalid) fails the check |
| `terraform_state_has` | `path`, `addresses`, `types`, `count` | The state there manages every address (`aws_subnet.app["a"]`), at least that many resources of each type (`{aws_subnet: 2}`, whatever their names), and exactly `count` resources |
| `librenms_device` | `hostname`, `expect`, `poll` (default true) | LibreNMS monitors the device (the address it was added with) and, after a poll the grader forces, its fields have those values (`{status: 1, os: srlinux, community: ...}`; `status: 1` = reached over SNMP) |
| `librenms_absent` | `hostname` | LibreNMS does not monitor it |
| `librenms_alert` | `rule`, `devices`, `count`, `severity` | Exactly one rule has that name (and severity), and after a poll of every device it has active alerts on exactly those devices, `count` in all (one per matching port) |
| `librenms_unchanged` | `allow_new`, `allow_changed`, `allow_deleted` | Devices (how they are monitored), alert rules and device groups match `baseline/librenms.json`, except what the lists allow: a kind (`devices`, `rules`, `groups`) or `kind:label` (`devices:172.30.30.11`, `rules:name`). A device deleted and re-added counts as deleted. Needs `librenms` in `requires.services` |
| `zabbix_host` | `ip`, `expect`, `poll` (default true), `wait_s` (45) | Zabbix has a host whose SNMP interface is at that address and, after a poll the grader forces, it has those values: `host`, `status` (0 = enabled), `community` (macros resolved), `snmp_version`, `available` (1 = Zabbix reached it over SNMP), `groups` and `templates` (lists: at least these) |
| `zabbix_absent` | `ip` | Zabbix has no host with an SNMP interface there |
| `zabbix_problem` | `trigger`, `hosts`, `severity` (0-5), `wait_s` (40) | Exactly one trigger made by hand has that name (and severity), it is enabled and on exactly those hosts, and after a poll of its items it has one open problem |
| `zabbix_maintenance` | `name`, `hosts`, `duration_s`, `data_collection` (default false), `tolerance_s` (300), `wait_s` (100) | Exactly one maintenance has that name and type, it ends `duration_s` after it was made (between the start of the run and now), and Zabbix really has exactly those hosts in it (it works that out once a minute) |
| `zabbix_unchanged` | `allow_new`, `allow_changed`, `allow_deleted` | Hosts (how they are monitored), hand-made triggers, maintenances, host groups and global macros match `baseline/zabbix.json`, except what the lists allow: a kind (`hosts`) or `kind:label` (`hosts:srl1`, `triggers:my trigger`) |


The cloud checks have no AWS client of their own: they run `aws`, `terraform` and a boto3 script in a throwaway
container of the toolbox image, so the grader reads the account independently of the attempt's container.

Example from a `task.yaml`:

```yaml
canaries:
  host_desc: description
setup: setup.sh          # gets STICK_CANARY_HOST_DESC and STICK_NODE_FRR1 (the container name)
checks:
  - type: file_matches_running_config
    name: frr1.cfg is frr1's running config
    params: {node: frr1, path: frr1.cfg}
    weight: 3
  - type: file_contains
    params: {path: frr1.cfg, lines: ["description {{ canaries.host_desc }}"]}
  - type: no_change_outside
    params: {allowed: []}
```

## Adding your own checks

A check is a Python function registered with `@check("name")` that returns a `Verdict`
(see `src/llm_on_a_stick/grading/checks/builtin.py` for examples). To ship checks in your own package, declare an
entry point in the `llm_on_a_stick.checks` group pointing at the module that defines them.

## result.json

`outcome`, `score`, `checks` and `failure_hints` come from the code checks. `judge` is there when the task has
judge checks or a judge has run, and is otherwise `null`:

| Field | Meaning |
|---|---|
| `judge.model` | The judge, `provider/model`; `null` when no judge has run |
| `judge.checks[]` | Per `llm_judge` check: `name`, `status` (`graded`, `not-graded`, `error`), `artifact`, `scale`, `score` (the median), `scores` (every repeat), `agreement`, `reason` |
| `judge.score` | Mean of the graded checks, each put on 0..1 (1 on the scale is 0, the top is 1). Not part of `score` |
| `judge.summary` | Why the attempt didn't pass; empty on a pass |
| `judge.sampling`, `judge.repeats` | What was sent to the judge, and how often each check was asked |
| `judge.tokens_in`, `judge.tokens_out`, `judge.cost_usd`, `judge.judged_at` | What judging this attempt took |

The format is described by a JSON schema shipped with the package:
`src/llm_on_a_stick/data/result.schema.json`. After changing `grading/results.py`, regenerate it with:

```bash
uv run python -c "import json; from llm_on_a_stick.grading.results import Result; s = Result.model_json_schema(); s['\$id'] = 'https://github.com/Jitter00/llm-on-a-stick/schemas/result.schema.json'; print(json.dumps(s, indent=2))" > src/llm_on_a_stick/data/result.schema.json
```
