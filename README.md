# llm-on-a-stick

**One eval harness, many LLMs. Start poking.**

An open-source benchmark for comparing local and frontier LLMs on real NetDevOps work: building labs, retrieving and
changing configs, keeping NetBox and DNS in sync, validating changes and troubleshooting across tools. It reports
**why** a model fails (wrong CLI dialect, invented API fields, collateral changes...), not just a score.

> Status: **pre-alpha, Phase 0**. The lab environment and the `stick` CLI skeleton exist. The tool stack, grader and
> tasks come next. See [the roadmap](#roadmap).

## Why

Existing agentic network benchmarks (NIKA, NetArena, NetConfArena, NetAgentBench) are academic and mostly
routing-only. None of them exercise the tools network engineers use every day, and none is built around
"run my local model on my own box and compare it to a frontier model".

## The default lab (no vendor accounts needed)

```
       srl1 (AS65001)      srl2 (AS65002)       Nokia SR Linux
         |      \          /      |
       frr1 (AS65101)    frr2 (AS65102)         FRRouting (stick-frr image)
         |                        |
         h1 10.1.1.10/24          h2 10.1.2.10/24   Linux hosts
```

All images are public: `ghcr.io/nokia/srlinux`, FRRouting (we build `stick-frr` from `quay.io/frrouting/frr`,
adding SSH-to-vtysh, SNMP, LLDP and syslog) and `network-multitool`. Nothing is redistributed. Vendor images that
need an account or EULA (Arista cEOS, Juniper vJunos, Cisco XRd/CML) will be optional "bring your own" backends.

## Quick start

Requirements: Linux (or WSL2) with Docker and [containerlab](https://containerlab.dev/install/), Python 3.11+, and
[uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run stick doctor            # what can this machine run?
uv run stick image build frr   # builds stick-frr:dev
uv run stick env up            # deploys the base lab
uv run stick env status
uv run stick env down
```

## Platforms

| Platform | Support |
|---|---|
| Linux x86_64 | Full (reference platform) |
| Windows 11 + WSL2 | Supported; VM-based network OSes need nested virtualisation |
| macOS Apple Silicon | Containers only, best effort (the base lab images are multi-arch); no VM-based NOS or local CML |

Details: [docs/platforms.md](docs/platforms.md).

## Roadmap

- **Phase 0 – environment:** base lab, `stick doctor`, then the tool stack one service at a time (NetBox, Nautobot,
  LibreNMS, Zabbix, Oxidized, Batfish, SuzieQ, Gitea, gNMIc + Prometheus, Loki, PowerDNS, Kea) and a
  [compatibility matrix](docs/compatibility.md).
- **Phase 1 – grading:** deterministic checks, failure classification, `result.json` and reports, a judge model kept
  separate from the model under test, and a bring-your-own-agent mode (`stick env up` → your agent → `stick grade`).
- **Phase 2 – tasks:** sections `lab-mgmt`, `cfg-mgmt`, `sot-ddi`, `validation-observability`, `troubleshooting`;
  user-defined tasks; run variants (context window, quantisation, CLI vs MCP); a resource-aware scheduler.

## Contributing

Commits follow [Conventional Commits](https://www.conventionalcommits.org/). See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

Apache-2.0.
