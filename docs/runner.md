# Running models

`stick run` lets an AI model attempt tasks in the lab, grades every attempt and records what it cost. Every model
gets **the same instructions, the same single tool and the same limits**, so local and paid models can be compared
fairly.

```bash
uv run stick run running-config-cli-frr --model ollama/qwen3:14b
uv run stick run --section cfg-mgmt --model ollama/qwen3:14b --model anthropic/claude-sonnet-5-5 --repeat 3
uv run stick report                                   # compare everything in runs/
```

`stick run` (and `stick vs`) first starts whatever the chosen tasks need and isn't running yet: the lab, and
services such as Oxidized or NetBox (a first start of NetBox takes a few minutes). It leaves them running, so the
next run starts at once. `uv run stick env down` stops everything: the services, then the lab.

## Which models

A model is written `provider/model`. Any server that speaks the OpenAI chat-completions API with tool calling works.

| Provider | Example | Default address | Key (environment variable) |
|---|---|---|---|
| `ollama` | `ollama/qwen3:14b` | `http://127.0.0.1:11434/v1` | none |
| `lmstudio` | `lmstudio/qwen3-14b` | `http://127.0.0.1:1234/v1` | none |
| `strata` | `strata/deepseek-v4.1-flash` | `http://127.0.0.1:8080/v1` | none |
| `vllm` | `vllm/Qwen/Qwen3-14B` | `http://127.0.0.1:8000/v1` | none |
| `llamacpp` | `llamacpp/model` | `http://127.0.0.1:8080/v1` | none |
| `openai-compat` | `openai-compat/<model> --base-url http://host:port/v1` | (you give it) | `STICK_API_KEY` (optional) |
| `openai` | `openai/<model>` | OpenAI | `OPENAI_API_KEY` |
| `openrouter` | `openrouter/<vendor>/<model>` | OpenRouter | `OPENROUTER_API_KEY` |
| `anthropic` | `anthropic/claude-sonnet-5-5` | Anthropic | `ANTHROPIC_API_KEY` |
| `script` | `script/path/to/commands.yaml` | none: replays fixed commands | none |

Your server on another port or machine: `--base-url http://192.168.1.50:8080/v1`, or set it once with
`STICK_<PROVIDER>_BASE_URL`, e.g. `export STICK_STRATA_BASE_URL=http://127.0.0.1:9000/v1`. Ollama follows
`OLLAMA_HOST`, like the `ollama` command does. `stick doctor` shows
which local servers it can see and what they serve.

### Settings file (`.env`)

To avoid typing these variables each time, put them in a file named `.env` in the folder you run `stick` from:

```bash
cp .env.example .env      # then edit .env: uncomment the lines you need
```

