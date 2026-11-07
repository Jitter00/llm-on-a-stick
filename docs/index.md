# llm-on-a-stick

**One eval harness, many LLMs. Start poking.**

A free, open-source benchmark that tests how well AI models handle real network engineering work, on a small virtual
network that runs on your own machine. It reports *why* a model fails, not just a score.

!!! note "Status"
    Early days. The virtual lab, the `stick` command, NetBox and Oxidized work and are covered by automated tests.
    The AI benchmark tasks come next.

**New here?** The [README](https://github.com/Jitter00/llm-on-a-stick#readme) walks you through installing Docker,
containerlab and uv step by step, and has a troubleshooting table.

## Your first lab

Run these from inside the `llm-on-a-stick` folder:

```bash
uv run stick doctor                    # check your machine
uv run stick image build frr           # build the FRR router image (once)
uv run stick env up                    # start the lab
ssh admin@clab-stick-base-frr1         # password: admin (FRR CLI)
ssh admin@clab-stick-base-srl1         # password: NokiaSrl1! (SR Linux CLI)
uv run stick svc up netbox oxidized    # start the tools (NetBox's first start takes ~2.5 min)
uv run stick svc reset netbox          # back to the starting state
uv run stick svc down netbox oxidized  # stop the tools
uv run stick env down                  # stop the lab
```

## Cheat sheet

| Lab node | Management IP | Login | Role |
|---|---|---|---|
| srl1, srl2 | 172.30.30.11, .12 | `admin` / `NokiaSrl1!` | Nokia SR Linux spines, AS65001 / AS65002 |
| frr1, frr2 | 172.30.30.21, .22 | `admin` / `admin` | FRR leaves, AS65101 / AS65102 |
| h1, h2 | 172.30.30.31, .32 | `docker exec -it clab-stick-base-h1 sh` | hosts 10.1.1.10, 10.1.2.10 |

| Tool | In your browser | From the lab network |
|---|---|---|
| NetBox 4.7 | <http://127.0.0.1:8081> (`admin` / `admin`) | `http://172.30.30.100:8080` |
| Oxidized 0.37 | <http://127.0.0.1:8888> | `http://172.30.30.101:8888` |

Measured RAM: ~1.9 GB per SR Linux node and ~31 MB per FRR node (the whole lab is ~4 GB), NetBox ~1.5 GB,
Oxidized ~50 MB.

## Run the tests

```bash
uv run pytest            # quick tests, a few seconds, no lab needed
uv run pytest -m lab -v  # lab tests: builds the lab, starts NetBox and Oxidized (~3 min)
```

More: [Services](services.md) · [Platforms](platforms.md) · [Compatibility](compatibility.md)
