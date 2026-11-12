# TODO

Each item below is meant to be one PR (Conventional Commit title, e.g. `feat(svc): add Nautobot service`).
Items are roughly in order; dependencies are noted. Only open items are listed: delete an item in the PR that
completes it (what was done is in CHANGELOG.md and the git history).

## Repo setup

- [ ] Try `ubuntu-26.04` runners once containerlab is verified there (`ubuntu-latest` is still 24.04).

## Next up

- [ ] **LLM judge** (only for what code can't grade; policy in [docs/grading.md](docs/grading.md#grading-policy-code-first)):
      new check type `llm_judge` (`artifact`, `rubric`, `reference`, `scale`); `stick grade --judge-model`, refused if it's
      the tested model; judge scores in their own `result.json` section with model/version/agreement, never mixed into
      `score`; per-check `graded_by: code | judge`; `not-graded` when no judge is configured; a small human-graded
      calibration set. Done first: transcript hints in code (`wrong-dialect`, `attempted-change`,
      `no-verification`, `ignored-error`; hints only, see docs/grading.md "Failure hints", `stick hints`).

## Phase 0: environment (one service per PR)

Pattern for every service (see `services/netbox/` and `docs/services.md`):
`services/<name>/{compose.yaml,service.yaml,seed.yaml}`, a fixed IP on `stick-mgmt` in `lab.SERVICE_IPS`, a health check,
seed data, a snapshot/reset, a measured footprint in `src/llm_on_a_stick/data/footprints.yaml` (`measured: true`),
`tests/integration/test_<name>.py` (up → seeded → change → reset), a row in `docs/compatibility.md` and a section in `docs/services.md`.
Measure RAM with cgroup `memory.current` (`docker stats` shows 0 for some containers), and time the cold boot and the reset.

- [ ] **Gitea.** Seed an org, a `lab-configs` repo and an API token; snapshot = its DB and repo volume. Needed for the GitOps tasks.
- [ ] **Syslog (Loki + Promtail, or rsyslog → Loki).** `stick-frr` already forwards when `STICK_SYSLOG_TARGET=host:port` is set;
      wire that in the topology. Configure SR Linux remote syslog in `configs/srl/*.cli`. Verify logs from all four nodes.
- [ ] **Telemetry (gNMIc + Prometheus).** gNMI subscriptions to SR Linux (interface counters, BGP state); FRR has no gNMI
      (document SNMP as its path). Verify counters appear in Prometheus.
- [ ] **DDI (PowerDNS + Kea).** Authoritative zone for the lab (`stick.lab`) with API enabled; Kea DHCP on the host subnets.
      This means h1/h2 switch from static IPs to DHCP (a topology change, so update the integration tests).
- [ ] **SuzieQ.** Poller against SR Linux and FRR; check which of the two it supports.
- [ ] **Batfish.** Expected: no SR Linux support, partial FRR. Record the actual result. It becomes fully useful once cEOS or Junos are added.
- [ ] **Compatibility spike leftovers.** SR Linux SSH CLI, NETCONF and gNMI, LLDP on both OSes, remote syslog
      (cells still ❓ in `docs/compatibility.md`).
- [ ] **`stick env reset`.** Redeploy the lab and reset every running service, so a whole attempt starts from a known state.
- [ ] **`stick up <profile>`.** Lab plus a named set of services (e.g. `cfg-mgmt` = lab + Oxidized + Gitea), checked against
      the RAM budget from `stick doctor`.

## Phase 1: grading and runner

- [ ] More checks as tasks need them: `interface_ip`, `dns_record` (with PowerDNS), NETCONF-specific checks, gNMI-based reads.
- [ ] **Failure classifier** (`classify.py`): transcript plus device responses → `cli-syntax`, `wrong-dialect` (done as a hint),
      `netconf-rpc-error`, `hallucinated-api`, `hallucinated-value`, `truncated-output`, `incomplete-config`, `wrong-config`,
      `collateral-change`, `no-verification` (done as a hint), `loop`, `gave-up`, `limit-exceeded`, `env-error` (excluded from scores).
- [ ] Runner follow-ups: scheduler (parallel *lab work* only: **never run several local models at the same time**;
      local models always go one after another, and API models may run in parallel; for `stick vs`, a lab instance per
      model so that a cloud and a local model can run at the same time), publish `stick-toolbox` to GHCR, Inspect-format log export,
      MCP tools as a variant of any task (`--tools mcp`; today only the `mcp` section's own tasks use MCP
      servers), an MCP server for the routers themselves, context-window variants (`--num-ctx`), streaming for
      long Anthropic turns, macOS support for the toolbox.
- [ ] **Judge model** (`--judge-model`): see "Next up" and the grading policy in docs/grading.md.
- [ ] **Report.** `stick report` (table/md/json per model and attempt), the HTML page (`--html`, also written by
      `stick run`) and `stick vs` exist; next: breakdowns by section, tag and failure class.

## Phase 2: tasks, user tests, variants, scheduler

- [ ] **At most 5 tasks for each of the other sections, none obvious** (rules: docs/tasks.md, "Which tasks are
      kept"; pick the ones local models are likely to get wrong). New sections are per tool (powerdns, kea,
      ...); the groupings are in sections/README.md. Also `lab-mgmt` and `troubleshooting` (fault injection:
      MTU mismatch, wrong ASN, ACL blackhole).
- [ ] **User-defined tasks.** `--tasks-dir` (local path or git URL); `stick task new` (scaffold); `stick task validate`
      (oracle must PASS, no-op agent must FAIL); a `@check` plugin interface + entry points; `matrix:` expansion.
- [ ] **Run variants.** Same model × context window (8k/32k/128k) first, then quantisation, CLI vs MCP tools, reasoning
      effort, with/without docs.
- [ ] **Scheduler.** Group tasks by shared services, bin-pack parallel lab instances under the doctor RAM budget
      (minus local model RAM), limit API concurrency per provider; `stick run --dry-run` prints the plan.
      Parallel labs need per-instance lab names and mgmt subnets (today both are fixed).

## Later

- [ ] **macOS.** First test the Linux-VM route in docs/platforms.md on a real Mac (also: do the service and toolbox
      images run on ARM?). Then native `stick run`: put the toolbox on `stick-mgmt` instead of the host network,
      give tasks the services' lab-network addresses instead of `127.0.0.1`, run containerlab in a container.
      The network change affects Linux too, so every section needs re-testing.
- [ ] CML backend (lab-per-sample via `virl2_client`; CML-Free 5-node limit; Cisco refplat images only inside CML).
- [ ] BYO vendor images: Arista cEOS, Juniper vJunos/cRPD (vrnetlab), Cisco XRd/Cat8kv. Fetch/build scripts only, never redistributed.
- [ ] NetClaw's MCP servers (Apache-2.0) as another tool layer for the "CLI vs MCP" variant (the `mcp` section
      uses each tool's own published server); NetClaw itself as an agent under test.
- [ ] IETF draft-cui-nmrg-llm-benchmark task import.
- [ ] Public leaderboard (local models broken out by hardware and quantisation).

## Known gotchas (learned so far)

- SR Linux startup `.cli` files take no `#` comments: containerlab stops at the first one, silently.
- `snmpd -c` *adds* a config file to the default search path; use `-C -c` or it binds udp:161 twice and crashes the container.
- FRR config is mounted read-only under `/etc/stick` and copied in at boot, so `write memory` can't modify the repo (a test enforces this).
- NetBox 4.5+ only creates a v2 token (`Bearer nbt_<key>.<token>`) when `API_TOKEN_PEPPER_1`, a 12-char `SUPERUSER_API_KEY`
  and a 40-char `SUPERUSER_API_TOKEN` are all set; `Token <hex>` returns 403. Cold boot is ~150 s on a desktop but 5–6 min on a 4-vCPU GitHub runner, so the health check uses `start_period: 600s`.
- `docker stats` reports 0B for SR Linux containers; read cgroup `memory.current` instead.
- containerlab reuses an existing `stick-mgmt` network and doesn't delete it on destroy while services are attached.
- A local credential-guard hook blocks reading or writing `*.env` files; keep service settings inline in `compose.yaml`.
- Oxidized 0.37 has no SR Linux or FRR model; ours use SSH exec mode. `CONFIG_RELOAD_INTERVAL: "0"` in its image means
  "reload continuously", not "never". Named volumes are root-owned, so mount them under `~/.config/oxidized`, which the
  image chowns at start. `rest:` is deprecated; use `extensions.oxidized-web`.
- stick-frr: without `/etc/frr/vtysh.conf`, every non-root vtysh session printed two warning lines first; the entrypoint now creates it.
- SR Linux: `sr_cli -ed "set ..."` does NOT commit; use `sr_cli -ec` (candidate mode, commit at end).
- The grader reads state via `docker exec` (sr_cli / vtysh); verified byte-identical to what SSH returns.
- The credential-guard hook matches the text `llm_on_a_stick.env` (our env module) as a `.env` file; put such
  edits in a scratchpad script instead of an inline shell command.
- A full SR Linux NETCONF reply is ~300 KB: too big for one environment variable (128 KB limit). Use files.
- SR Linux NETCONF trees contain `<interface>` under network-instances, LLDP etc. with reused names; use
  `data/interface` for the real interfaces.
- Oxidized only stores a new version when the config changed: wait for the backup *run* (nodes.json `last.end`).
- MCP (the `mcp` section): the Python SDK is at 2.x (`MCPServer`, snake_case fields; 1.x examples don't run).
  AWS's API server takes `AWS_ENDPOINT_URL` only for a loopback address, hence host networking, and needs the
  internet at start. `zabbix-mcp` refuses Zabbix 8.0 without `ZABBIX_SKIP_VERSION_CHECK=true`. Its
  `maintenance_create` can't make a maintenance without data collection.
- LibreNMS learns IP addresses from FRR only (SR Linux's SNMP agent doesn't list them), and FRR interface
  descriptions don't reach `ifAlias`.
- A model without a shell has no clock: the MCP system prompt gives the time.