[`.env.example`](https://github.com/Jitter00/llm-on-a-stick/blob/main/.env.example) lists every setting with its
default. `.env` is not committed to git. A variable already set in your shell wins over the file, and `stick`
prints one line naming the file and the settings it took from it.

**Don't put a real API key in `.env` if you can avoid it.** The file is plain text: any program running as you
can read it, and it is easy to leak through a backup or a mistaken commit. Two better options:

- **A local proxy that holds the key** (Linux), such as [keyveil](https://github.com/Jitter00/keyveil). The key
  stays encrypted on disk, the proxy adds it to each request, and `.env` then holds no secret:

    ```bash
    STICK_ANTHROPIC_BASE_URL=http://127.0.0.1:8787/anthropic
    ANTHROPIC_API_KEY=proxy-handles-auth      # a placeholder, not a key
    ```

    keyveil is a young project: read its threat model before relying on it. While it runs, any program on your
    machine can send requests through it (it can't read the key), so stop it when you're done.
- **A password manager**, exporting the key for the current terminal only, e.g.
  `export ANTHROPIC_API_KEY="$(pass show anthropic/api-key)"`.

Before anything runs, `stick run` checks that each server answers and serves the model you named (it lists what the
server has if not). **The model must support tool calling.** For Ollama, also set the context window to match the other models
(`OLLAMA_CONTEXT_LENGTH`, e.g. 65536); its default is small, and longer conversations are silently cut. Many small local models don't; their runs end with
`model-error` and the server's message in `metrics.json`.

API keys are only read from the environment. They are never written to the run folder.

## What the model gets

- **System prompt** (the same for every model, versioned as `system_prompt_version` in the metrics): it's a network
  engineer in a lab with one tool; its working directory is `/work`; commands have no terminal; it sees at most
  4,000 characters of each command's output; only what the task asks it to produce is checked, not its reply.
  It is kept short on purpose (see [Keeping the input small](#keeping-the-input-small)).
- **The task's prompt**, with this run's addresses, file paths and canaries filled in. Paths in the workspace are
  written `/work/...`: short, so a model can't fail a task by mistyping a long folder name.
- **One tool, `run_command`**, which runs a bash command in the **toolbox** container: `ssh`, `sshpass`, `curl`,
  `jq`, `python3` with `ncclient` and `boto3`, `netconf-console2`, `snmpget` and `snmpwalk`, and for the cloud
  sections `aws` and `terraform` (with its AWS provider, so `terraform init` needs no download). The toolbox shares
  the host's network, so it reaches the lab
  and the tools exactly like you do from your machine; the run's workspace folder (`<run>/work` on your machine)
  is mounted at `/work`.

The model never runs anything on your machine itself. The toolbox image is built automatically the first time,
and again when a new version of `stick` changes its tools (`uv run stick image build toolbox` builds it by hand).
It is about 1.5 GB, most of it the AWS CLI and Terraform's AWS provider. For a task that requires a service with
client settings (moto: `AWS_ENDPOINT_URL`, credentials, region), the toolbox gets them as environment variables.

### Keeping the input small

Most models tested here run locally, where reading the prompt is a large part of the time: every turn re-sends
the whole conversation, so one long command output is paid for again on every later turn. In the first
comparison (7 cfg-mgmt tasks × 3 attempts), Strata's deepseek-v4.1-flash read 4 million tokens and wrote 0.1
million. So the input is kept to what a task needs:

- a short system prompt (about 130 words) and short task prompts;
- at most 4,000 characters of each command's output. The model is told so, and is told to save long output to a
  file and read it in parts with `grep`, `head` or `sed -n`. Tasks are written so that nothing needs more: big
  outputs (a full NETCONF reply is ~300 KB) go to files and are graded there;
- the model's reasoning isn't sent back to OpenAI-compatible servers on the next turn (Anthropic's API requires
  its thinking blocks back, and handles them itself).

Earlier turns are never shortened or dropped afterwards: the conversation only grows at the end, so servers
that cache the prompt (llama.cpp, Strata, Ollama, Anthropic) re-read only the new part on each turn.

## Limits

| Limit | Default | Change it with |
|---|---|---|
| Turns (model replies) | the task's `limits.turns`, else 30 | `--max-turns` |
| Time for the whole attempt (**safety net only**) | 1 hour (or the task's `limits.time_s`, if larger) | `--timeout` |
| Tokens (read + written) | the task's `limits.tokens`, else none | task.yaml |
| One command | 60 s | `--cmd-timeout` |
| Output the model sees per command | 4,000 characters, about 1,000 tokens (head and tail kept, the gap marked) | `Settings.max_output_chars` |
| RAM kept free for your system | 2048 MiB: below it an attempt waits up to a minute, then stops (`low_memory`, not counted against the model) | `--min-free-ram` (0 = off) |

**The turns are the limit.** Time depends on your hardware: the same model passes on a fast GPU and runs out of
time on a slow one, and a `timeout` would say nothing about the model. So an attempt only stops on time after an
hour (a hung server, a machine far too slow), and the time taken is recorded and shown in `stick report` instead.
Expect long batches for big models that run partly in system RAM.

### Sampling (temperature)

You don't need to look up sampling settings yourself. For OpenAI-compatible servers, `stick run` picks them in
this order:

1. `--temperature X` on the command line: that temperature for every model, nothing else sent.
2. Otherwise the model's recommended settings from
   [`data/sampling.yaml`](https://github.com/Jitter00/llm-on-a-stick/blob/main/src/llm_on_a_stick/data/sampling.yaml),
   which lists common model families (Gemma, DeepSeek V4, Qwen3...) with the maker's published values and
   where they come from. It matches on the model name, so `ollama/gemma4:26b`, `strata/gemma-4-26b` and
   `openrouter/google/gemma-4-26b-it` all get Gemma's settings.
3. A model the file doesn't list: temperature 0.

`stick run` prints what each model gets before it starts (`sampling: temperature 1.0, top_p 0.95
(data/sampling.yaml: Gemma 4)`). The values are sent with every request and override the server's or model's
own defaults (an Ollama Modelfile's `temperature`, for example); anything not sent (`top_k`, `min_p`...) stays at
the server's defaults. Every attempt records what was used (`sampling`, `sampling_source`), and `stick report` shows
the same model at different settings on separate lines.

Missing a model, or a value out of date? Add or fix its entry in `data/sampling.yaml` (with its `source`) and
open a pull request.

Claude models don't take a temperature; use `--effort low|medium|high|xhigh|max` instead (default: the model's
own).

**Thinking is off by default for Claude models.** Recent Claude models think before answering unless told not to;
`stick run` tells them not to, so every model is compared at its plainest and a task shows whether it is hard
enough. Add `--thinking` to let the model think (its own default amount). Before the run, `stick` asks the model
once how it turns thinking off and uses the first way it accepts:

| What is sent | Models (examples) |
|---|---|
| thinking `disabled` | Claude Haiku 5.5, Opus 5 (only up to effort `high`) |
| thinking `between_tools` | Claude Sonnet 5.5 (only up to effort `high`) |
| nothing: thinking stays on | models that can't turn it off, such as Claude Opus 5.5 and Fable; also any model at effort `xhigh` or `max` |

Which one applied is printed before the run (`sampling: thinking disabled`) and recorded with every attempt, so the
report never shows a run as "thinking off" when the model was thinking. `--thinking` has no effect on other
providers: local servers each have their own switch for it.

## What gets recorded

Each attempt is a normal run folder (see [Grading](grading.md)) plus:

- `transcript.jsonl`: every model turn (text, tool calls, tokens, time) and every command (exit code, output,
  time), one JSON object per line;
- `metrics.json`, also copied into `result.json` under `metrics`:

| Field | Meaning |
|---|---|
| `model`, `provider`, `base_url` | Who was tested |
| `stop_reason` | `done` (the model said it had finished), `max_turns`, `timeout`, `token_limit`, `model_error`, `refusal`, `low_memory`, `output_limit` (cut off twice, see below), `empty_reply` (empty twice), `context_full` |
| `turns`, `tool_calls` | Model replies, and commands it asked for |
| `tool_errors` | Malformed tool calls: arguments that aren't JSON, an unknown tool name |
| `command_failures`, `command_timeouts`, `truncated_outputs` | Commands that exited non-zero, ran out of time, or printed more than the model was shown |
| `output_limit_hits`, `repetition_loops`, `nudges` | Replies cut off (at the output cap, or stopped as a loop), how many of them were loops, and the nudges sent |
| `sampling`, `sampling_source` | Sampling settings sent with every request, e.g. `{"temperature": 1.0, "top_p": 0.95}`, and where they came from (`data/sampling.yaml: Gemma 4`, `default`, `--temperature`) |
| `empty_replies` | Replies with no text and no command |
| `commands_not_run` | Commands from cut-off replies, refused because they may be incomplete |
| `tokens_in`, `tokens_out` | Tokens read (the whole conversation each turn) and written, summed over the attempt |
| `peak_context_tokens` | The biggest single turn: how much context window the task needed |
| `context_window` | The context window the server reported (Strata/llama.cpp: `n_ctx`; Ollama: the loaded model's `context_length`). Compare models at the same size. |
| `cost_usd` | From `data/prices.yaml` for API models; 0 for local servers; `null` if the price isn't known |
| `wall_s`, `model_s`, `tools_s` | Total time, time waiting for the model, time running commands |

The runner adds these failure hints to the grader's (see [Grading](grading.md#failure-hints)): `max-turns`,
`timeout`, `model-error`, `refusal`, `tool-call-error`, `no-tool-use`, `output-limit`, `repetition-loop`,
`empty-reply`, `context-full`, `answer-in-reply` (no output file, but the final reply quotes this attempt's canary: the model found the answer and
didn't save it where the task asked).

## When a reply is cut off or empty (loops)

Every reply may be at most **8,000 tokens**, thinking included, for every model. A normal turn here uses 100-2,000
and a whole config is under 3,000, so the cap only stops replies that have gone wrong. Some models, especially
local ones, sometimes get stuck while thinking and repeat the same lines until they reach the cap. Every model
gets the same treatment:

1. Replies from OpenAI-compatible servers (Ollama, Strata, vLLM...) are streamed and checked as they arrive: once
   the end of the reply keeps repeating itself, the runner stops it there (`stop_reason` of the turn:
   `repetition`) instead of waiting for the cap. That's seconds instead of minutes on a local model. The server
   doesn't report token counts for a stopped reply, so they are estimated (about 4 characters per token) and the
   turn is marked `usage_estimated` in the transcript. Anthropic replies are not streamed; they can only hit the
   cap.
2. The reply is recorded as cut off (`output_limit_hits`). If its end repeats itself, it also counts as a loop
   (`repetition_loops`).
3. If the reply had a command in it, the command is **not run**: it may be incomplete (half a script, an unclosed
   heredoc), and half a command could make half a change. The model gets an error instead (*"not run. Your reply
   was cut off at the output limit while writing this command, so it may be incomplete. Write shorter
   commands..."*) and carries on (`commands_not_run`).
4. If the reply had no command, the runner sends **one** message (a
   "nudge"), the same for every model: *"Your last reply was cut off without a tool call: it hit the output
   limit or kept repeating itself. Continue: run the next command, or reply with a short summary if you have
   finished."* It uses up a turn. A loop's text is not sent back to the model.
5. A reply that is **empty** (no text, no command: the model stopped mid-thought) gets the same treatment with
   *"Your last reply was empty: no text and no tool call. Continue: run the next command, or reply with a short
   summary if you have finished."* (`empty_replies`, hint `empty-reply`).
6. There is **one nudge per attempt**, shared by both cases. The next cut-off or empty reply without a command ends
   the attempt (`stop_reason: output_limit` or `empty_reply`), and the work is graded as it stands.

**When the conversation fills the context window**, the server cuts the reply off because there's no room left,
not because of the output cap: the prompt plus the reply reach the window (`context_window`). The model can't
continue in that conversation, so the attempt ends there (`stop_reason: context_full`, hint `context-full`)
without a nudge. Typically the model filled the conversation with very long commands or outputs.

The score only reflects the result: a model that recovers and does the job still passes. The cost of the loop
shows in the turns, tokens and time, and in the `output-limit` / `repetition-loop` hints in `stick report`.

## Comparing: `stick report`

```bash
uv run stick report                       # summary per model, then every attempt
uv run stick report --task config-section-bgp
uv run stick report --format md > results.md   # for a README, an issue or a blog post
uv run stick report --format json         # for your own analysis
```

The summary shows, per model: attempts, passes, mean score, tokens, cost, mean time and its most common problems.
The problems include hints from what the model did, such as `wrong-dialect` or `no-verification`
([Grading](grading.md#failure-hints)); they never change the score. To see them for attempts recorded before
these rules existed, without changing anything:

```bash
uv run stick hints runs/compare            # one row per attempt: recorded hints, transcript hints
```

### The HTML report

`stick run` ends by writing a report of **that run only** into the runs folder and prints its address to click
(`--no-report` skips it). The file is named after what ran, e.g.
`report-claude-haiku-5-5-cfg-mgmt-20261110T140706Z.html`, so reports in one folder don't overwrite each other, and a
run of one model never turns into a comparison with older runs lying in the same folder. `stick report --html`
writes it for runs you already have:

```bash
uv run stick report runs/compare --html                    # -> runs/compare/report.html
uv run stick report runs/haiku runs/gemma --html --out vs.html --title "Zabbix: Haiku vs Gemma"
```

It is one self-contained file (no network needed, so you can mail it or attach it to an issue) with:

- **What a turn is**, at the top: one reply from the model, in which it asks for commands or says it has
  finished, and how many turns an attempt may use in these runs.
- **Scores**: per model, attempts passed, mean score, time, turns, tokens and cost.
- **Tasks**: one square per attempt (pass, partial, fail, error); select a square to open that attempt.
- **Where it struggled**: what the model never or only sometimes passed, how its attempts ended, the failure
  hints by how many attempts had them, and the checks that failed most, with the grader's message. This comes
  from the recorded results by fixed rules; no model writes it.
- **Attempts**: each attempt's checks (expected and observed for the failed ones), metrics, prompt and the whole
  conversation: what the model said, every command, its exit code and output.

With two models in the data the page puts them side by side and says which did better on each task (pass rate
first, then mean score). `report.json` next to it has the same numbers without the transcripts. The transcripts
contain the lab's logins and API tokens; they only work inside the lab.

## Head to head: `stick vs`

```bash
uv run stick vs anthropic/claude-haiku-5-5 ollama/gemma4:12b --section zabbix --repeat 3
```

Runs both models on the same tasks and writes the side-by-side `report.html`, into
`runs/vs-<a>-vs-<b>-<time>/` unless you give `--runs-dir`. It takes the options of `stick run`. `--base-url`
applies to both models, so with two providers set the address per provider instead, e.g.
`STICK_OLLAMA_BASE_URL=http://192.168.122.1:11434/v1` (in your shell or in [`.env`](#settings-file-env)).

The two models run one after the other, the first one's whole batch before the second. Two local models can't
share the GPU and RAM, so `stick vs` refuses that pair: run each with `stick run` into its own folder and compare
with `stick report <folder> <folder> --html`. A cloud model and a local model don't compete for the machine and
could run at the same time, but all attempts still share the one lab (the same routers, one instance of each
tool), and two attempts at once would undo each other's work. Running that pair in parallel needs a lab per model
first; it's on the roadmap.

## A scripted "model"

`--model script/<file.yaml>` runs fixed commands instead of asking a model. It's how the tests prove the runner and
a task work together, and a quick way to check your own task end to end:

```yaml
commands:
  - sshpass -p admin ssh admin@{{ nodes.frr2.mgmt_ip }} "show running-config" > {{ workspace }}/frr2.cfg
final: Saved frr2's running config.
```

## Local models and your machine

!!! warning "Local models run one after another, never in parallel"
    `stick run` runs one attempt at a time, model by model, and refuses two local models in one command:
    **several local models must never run at the same time**: they
    compete for the same GPU and RAM (one may not even load), and the timings become meaningless. To compare local
    models, run one model's batch, stop that server, then run the next model's batch:

    ```bash
    uv run stick run --section cfg-mgmt --model strata/deepseek-v4.1-flash --repeat 3 --runs-dir runs/compare
    # stop Strata, then:
    uv run stick run --section cfg-mgmt --model ollama/gemma4:26b --repeat 3 --runs-dir runs/compare
    uv run stick report runs/compare
    ```

A local model is busy the whole time `stick run` works: in a chat it generates for a few seconds and then waits for
you, but an agent sends turn after turn. Expect the GPU (and, for models partly kept in system RAM, all CPU cores)
to stay at full load for the whole batch. Two local servers usually can't share one GPU: run their batches one after
the other, stopping the first server in between. `--min-free-ram` (default 2048 MiB) stops an attempt before the
system runs out of memory.

## Platforms

The toolbox uses Docker's host networking to reach the lab's management addresses: Linux and WSL2. On macOS the lab
addresses aren't reachable from the host, so `stick run` is not supported there yet (see [Platforms](platforms.md)).
