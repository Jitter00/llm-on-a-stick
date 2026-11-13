# Notes for AI agents

For an agent (Claude Code, Codex, ...) that a user asks to run model tests with `stick`, or to work on this
repository. People: start with [README.md](README.md).

## Before you run anything

Work from the repository root: `stick` reads its settings from `.env` in the current folder and writes results to
`runs/` there. If `stick` is not on the PATH, use `uv run stick` instead.

Some things only the user can do. Check them first, and ask instead of working around them:

- **Credentials.** Paid models need a key or a local proxy, set in the shell or in `.env` (see `.env.example`).
  Don't create, read or edit `.env`, and never ask for a key in the chat. If a run says
  `no usable Anthropic credentials`, or `the Anthropic API key was rejected`, tell the user what to set.
- **Local model servers.** The user starts and stops them (Ollama, Strata, LM Studio...). `stick doctor --json`
  shows which servers answer and which models are loaded. Check that yourself before asking.
- **Money.** A run against a paid API costs money. Say which model and how many attempts
  (tasks x `--repeat`) before you start one the user didn't ask for in those terms. The same goes for a judge
  (`--judge-model`, `stick judge`): say which model, and the number of calls the command prints.
- **First-time setup** (Docker, containerlab, `stick image build frr`): README, "Install, step by step".
  `stick doctor` reports what is missing.

## Running tests

```bash
stick task list                                            # task ids and their sections
stick run --section cfg-mgmt --model anthropic/claude-haiku-5-5        # one model, one section
stick run netconf-filtered-bgp --model anthropic/claude-haiku-5-5      # one task: its id, no --section
stick run --all --model anthropic/claude-haiku-5-5 --repeat 3          # every task, three attempts each
stick vs anthropic/claude-haiku-5-5 ollama/gemma4:12b --section cfg-mgmt   # two models, side by side
stick judge runs/<name> --judge-model anthropic/claude-haiku-5-5       # why attempts failed (needs no lab)
stick env down                                             # stop everything when the user is done
```

- `stick run` and `stick vs` start the lab and the services the chosen tasks need, if they aren't running, and
  leave them running. Don't start them yourself first. Stop them with `stick env down` only when the user has
  finished: they may want to look at the lab.
- Pass `--runs-dir runs/<name>` with a new name for each batch, so its attempts stay apart from older ones.
- `--judge-model <provider/model>` on `stick run` or `stick vs` has a second model explain failed attempts
  and score how the tested model worked. It is refused when it is one of the tested models; don't work around
  that. It never changes pass, fail or score.
- Claude models run with thinking off unless you pass `--thinking`. The line `sampling: thinking ...` printed
  before the run says what was applied; some models can't turn it off.

### Rules

- **Never run two local models at the same time**, in one command or in two terminals: they share the GPU and
  RAM. `stick vs` refuses two local models. Run the first with `stick run`, have the user stop it and start the
  second, run that one into another folder, then compare with
  `stick report <folder-a> <folder-b> --html --out <file>.html`.
- **One `stick run` at a time.** There is one lab, and every attempt resets it.
- **Don't run `stick task validate` during a model run**: both use the same emulated AWS account.
- **Runs can be long.** A cloud model takes about 15 s per attempt, a local model several minutes, and a first
  start of NetBox or Nautobot adds about 2.5 minutes. Run anything bigger than one section in the background and
  wait for it to exit; don't cut it short with a command timeout.

## Reading the results

Don't parse the terminal table. Each run ends by printing two paths:

- `report-<model>-<what>-<time>.html`: the page for the user. Give them the `file://` address as printed.
- The `.json` file with the same name: the same numbers, for you.
    - `contenders[]`: one per model and setting, with `attempts`, `passed`, `mean_score`, `tokens_in`,
      `tokens_out`, `cost_usd`, `mean_wall_s`, `total_wall_s` (seconds, all attempts), `mean_turns`, and
      `sampling` (what was really sent). With a judge: `judge_score` (0..1, mean over `judge_attempts`),
      kept apart from `mean_score`.
    - `attempts{}`: one per attempt, with `task_id`, `outcome` (`pass`, `partial`, `fail`, `error`), `score`,
      `hints` (what probably went wrong), `checks` and `run_dir`. With a judge: `judge.summary` (why it
      didn't pass) and `judge.checks[]` (`score`, `scale`, `scores` per repeat, `agreement`, `reason`).
    - `judges`: the judge models used, if any.
    - `by_section[]` and `by_tier[]`: `name` and, per contender id, `tasks`, `attempts`, `passed`,
      `mean_score`. `max_repeats` is the most attempts any task got: at 1, a section moves in thirds.
    - `versus`: set only when there are two or three contenders: `wins` (task ids per contender, and `tie`),
      `top` (task ids where the contender was best or joint best), `only_passed_by` and `headline`.

Each attempt's folder (`run_dir`) holds `result.json` (outcome and every check), `metrics.json` (tokens, time,
`stop_reason`) and `transcript.jsonl` (every model turn and command). To explain why an attempt failed, read
`result.json`, then the transcript.

**Exit codes of `stick run` and `stick vs`:** `0` means every attempt ran and was graded, **not** that every
attempt passed. `1`: at least one attempt could not run. `2`: nothing started (wrong model or task name, server
unreachable, missing credentials). Take pass and fail from the `.json` file.

When you report to the user, give passed/attempts per model, name the tasks that failed with their hints, and
say which settings applied (`sampling`). Report judge scores apart from pass rates and as one model's opinion:
they have not been checked against human grading. Don't call a model better on the strength of one attempt per task.

## Working on the code

- Tests: `uv run pytest`. Don't add `-m`: `-m lab` deploys the real lab and starts services (several minutes).
  Lint and types: `uv run pre-commit run --all-files`.
- Commits and PR titles follow Conventional Commits; see [CONTRIBUTING.md](CONTRIBUTING.md).
- Start-up times, service details and known pitfalls: [docs/services.md](docs/services.md) and the "Known
  gotchas" list in [TODO.md](TODO.md). How runs and reports work: [docs/runner.md](docs/runner.md).
