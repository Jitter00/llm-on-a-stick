# llm-on-a-stick

**One eval harness, many LLMs. Start poking.**

llm-on-a-stick is a free, open-source benchmark that tests how well AI models (LLMs) handle real network engineering
work: building labs, pulling and changing router configs, keeping NetBox in sync, validating changes and
troubleshooting. You run it on your own machine, against a small virtual network, and compare a local model (for
example one running in Ollama) with a paid one. It tells you **why** a model fails (wrong CLI syntax, made-up API
fields, changing things it shouldn't), not just a score.

> **Status: early days.** What works today: the virtual lab, the `stick` command, two tools (NetBox and
> Oxidized), the **grader**, which checks an attempt at a task and explains what went wrong, the **first five
> tasks** (getting router configs right over CLI and NETCONF), and the **runner**, which lets AI models attempt
> them and compares the results. You can [be the agent yourself](#try-the-grader-be-the-agent) or
> [run a model](#run-a-model). More tools and tasks come next. See [Roadmap](#roadmap).

**Contents:** [What you need](#what-you-need) · [Install](#install-step-by-step) ·
[Your first lab](#your-first-lab-about-10-minutes) · [Try the grader](#try-the-grader-be-the-agent) ·
[Run a model](#run-a-model) · [Cheat sheet](#cheat-sheet) ·
[Run the tests](#run-the-tests-yourself) · [Troubleshooting](#troubleshooting) · [Glossary](#glossary)

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
| **Operating system** | Linux (Ubuntu, Debian, Fedora...) or Windows 11 with WSL2. macOS works on a best-effort basis (see [docs/platforms.md](docs/platforms.md)). |
| **Memory (RAM)** | About 8 GB free: the lab uses ~4 GB, NetBox ~1.5 GB, Oxidized ~50 MB. |
| **Disk** | About 10 GB free for the container images. |
| **Internet** | For the first download of images and tools. |

You don't need to know Python. Everything below is copy and paste.

## Install, step by step

Open a terminal. On Windows, open your WSL2 (Ubuntu) terminal and run everything there.

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

From now on, run every command from inside the `llm-on-a-stick` folder, and start each one with `uv run`.

## Your first lab (about 10 minutes)

**1. Check your machine.**

```bash
uv run stick doctor
```

Every line should say `ok` (or `warn`, which is fine). A `fail` line tells you what to fix: usually Docker or
containerlab isn't installed or you haven't logged out and back in yet. See [Troubleshooting](#troubleshooting).

**2. Build the FRR router image** (once; about a minute).

```bash
uv run stick image build frr
```

**3. Start the lab.** The first time, this downloads the Nokia SR Linux image (about 1 GB).

```bash
uv run stick env up
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
uv run stick svc up netbox oxidized
```

Then open them in your browser:

- NetBox: <http://127.0.0.1:8081> (user `admin`, password `admin`). It comes with a site, roles, platforms and device
  types, but no devices: documenting the lab is one of the future benchmark tasks.
- Oxidized: <http://127.0.0.1:8888>. It has already backed up the configs of all four routers.

**6. Reset a tool to its starting state.** This is what the benchmark does between attempts.

```bash
uv run stick svc reset netbox
```

**7. Clean up** when you're done.

```bash
uv run stick svc down netbox oxidized
uv run stick env down
```

Your NetBox data is kept for next time. To wipe it too, add `--volumes` to the `svc down` command.

## Try the grader: be the agent

The grader is what will score AI models: it looks at the lab after an attempt and checks, one by one, whether the
task was done, and if not, why. You can try it now by doing a task yourself. With the lab running (see above):

**1. Start a task.** It prints the instructions an AI model would get.

```bash
uv run stick task start running-config-cli-frr
```

The task: save frr2's complete running config to a file. Before you start, it puts a random interface description
on frr2 (a "canary"), so a made-up or memorised config can't pass.

**2. Do the task.** Copy the run folder name from the output (`runs/running-config-cli-frr-...`):

```bash
ssh admin@clab-stick-base-frr2 "show running-config" > runs/<run folder>/work/frr2.cfg    # password: admin
```

**3. Grade it.**

```bash
uv run stick grade
```

You'll see each check with `pass` or `fail`, and an overall result (`pass`, `partial` or `fail`). The full details go
into `result.json` in the run folder.

**4. Now fail on purpose** and grade again: delete half of the lines in `frr2.cfg`, or add a line that isn't on the
router. The grader tells you what's missing or invented (`truncated-output`, `hallucinated-value`).

**5. Try a harder one.** `uv run stick task list` shows all five tasks, from saving a config to comparing CLI,
NETCONF and Oxidized. What each one tests: [docs/tasks.md](docs/tasks.md). How grading works and how to write your
own checks: [docs/grading.md](docs/grading.md).

## Run a model

Now let an AI model do the same tasks. You need a model server running on your machine, for example
[Ollama](https://ollama.com) (`ollama pull qwen3:14b`), LM Studio, or Strata, or an API key for a paid model. The
model must support **tool calling**.

**1. Check that `stick` sees your model server:**

```bash
uv run stick doctor          # lists the model servers it finds and the models they serve
```

**2. Run one task with one model:**

```bash
uv run stick run running-config-cli-frr --model ollama/qwen3:14b
```

The model gets the task's instructions and one tool: running shell commands in a small "toolbox" container that can
reach the lab. When it says it's done (or runs out of turns or time), the grader scores the attempt. The first run
builds the toolbox image, which takes a few minutes (about 1.5 GB: it includes the AWS CLI and Terraform).

**3. Compare two models on all five tasks**, three attempts each (models don't always do the same thing twice).
**Run local models one after another, never at the same time**: they share your GPU and memory. Finish the first
model, stop its server, then run the second:

```bash
uv run stick run --section cfg-mgmt --model strata/deepseek-v4.1-flash --repeat 3 --runs-dir runs/compare
# now stop Strata (close its window), then:
uv run stick run --section cfg-mgmt --model ollama/qwen3:14b --repeat 3 --runs-dir runs/compare
uv run stick report runs/compare
```

`stick run` refuses two local models in one command for this reason. A local model and a paid API model can go in one
command (`--model ollama/qwen3:14b --model anthropic/claude-sonnet-5-5`).

`stick report` shows, per model, how many attempts passed, the mean score, tokens, cost, time and the most common
problems. Every attempt's full conversation is in `transcript.jsonl` in its run folder.

You don't have to read those files: every `stick run` also writes `report.html` into the runs folder, one page with
the scores, where each model struggled and every attempt's checks and conversation. For two models side by side:

```bash
uv run stick vs anthropic/claude-haiku-5-5 ollama/qwen3:14b --section cfg-mgmt --repeat 3
uv run stick report runs/compare --html        # the same page for runs you already have
```

The page counts **turns**, and explains them at the top. A turn is one reply from the model: it reads the
conversation so far, then either asks for commands to run in the lab or says it has finished. An attempt may use
as many turns as the task allows (its `limits.turns`, else 30; `--max-turns` overrides it). An attempt that reaches
the limit is stopped and graded as it stands, so fewer turns means the model got to the result more directly.

Model names are `provider/model`: `ollama/...`, `lmstudio/...`, `strata/...`, `vllm/...`, `openai/...`,
`anthropic/...`, or `openai-compat/<model> --base-url http://host:port/v1` for any other OpenAI-compatible server.
Paid models read their key from an environment variable (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`). Server on a different
port: `--base-url http://127.0.0.1:9000/v1`. All options and what's recorded: [docs/runner.md](docs/runner.md).

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

| Command | What it does |
|---|---|
| `uv run stick doctor` | Checks your machine and shows what it can run |
| `uv run stick env up` / `down` / `status` | Start, stop or show the lab |
| `uv run stick svc list` | Lists the available tools |
| `uv run stick svc up <tool>...` | Starts tools (one after another), with their starting data |
| `uv run stick svc status` | Shows which tools are running and healthy |
| `uv run stick svc reset <tool>` | Puts a tool back to its starting state |
| `uv run stick svc down <tool>...` | Stops tools (`--volumes` also deletes their data) |
| `uv run stick task list` | Lists the tasks (`--tasks-dir <folder>` adds your own) |
| `uv run stick task start <task>` | Prepares an attempt and prints the instructions |
| `uv run stick grade` | Grades the latest attempt and writes `result.json` |
| `uv run stick run <task> --model <provider/model>` | Lets a model attempt a task, then grades it (`--section`, `--all`, `--repeat`) |
| `uv run stick report` | Compares model runs: passes, score, tokens, cost, time, common problems (`--html` writes the report page) |
| `uv run stick vs <model> <model>` | Runs two models on the same tasks and writes the side-by-side `report.html` |

## Run the tests yourself

The project checks itself with automated tests. There are two kinds.

### Quick tests (a few seconds, no lab needed)

```bash
uv run pytest
```

These check the code and configuration files. The last line should look like `122 passed, 28 deselected`
("deselected" are the lab tests below, which are skipped by default).

### Lab tests (about 5 minutes, more the first time)

These build the real lab, start NetBox and Oxidized, and check that everything works: BGP comes up, hosts can ping
each other, NetBox has its starting data and resets correctly, Oxidized backs up every router, and so on.

```bash
sudo apt install sshpass         # once: the NETCONF task checks use it
uv run stick image build frr     # only needed once, or after updating the code
uv run pytest -m lab -v
```

Each test prints `PASSED` or `FAILED` as it runs; the last line is the summary, for example `30 passed`. The first
run takes longer because of image downloads and NetBox's first start.

To test just one area, name its file:

```bash
uv run pytest -m lab -v tests/integration/test_base_lab.py   # the lab itself
uv run pytest -m lab -v tests/integration/test_netbox.py     # NetBox
uv run pytest -m lab -v tests/integration/test_oxidized.py   # Oxidized
uv run pytest -m lab -v tests/integration/test_grading_lab.py # the grader
uv run pytest -m lab -v tests/integration/test_tasks_lab.py   # every task can be solved, and can't be faked
uv run pytest -m lab -v tests/integration/test_runner_lab.py  # the runner and its toolbox
```

> **Note:** the lab tests redeploy the lab from scratch and reset NetBox and Oxidized to their starting state, so
> don't run them while you're in the middle of using the lab. Afterwards they clean up: the lab is removed, and NetBox
> and Oxidized are stopped again unless they were already running before the tests started. To keep them running
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
| `address already in use` for port 8081 or 8888 | Something else uses that port. Pick another: `STICK_NETBOX_PORT=9081 uv run stick svc up netbox` (or `STICK_OXIDIZED_PORT` for Oxidized). |
| NetBox seems stuck on its first start | It's creating its database; this takes about 2.5 minutes (up to ~6 on a small machine). `uv run stick svc status` shows when it's healthy. |
| `ssh: Could not resolve hostname clab-stick-base-...` | The lab isn't running (`uv run stick env up`), or use the IP from the [cheat sheet](#cheat-sheet). |
| Not enough memory | `uv run stick doctor` shows your budget. Start only the tools you need. |
| `stick run` says `cannot reach http://127.0.0.1:...` | The model server isn't running, or it's on another port: add `--base-url http://127.0.0.1:<port>/v1`. |
| `stick run` says the server `doesn't serve` the model | Use one of the names it lists (for Ollama, `ollama list`), e.g. `ollama/qwen3:14b`. |
| Every attempt ends with `model-error` | Look at `error` in the run's `metrics.json`. Often the model doesn't support tool calling: try another model. |
| I want to start completely fresh | `uv run stick svc down netbox oxidized --volumes`, then `uv run stick env down`. |

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

1. ~~**Grader**~~: done. Checks the lab after an attempt and reports what went wrong ([docs/grading.md](docs/grading.md)).
2. ~~**First tasks**~~: done. Seven config-retrieval tasks over CLI and NETCONF ([docs/tasks.md](docs/tasks.md)).
3. ~~**Running models**~~: done. Local (Ollama, LM Studio, vLLM, Strata...) and paid models, compared with
   `stick report` ([docs/runner.md](docs/runner.md)).
4. **More tools**: ~~Nautobot~~, ~~AWS CLI and Terraform (against an emulated AWS account)~~, ~~LibreNMS~~, ~~Zabbix~~,
   Gitea, syslog, telemetry, DNS/DHCP, SuzieQ, Batfish.

The detailed list is in [TODO.md](TODO.md). Supported platforms: [docs/platforms.md](docs/platforms.md). Which tools
work with which devices: [docs/compatibility.md](docs/compatibility.md).

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the developer setup and commit rules.

## Licence

MIT. See [LICENSE](LICENSE).
