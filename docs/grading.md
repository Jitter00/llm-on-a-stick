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
4. **Rules for the judge** (it arrives after the model runner):
    - it is **never the model being tested** (refused unless explicitly overridden);
    - it **never overrides code**: if the code says the BGP session is down, no judge turns that into a pass;
    - its score is reported **separately** from the code score, never mixed in;
    - it grades against a written rubric and a reference answer, **without knowing which model** produced the answer;
    - it runs at temperature 0 and repeats each judgement, so disagreement shows up;
    - the judge model and version are recorded in `result.json`;
    - it's optional: without a judge, judge-only checks show as "not graded" and the code score stands.
5. **Calibration**: a small set of human-graded examples per kind of judged check, to measure how often a judge
   agrees with people before its scores are trusted.

All checks available today are code checks.

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

More (wrong CLI dialect, giving up...) will come from analysing transcripts.

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
| `netbox_object` | `endpoint`, `filters`, `count` or `min` | NetBox has exactly `count` (or at least `min`) matching objects |

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

The format is described by a JSON schema shipped with the package:
`src/llm_on_a_stick/data/result.schema.json`. After changing `grading/results.py`, regenerate it with:

```bash
uv run python -c "import json; from llm_on_a_stick.grading.results import Result; s = Result.model_json_schema(); s['\$id'] = 'https://github.com/Jitter00/llm-on-a-stick/schemas/result.schema.json'; print(json.dumps(s, indent=2))" > src/llm_on_a_stick/data/result.schema.json
```
