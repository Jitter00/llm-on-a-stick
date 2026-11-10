# Platforms

The `stick` CLI is plain Python and runs anywhere. containerlab and the lab containers always need a Linux
environment: native, WSL2, or a Linux VM on macOS. `stick doctor` tells you which situation you're in and what you
can run.

| Platform | Support level | What works | What doesn't |
|---|---|---|---|
| **Linux x86_64** | Full (reference platform) | Everything: container NOS, tool stack, VM-based NOS via vrnetlab (with KVM), local CML VM | – |
| **Windows 11 + WSL2** | Supported | Container NOS and tool stack inside WSL2 | VM-based NOS need nested virtualisation enabled; set a RAM limit in `.wslconfig` |
| **macOS, Apple Silicon** | Best effort, containers only | Base lab (SR Linux and FRR both ship arm64 images) and container tools, inside OrbStack or Docker Desktop; model runs inside a [Linux VM](#macos-use-a-linux-virtual-machine) | `stick run` directly on macOS; no x86 VM-based NOS, no local CML (a remote CML server is fine); Batfish may need x86 emulation |
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
not supported there directly yet; the model servers themselves (Ollama, LM Studio...) can still run on a Mac and be
used from a Linux machine with `--base-url`.

## macOS: use a Linux virtual machine

To run models against the lab on a Mac, run `stick` inside a Linux virtual machine (VM) on it. Inside the VM
everything is plain Linux, so the whole README applies.

!!! warning "Not tested yet"
    This route follows from how `stick` works, but nobody has run it end to end on a Mac. If you try it, please
    open an issue with what happened.

1. **Create an Ubuntu VM** with a tool of your choice: [OrbStack](https://orbstack.dev) (Linux machines),
   [Multipass](https://multipass.run), [Lima](https://lima-vm.io) or [UTM](https://mac.getutm.app). Give it at
   least 4 CPUs, 12 GB of memory and 40 GB of disk; the VM's memory, not the Mac's, is what the lab and the tools
   can use. With Multipass, for example:

    ```bash
    multipass launch --name stick --cpus 4 --memory 12G --disk 40G
    multipass shell stick
    ```

2. **Inside the VM, follow the README** from "Install, step by step": Docker, containerlab, uv, then `stick`.
   `stick doctor` tells you what is missing.
3. **A local model stays on the Mac**, where it can use the GPU. Start Ollama or LM Studio on macOS so that it
   listens on the network and not only on the Mac itself (Ollama: `OLLAMA_HOST=0.0.0.0`), then give `stick` the
   Mac's address as the VM sees it, in the VM's `.env`:

    ```bash
    STICK_OLLAMA_BASE_URL=http://<address of the Mac>:11434/v1
    ```

    OrbStack names the Mac `host.orb.internal`; with the other tools it is the VM's default gateway
    (`ip route | grep default`). Paid API models need nothing special.
4. **The report** is written inside the VM, so the `file://` address `stick` prints only opens in a browser in
   the VM. Copy the report to the Mac (`multipass transfer stick:<path to the report> .`) or open it through the
   folder your VM tool shares with macOS. The report is a single file and works anywhere.

On an Apple Silicon Mac the VM is ARM. The lab's routers (SR Linux, FRR) have ARM images; the tool-stack services
and the toolbox image haven't been checked on ARM yet, so some sections may not start.
