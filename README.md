# llm-on-a-stick

**One eval harness, many LLMs. Start poking.**

llm-on-a-stick is a free, open-source benchmark that tests how well AI models (LLMs) handle real network engineering
work: pulling router configs over CLI and NETCONF, keeping NetBox and Nautobot in sync with the network, fixing
monitoring in LibreNMS and Zabbix, and working with the AWS CLI and Terraform. You run it on your own machine,
against a small virtual network, and compare a local model (for
example one running in Ollama) with a paid one. It tells you **why** a model fails (wrong CLI syntax, made-up API
fields, changing things it shouldn't), not just a score.

> **What works today:** the virtual lab; the `stick` command; six tools around it (NetBox, Nautobot, LibreNMS,
> Zabbix, Oxidized, and an emulated AWS account for the AWS CLI and Terraform); **40 tasks** in eight sections,
> from getting router configs right over CLI and NETCONF to keeping NetBox in sync and fixing monitoring, and
> the same tools through their MCP servers instead of a shell; the
> **grader**, which checks every attempt and explains what went wrong; and the **runner**, which lets AI models
> attempt the tasks and compares the results in a report. Start with the [Quick start](#quick-start). What comes
> next: [Roadmap](#roadmap).

**Contents:** [Quick start](#quick-start) · [What you need](#what-you-need) · [Install](#install-step-by-step) ·
[Your first lab](#your-first-lab-about-10-minutes) ·
[Run a model](#run-a-model) · [Commands at a glance](#commands-at-a-glance) · [Cheat sheet](#cheat-sheet) ·
[Run the tests](#run-the-tests-yourself) · [Troubleshooting](#troubleshooting) · [Glossary](#glossary)

## Quick start

One model, one section, one report. For when you already have Docker, containerlab and uv, and a model server
such as [Ollama](https://ollama.com) running. (Missing any of them? Start at
[Install, step by step](#install-step-by-step).)

```bash
git clone https://github.com/Jitter00/llm-on-a-stick.git
cd llm-on-a-stick
uv sync
uv run stick doctor                                            # checks your machine and lists your models
uv run stick image build frr                                   # once, about a minute
uv run stick run --section cfg-mgmt --model ollama/gemma4:12b  # five tasks, one model
```

`stick run` starts the lab and the tools the tasks need, lets the model attempt the five config management
tasks, and prints the address of a report page: what passed, and why the rest failed. The first run also
downloads and builds about 2.5 GB of container images, so it takes longer than the ones after it.

Two things to know before you trust the result:

- **Give the model enough context.** Ollama's default can be as small as 4k, and these tasks need far more:
  start it with `OLLAMA_CONTEXT_LENGTH=65536`. Details in [Run a model](#run-a-model).
- **Any model with tool calling works**: use a name `stick doctor` lists, or a paid model such as
  `anthropic/claude-haiku-5-5` with its API key set.

Next: [compare two models](#commands-at-a-glance), or look around the lab yourself in
[Your first lab](#your-first-lab-about-10-minutes).

## The lab

A small leaf/spine network that runs entirely in containers on your machine. No vendor accounts or licences needed.

```
       srl1 (AS65001)      srl2 (AS65002)       Nokia SR Linux (spines)
         |      \          /      |
         |       \        /       |
       frr1 (AS65101)    frr2 (AS65102)         FRRouting (leaves)
         |                        |
         h1 10.1.1.10/24          h2 10.1.2.10/24   Linux hosts
```

eBGP everywhere; the leaves advertise their host subnets, so h1 can ping h2 across the fabric. Next to it you can run
tools such as NetBox and Oxidized, connected to the lab's management network like they would be in a real network.

## What you need

| | |
|---|---|
| **Operating system** | Linux (Ubuntu, Debian, Fedora...) or Windows 11 with WSL2. On a Mac you can bring up the lab but not run models against it yet; the way round is a Linux virtual machine on the Mac (see [docs/platforms.md](docs/platforms.md)). |
| **Memory (RAM)** | About 6 GB free for one section, about 11 GB to run every section at once (`--all`). The lab uses ~4 GB; each tool adds its own: NetBox ~1.5 GB, Nautobot ~1.3 GB, Zabbix ~1.3 GB, LibreNMS ~0.8 GB, the emulated AWS account ~0.2 GB, Oxidized ~50 MB. A model running on the same machine needs its own memory on top. `stick doctor` shows what fits. |
| **Disk** | About 10 GB free for the container images. |
| **Internet** | For the first download of images and tools. |

You don't need to know Python. Everything below is copy and paste.

## Install, step by step

Open a terminal. On Windows, open your WSL2 (Ubuntu) terminal and run everything there. These steps are for Linux
and WSL2; steps 1 and 2 don't apply on a Mac, which needs Docker Desktop or OrbStack instead (or follow all the
steps inside a Linux virtual machine).

### 1. Docker

Docker runs the lab devices and the tools as containers.

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```

The second line lets you use Docker without `sudo`. **Log out and log back in** (or restart WSL with
`wsl --shutdown` from Windows) so it takes effect.

**Check it worked:** `docker run --rm hello-world` prints "Hello from Docker!".

(Prefer your distribution's own instructions? See <https://docs.docker.com/engine/install/>.)

### 2. containerlab

containerlab builds the virtual network (devices plus the links between them).

```bash
bash -c "$(curl -sL https://get.containerlab.dev)"
sudo usermod -aG clab_admins $USER
```

The second line lets you start labs without `sudo`. **Log out and log back in** again.

**Check it worked:** `containerlab version` prints a version number.

### 3. uv

uv installs Python and everything this project needs, in a private folder that doesn't touch the rest of your system.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Close and reopen the terminal.

**Check it worked:** `uv --version` prints a version number.

### 4. Get llm-on-a-stick

```bash
git clone https://github.com/Jitter00/llm-on-a-stick.git
cd llm-on-a-stick
uv sync
```

`uv sync` downloads the right Python version and the project's dependencies (first time: a minute or so).

**Check it worked:** `uv run stick --help` lists the available commands.

**Install `stick` as a command**, so that you type `stick ...` from now on, without `uv run` in front:

```bash
uv tool install --editable .
```

`--editable` makes the command follow this folder, so a `git pull` updates it. **Check it worked:** `stick --help`
prints the same list. If the terminal says `stick: command not found`, run `uv tool update-shell` and open a new
terminal.

The rest of this page uses the installed command. Run every command from inside the `llm-on-a-stick` folder: that
is where `stick` looks for your `.env` settings and where it writes `runs/`.

## Your first lab (about 10 minutes)

**1. Check your machine.**

```bash
stick doctor
```

Every line should say `ok` (or `warn`, which is fine). A `fail` line tells you what to fix: usually Docker or
containerlab isn't installed or you haven't logged out and back in yet. See [Troubleshooting](#troubleshooting).

**2. Build the FRR router image** (once; about a minute).

```bash
stick image build frr
```

**3. Start the lab.** The first time, this downloads the Nokia SR Linux image (about 1 GB).

```bash
stick env up
```

You'll see a table with six nodes in state `running`. Give BGP about 30 seconds to come up.

**4. Log in to the routers, like real ones.**

```bash
ssh admin@clab-stick-base-frr1     # password: admin       (lands straight in the FRR CLI)
ssh admin@clab-stick-base-srl1     # password: NokiaSrl1!  (the SR Linux CLI)
```

Try `show ip bgp summary` on frr1 or `show network-instance default protocols bgp neighbor` on srl1. Type `exit`
to log out. To test traffic across the fabric:

```bash
docker exec -it clab-stick-base-h1 ping -c 3 10.1.2.10
```

**5. Start the tools.** NetBox takes about 2.5 minutes the first time (it sets up its database; up to ~6 minutes on
a small machine); later starts are quick.

```bash
stick svc up netbox oxidized
```

Then open them in your browser:

- NetBox: <http://127.0.0.1:8081> (user `admin`, password `admin`). It comes with a site, roles, platforms and device
  types, but no devices: documenting the lab is what the `netbox` tasks ask a model to do.
- Oxidized: <http://127.0.0.1:8888>. It has already backed up the configs of all four routers.

**6. Reset a tool to its starting state.** This is what the benchmark does between attempts.

```bash
stick svc reset netbox
```

**7. Clean up** when you're done.

```bash
stick svc down netbox oxidized
stick env down
```

Your NetBox data is kept for next time. To wipe it too, add `--volumes` to the `svc down` command.

## Run a model

Let an AI model attempt the tasks: `stick` gives it each task's instructions, grades what it did in the lab and
tells you why it failed. (To see what the grader does by doing a task yourself, see
[docs/grading.md](docs/grading.md#try-it-yourself-be-the-agent).) You need a model server running on your machine, for example
[Ollama](https://ollama.com) (`ollama pull qwen3:14b`), LM Studio, or Strata, or an API key for a paid model. The
model must support **tool calling**.

**Set the context window on your model server yourself.** The context window is how much conversation the model
can hold at once, and `stick` doesn't change it: it only records the size the server reports. Set it before you
start the server, and use the same size for every model you compare:

- **Ollama**: its default depends on your GPU (4k under 24 GB of VRAM, 32k from 24 GB), and a conversation that
  outgrows it is cut without warning. Start it with `OLLAMA_CONTEXT_LENGTH=65536` (or another size your memory
  allows); `ollama ps` shows the size a loaded model got.
- **Strata, LM Studio, llama.cpp, vLLM**: the context size in the server's own settings.

Each attempt records the size that applied (`context_window` in its `metrics.json`). An attempt that fills the
window stops with `context_full`. To test one model at several sizes, restart the server at each size and run
into a separate folder (`--runs-dir`).

**1. Check that `stick` sees your model server:**

```bash
stick doctor          # lists the model servers it finds and the models they serve
```

**2. Run one task with one model:**

```bash
stick run running-config-cli-frr --model ollama/qwen3:14b
```

The model gets the task's instructions and one tool: running shell commands in a small "toolbox" container that can
reach the lab. When it says it's done (or runs out of turns or time), the grader scores the attempt. The first run
builds the toolbox image, which takes a few minutes (about 1.5 GB: it includes the AWS CLI and Terraform).
In the `mcp` section the model has no shell: its tools are those of the tools' MCP servers
([docs/tasks.md](docs/tasks.md#mcp-the-same-tools-through-mcp-servers)).

**3. Compare two models on the five `cfg-mgmt` tasks**, three attempts each (models don't always do the same thing twice).
**Run local models one after another, never at the same time**: they share your GPU and memory. Finish the first
model, stop its server, then run the second:

```bash
stick run --section cfg-mgmt --model strata/deepseek-v4.1-flash --repeat 3 --runs-dir runs/compare
# now stop Strata (close its window), then:
stick run --section cfg-mgmt --model ollama/qwen3:14b --repeat 3 --runs-dir runs/compare
stick report runs/compare
```

`stick run` refuses two local models in one command for this reason. A local model and a paid API model can go in one
command (`--model ollama/qwen3:14b --model anthropic/claude-sonnet-5-5`).

`stick report` shows, per model, how many attempts passed, the mean score, tokens, cost, time and the most common
problems. Every attempt's full conversation is in `transcript.jsonl` in its run folder.

You don't have to read those files: every `stick run` also writes a report of that run into the runs folder (named after the model and what ran, e.g.
`report-claude-haiku-5-5-cfg-mgmt-<time>.html`) and prints its address for you to click: one page with
the scores, where each model struggled and every attempt's checks and conversation. For two models side by side:

```bash
stick vs anthropic/claude-haiku-5-5 ollama/qwen3:14b --section cfg-mgmt --repeat 3
stick report runs/compare --html        # the same page for runs you already have
```

The page counts **turns**, and explains them at the top. A turn is one reply from the model: it reads the
conversation so far, then either asks for commands to run in the lab or says it has finished. An attempt may use
as many turns as the task allows (its `limits.turns`, else 30; `--max-turns` overrides it). An attempt that reaches
the limit is stopped and graded as it stands, so fewer turns means the model got to the result more directly.

Model names are `provider/model`: `ollama/...`, `lmstudio/...`, `strata/...`, `vllm/...`, `openai/...`,
`anthropic/...`, or `openai-compat/<model> --base-url http://host:port/v1` for any other OpenAI-compatible server.
Paid models read their key from an environment variable (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`). Server on a different
port: `--base-url http://127.0.0.1:9000/v1`. Settings you use every time can go in a local `.env` file
(`cp .env.example .env`; it also explains how to keep a real key out of that file). `stick run` starts the lab and the
tools the chosen tasks need if they aren't running. All options and what's recorded: [docs/runner.md](docs/runner.md).

**Claude models run with thinking off by default**, so every model is compared at its plainest. Add `--thinking` to
let the model think before it answers:

```bash
stick run --section cfg-mgmt --model anthropic/claude-haiku-5-5              # thinking off
stick run --section cfg-mgmt --model anthropic/claude-haiku-5-5 --thinking   # thinking on
```

A few Claude models can't turn thinking off (Claude Opus 5.5, for example): they run with it on, and the output
and the report say so. The option has no effect on local models.

## Commands at a glance

The commands for testing models, in one place. Run them from inside the `llm-on-a-stick` folder. `stick run` and `stick vs` start the lab and the tools the tasks need by themselves, and
each ends by printing the address of its report for you to click.

Letting an AI agent such as Claude Code run the tests for you? It finds what it needs in [AGENTS.md](AGENTS.md):
the rules (one local model at a time), what it must leave to you (keys, starting model servers) and where the
results are as data.

**One model, one section**

```bash
stick run --section cfg-mgmt --model anthropic/claude-haiku-5-5
```

**Two models side by side**

```bash
stick vs anthropic/claude-haiku-5-5 ollama/gemma4:12b --section cfg-mgmt
```

**A single task.** Give the task's id instead of `--section` (`stick task list` shows the ids and which section
each belongs to):

```bash
stick run netconf-filtered-bgp --model anthropic/claude-haiku-5-5
stick vs anthropic/claude-haiku-5-5 ollama/gemma4:12b netconf-filtered-bgp
```

**Every task in every section.** `--all` works with `stick run` and `stick vs`:

```bash
stick run --all --model anthropic/claude-haiku-5-5
stick run --all --model anthropic/claude-haiku-5-5 --repeat 3
```

`--repeat 3` makes the model attempt each task three times, each attempt starting from a clean lab. Models don't
always do the same thing twice, so this shows whether a task is solved reliably or only sometimes; the report then
says "2/3 passed". It takes three times as long.

**Two local models.** They share your GPU and memory, so `stick vs` refuses that pair. Run them one after the other,
each into its own folder, then make the side-by-side report from the two folders:

```bash
# 1. Gemma on Ollama
stick run --section cfg-mgmt --model ollama/gemma4:12b --runs-dir runs/gemma

# 2. Free the GPU (stop the first model), then start the second model's server (Strata: from its window)
ollama stop gemma4:12b

# 3. Strata
stick run --section cfg-mgmt --model strata/deepseek-v4.1-flash --runs-dir runs/strata

# 4. Side-by-side report
stick report runs/gemma runs/strata --html --out runs/gemma-vs-strata.html
```

`stick report` compares up to three models this way: give it a third folder (for example `runs/haiku`) and the
page shows all three side by side. Use folders that hold only these runs: the report counts every attempt it finds
in them, and another model or setting in there joins the comparison as one more model. For every task instead of one section, replace
`--section cfg-mgmt` with `--all` in steps 1 and 3.

**Stop everything afterwards** (the tools that are running, then the lab):

```bash
stick env down
```

## Cheat sheet

| Lab node | Management IP | Login | Notes |
|---|---|---|---|
| srl1, srl2 | 172.30.30.11, .12 | `admin` / `NokiaSrl1!` | Nokia SR Linux spines, AS65001 / AS65002 |
| frr1, frr2 | 172.30.30.21, .22 | `admin` / `admin`; `netops` / `netops` | FRR leaves, AS65101 / AS65102; `admin` lands in vtysh, `netops` in a Linux shell (`lldpcli`, `vtysh -c ...`) |
| h1, h2 | 172.30.30.31, .32 | `docker exec -it clab-stick-base-h1 sh` | hosts 10.1.1.10 and 10.1.2.10 |

| Tool | In your browser | From the lab network | Login |
|---|---|---|---|
| NetBox 4.7 | <http://127.0.0.1:8081> | `http://172.30.30.100:8080` | `admin` / `admin`; API token in [docs/services.md](docs/services.md) |
| Oxidized 0.37 | <http://127.0.0.1:8888> | `http://172.30.30.101:8888` | none |
| Nautobot 3.2 | <http://127.0.0.1:8082> | `http://172.30.30.102:8080` | `admin` / `admin` |
| Emulated AWS (moto 5.2) | <http://127.0.0.1:8083/moto-api/> | `http://172.30.30.103:5000` | none |
| LibreNMS 26.10 | <http://127.0.0.1:8084> | `http://172.30.30.104:8000` | `admin` / `Stick-lab-9x!Qz` |
| Zabbix 8.0 | <http://127.0.0.1:8085> | `http://172.30.30.107:8080` | `Admin` / `zabbix` |

| Command | What it does |
|---|---|
| `stick doctor` | Checks your machine and shows what it can run |
| `stick env up` / `status` | Start or show the lab |
| `stick env down` | Stop everything: the tools that are running, then the lab |
| `stick svc list` | Lists the available tools |
| `stick svc up <tool>...` | Starts tools (one after another), with their starting data |
| `stick svc status` | Shows which tools are running and healthy |
| `stick svc reset <tool>` | Puts a tool back to its starting state |
| `stick svc down <tool>...` | Stops tools (`--volumes` also deletes their data) |
| `stick task list` | Lists the tasks (`--tasks-dir <folder>` adds your own) |
| `stick task start <task>` | Prepares an attempt and prints the instructions |
| `stick grade` | Grades the latest attempt and writes `result.json` |
| `stick run <task> --model <provider/model>` | Lets a model attempt a task, then grades it (`--section`, `--all`, `--repeat`) |
| `stick report` | Compares model runs: passes, score, tokens, cost, time, common problems (`--html` writes the report page) |
| `stick vs <model> <model>` | Runs two models on the same tasks and writes the side-by-side report |

## Run the tests yourself

The project checks itself with automated tests. There are two kinds.

### Quick tests (a few seconds, no lab needed)

```bash
uv run pytest
```

These check the code and configuration files. The last line should look like `260 passed, 85 deselected`
("deselected" are the lab tests below, which are skipped by default).

### Lab tests (several minutes, more the first time)

These build the real lab, start every tool, and check that everything works: BGP comes up, hosts can ping
each other, each tool has its starting data and resets correctly, Oxidized backs up every router, and so on.

```bash
sudo apt install sshpass         # once: the NETCONF task checks use it
stick image build frr     # only needed once, or after updating the code
uv run pytest -m lab -v
```

Each test prints `PASSED` or `FAILED` as it runs; the last line is the summary, for example `85 passed`. The first
run takes longer because of image downloads and each tool's first start.

To test just one area, name its file:

```bash
uv run pytest -m lab -v tests/integration/test_base_lab.py   # the lab itself
uv run pytest -m lab -v tests/integration/test_netbox.py     # NetBox
uv run pytest -m lab -v tests/integration/test_oxidized.py   # Oxidized
uv run pytest -m lab -v tests/integration/test_nautobot.py   # Nautobot
uv run pytest -m lab -v tests/integration/test_librenms.py   # LibreNMS
uv run pytest -m lab -v tests/integration/test_zabbix.py     # Zabbix
uv run pytest -m lab -v tests/integration/test_moto.py       # the emulated AWS account
uv run pytest -m lab -v tests/integration/test_grading_lab.py # the grader
uv run pytest -m lab -v tests/integration/test_tasks_lab.py   # every task can be solved, and can't be faked (and the mcp tasks through their MCP servers)
uv run pytest -m lab -v tests/integration/test_runner_lab.py  # the runner and its toolbox
```

> **Note:** the lab tests redeploy the lab from scratch and reset the tools to their starting state, so
> don't run them while you're in the middle of using the lab. Afterwards they clean up: the lab is removed, and the
> tools are stopped again unless they were already running before the tests started. To keep them running
> after the tests (to look around), use `STICK_KEEP_SERVICES=1 uv run pytest -m lab -v`.

**If a test fails**, the output shows which check failed and why. The container logs usually tell you the rest:
`docker ps -a` lists the containers, and `docker logs <name>` shows a container's log (for example
`docker logs stick-netbox-netbox-1`). Feel free to open an issue with the output.

## Troubleshooting

| What you see | What to do |
|---|---|
| `permission denied ... docker.sock` | Run `sudo usermod -aG docker $USER`, then log out and back in. |
| containerlab says it needs root or `sudo` | Run `sudo usermod -aG clab_admins $USER`, then log out and back in. |
| `stick doctor` shows `fail` for docker | Docker isn't running: `sudo systemctl start docker` (on WSL2, restart WSL). |
| `address already in use` for port 8081 or 8888 | Something else uses that port. Pick another: `STICK_NETBOX_PORT=9081 stick svc up netbox` (or `STICK_OXIDIZED_PORT` for Oxidized). |
| NetBox seems stuck on its first start | It's creating its database; this takes about 2.5 minutes (up to ~6 on a small machine). `stick svc status` shows when it's healthy. |
| `uv sync` or `uv tool install` fails with `Permission denied` on `topologies/clab-stick-base` | Left over from a lab started by version 0.13 or older, which kept its working files there (now in `~/.local/state/stick/labs`). Stop the lab (`stick env down`), then `sudo rm -rf topologies/clab-stick-base`. |
| `ssh: Could not resolve hostname clab-stick-base-...` | The lab isn't running (`stick env up`), or use the IP from the [cheat sheet](#cheat-sheet). |
| Not enough memory | `stick doctor` shows your budget. Start only the tools you need. |
| `stick run` says `cannot reach http://127.0.0.1:...` | The model server isn't running, or it's on another port: add `--base-url http://127.0.0.1:<port>/v1`. |
| `stick run` says the server `doesn't serve` the model | Use one of the names it lists (for Ollama, `ollama list`), e.g. `ollama/qwen3:14b`. |
| Every attempt ends with `model-error` | Look at `error` in the run's `metrics.json`. Often the model doesn't support tool calling: try another model. |
| I want to start completely fresh | `stick svc down netbox oxidized --volumes`, then `stick env down`. |

## Glossary

- **containerlab**: builds virtual networks from containers, from a simple topology file.
- **Docker / Docker Compose**: run software in isolated containers; Compose starts a group of them together (each tool here is one group).
- **uv**: installs Python and this project's dependencies; `uv run <command>` runs a command inside the project.
- **pytest**: the program that runs the automated tests.
- **SR Linux**: Nokia's network operating system, free to use in labs.
- **FRR (FRRouting)**: open-source routing software (BGP, OSPF...) with a Cisco-like CLI.
- **NetBox**: a source of truth for network devices, IP addresses and cabling.
- **Oxidized**: backs up router configs and keeps their history.
- **Tool calling**: a model's ability to ask the program running it to do something (here: run a command) instead of only writing text.
- **Token**: the unit models read and write text in (roughly ¾ of a word); paid models charge per token.

## Why this project

Existing benchmarks for AI agents in networking (NIKA, NetArena, NetConfArena, NetAgentBench) are academic and mostly
about routing. None of them test the tools network engineers use every day, and none is built around "run my local
model on my own machine and compare it to a frontier model".

## Roadmap

What is still to do:

- **More tools**, each with its own tasks: Gitea, syslog, telemetry (gNMI), DNS and DHCP, SuzieQ, Batfish.
- **More task sections**: lab management and troubleshooting (faults put into the lab for the model to find).
- **A judge model** for the few things code can't grade.
- **Your own tasks**: a scaffold command, and tasks loaded from a git address.
- **Run variants**: the same model at different context sizes and quantisations, and the same task with a
  shell and with MCP tools (today the `mcp` section has its own tasks).
- **Several labs in parallel**, so a cloud model and a local model can run at the same time.
- **More devices**: Cisco CML as a lab backend, and your own Arista, Juniper or Cisco images.
- **A public leaderboard.**

The detailed list is in [TODO.md](TODO.md). Supported platforms: [docs/platforms.md](docs/platforms.md). Which tools
work with which devices: [docs/compatibility.md](docs/compatibility.md).

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the developer setup and commit rules.

## Licence

MIT. See [LICENSE](LICENSE).
