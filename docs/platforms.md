# Platforms

The `stick` CLI is plain Python and runs anywhere. containerlab and the lab containers always need a Linux
environment: native, WSL2, or a Linux VM on macOS. `stick doctor` tells you which situation you're in and what you
can run.

| Platform | Support level | What works | What doesn't |
|---|---|---|---|
| **Linux x86_64** | Full (reference platform) | Everything: container NOS, tool stack, VM-based NOS via vrnetlab (with KVM), local CML VM | – |
| **Windows 11 + WSL2** | Supported | Container NOS and tool stack inside WSL2 | VM-based NOS need nested virtualisation enabled; set a RAM limit in `.wslconfig` |
| **macOS, Apple Silicon** | Best effort, containers only | Base lab (SR Linux and FRR both ship arm64 images) and container tools, inside OrbStack or Docker Desktop | No x86 VM-based NOS, no local CML (a remote CML server is fine); Batfish may need x86 emulation |
| **macOS, Intel** | Like Linux, via a VM | Container labs | Nested virtualisation is limited |
| **Native Windows** | Not supported | – | Use WSL2 |

## Memory on macOS and Windows

On Docker Desktop and OrbStack, containers live in a VM with a fixed memory size. That VM size, not your Mac's
total RAM, is the real budget. `stick doctor` caps its estimate at the Docker VM's memory.

## Running a local model on the same machine

A local model server (Ollama, LM Studio, vLLM) competes with the lab for RAM. `stick doctor` lists the models
currently loaded. Ollama loads models on demand, so if the model under test isn't loaded yet, reserve room for it:

```bash
uv run stick doctor --reserve-mb 20000   # keep ~20 GB free for the model
```

## Running models (`stick run`)

The toolbox container that runs a model's commands uses Docker host networking to reach the lab's management
addresses. That works on Linux and WSL2. On macOS the lab addresses aren't reachable from the host, so `stick run` is
not supported there yet; the model servers themselves (Ollama, LM Studio...) can still run on a Mac and be used from a
Linux machine with `--base-url`.
