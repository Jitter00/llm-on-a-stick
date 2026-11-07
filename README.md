# llm-on-a-stick

**One eval harness, many LLMs. Start poking.**

llm-on-a-stick is a free, open-source benchmark that tests how well AI models (LLMs) handle real network engineering
work: building labs, pulling and changing router configs, keeping NetBox in sync, validating changes and
troubleshooting. You run it on your own machine, against a small virtual network, and compare a local model (for
example one running in Ollama) with a paid one. It tells you **why** a model fails (wrong CLI syntax, made-up API
fields, changing things it shouldn't), not just a score.

> **Status: early days.** What works today: the virtual lab, the `stick` command, and two tools (NetBox and
> Oxidized), each checked by automated tests you can run yourself (see [Run the tests](#run-the-tests-yourself)).
> What doesn't exist yet: the AI benchmark tasks themselves. They come next. See [Roadmap](#roadmap).

**Contents:** [What you need](#what-you-need) · [Install](#install-step-by-step) ·
[Your first lab](#your-first-lab-about-10-minutes) · [Cheat sheet](#cheat-sheet) ·
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

## Cheat sheet

| Lab node | Management IP | Login | Notes |
|---|---|---|---|
| srl1, srl2 | 172.30.30.11, .12 | `admin` / `NokiaSrl1!` | Nokia SR Linux spines, AS65001 / AS65002 |
| frr1, frr2 | 172.30.30.21, .22 | `admin` / `admin` | FRR leaves, AS65101 / AS65102; SSH lands in vtysh |
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

## Run the tests yourself

The project checks itself with automated tests. There are two kinds.

### Quick tests (a few seconds, no lab needed)

```bash
uv run pytest
```

These check the code and configuration files. The last line should look like `56 passed, 16 deselected`
("deselected" are the lab tests below, which are skipped by default).

### Lab tests (about 3 minutes, more the first time)

These build the real lab, start NetBox and Oxidized, and check that everything works: BGP comes up, hosts can ping
each other, NetBox has its starting data and resets correctly, Oxidized backs up every router, and so on.

```bash
uv run stick image build frr     # only needed once, or after updating the code
uv run pytest -m lab -v
```

Each test prints `PASSED` or `FAILED` as it runs; the last line is the summary, for example `16 passed`. The first
run takes longer because of image downloads and NetBox's first start.

To test just one area, name its file:

```bash
uv run pytest -m lab -v tests/integration/test_base_lab.py   # the lab itself
uv run pytest -m lab -v tests/integration/test_netbox.py     # NetBox
uv run pytest -m lab -v tests/integration/test_oxidized.py   # Oxidized
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

## Why this project

Existing benchmarks for AI agents in networking (NIKA, NetArena, NetConfArena, NetAgentBench) are academic and mostly
about routing. None of them test the tools network engineers use every day, and none is built around "run my local
model on my own machine and compare it to a frontier model".

## Roadmap

1. **Grader**: automatic checks of the lab's state after a model has worked on it, with a report of what went wrong.
2. **First tasks**: retrieving router configs over the CLI and NETCONF, and checking them against Oxidized.
3. **Running models**: connect local models (Ollama, LM Studio, vLLM) and paid ones, and compare them.
4. **More tools**: Nautobot, Gitea, syslog, telemetry, DNS/DHCP, LibreNMS, Zabbix, SuzieQ, Batfish.

The detailed list is in [TODO.md](TODO.md). Supported platforms: [docs/platforms.md](docs/platforms.md). Which tools
work with which devices: [docs/compatibility.md](docs/compatibility.md).

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the developer setup and commit rules.

## Licence

MIT. See [LICENSE](LICENSE).
