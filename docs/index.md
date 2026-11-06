# llm-on-a-stick

**One eval harness, many LLMs. Start poking.**

An open-source benchmark that compares local and frontier LLMs on real NetDevOps work and reports *why* a model
fails, not just a score.

!!! note "Status"
    Pre-alpha, Phase 0. The base lab and the `stick` CLI skeleton work; the tool stack, grader and tasks are next.

## Quick start

```bash
uv sync
uv run stick doctor            # what can this machine run?
uv run stick image build frr   # builds stick-frr:dev
uv run stick env up            # deploys the base lab (2x SR Linux, 2x FRR, 2x hosts)
uv run stick env status
uv run stick env down
```

## The base lab

| Node | Image | Role | Access |
|---|---|---|---|
| srl1, srl2 | `ghcr.io/nokia/srlinux:26.7.2` | spines, AS65001 / AS65002 | SSH `admin`/`NokiaSrl1!` (containerlab default), gNMI, JSON-RPC |
| frr1, frr2 | `stick-frr` (FRR 10.7.1 + extras) | leaves, AS65101 / AS65102 | SSH `admin`/`admin` straight into vtysh, SNMPv2c `stick-ro` |
| h1, h2 | `network-multitool` | hosts 10.1.1.10, 10.1.2.10 | `docker exec` |

Management network: `stick-mgmt`, 172.30.30.0/24. Measured RAM: ~1.9 GB per SR Linux node, ~31 MB per FRR
node; the whole lab is ~4 GB.

See [Platforms](platforms.md) for OS support and [Compatibility](compatibility.md) for which tools work with which
devices.
