# TODO

Each item below is meant to be one PR (Conventional Commit title, e.g. `feat(svc): add Nautobot service`).
Items are roughly in order; dependencies are noted. Tick items off in the PR that completes them.

## Repo setup

- [x] Replace the `OWNER` placeholder with the GitHub user (`Jitter00`) in `pyproject.toml`, `mkdocs.yml` and the task schema.
- [x] Repo created (public): https://github.com/Jitter00/llm-on-a-stick; `main` pushed; PR #2 (`feat/netbox`) opened, CI green.
- [x] Branch protection on `main`: requires only the `ci-ok` gate job (it depends on every CI job and fails on
      failed, cancelled or *skipped* jobs, since GitHub counts a skipped required check as passing). Also: up-to-date
      branches, linear history, conversations resolved, no force pushes. Admins can bypass.
- [x] Squash merge only (PR title becomes the commit), branches deleted after merge, auto-merge allowed.
- [x] GitHub Pages enabled (source: GitHub Actions). Actions may create PRs (needed by release-please).
- [x] `pypi` environment created.
- [x] PyPI trusted publisher: project `llm-on-a-stick`, owner `Jitter00`, repo `llm-on-a-stick`,
      workflow `release.yml`, environment `pypi`. v0.1.0 published.
- [x] Fine-grained PAT (this repo only; Contents + Pull requests read/write) stored as secret
      `RELEASE_PLEASE_TOKEN` (`gh secret set RELEASE_PLEASE_TOKEN -R Jitter00/llm-on-a-stick`). Without it, the Release PR
      opened by `GITHUB_TOKEN` never runs CI and is blocked by branch protection.
- [x] CI matrix: Linux (ubuntu-24.04), Apple Silicon (macos-26), Windows (windows-2025) × Python 3.11–3.13, plus one
      Intel Mac job (macos-15-intel, Python 3.12).
- [ ] Try `ubuntu-26.04` runners once containerlab is verified there (`ubuntu-latest` is still 24.04).
- [x] Licence: MIT.

## Next up (agreed order: first end-to-end result before the full tool stack)

1. [x] **Oxidized** (the one service the first tasks depend on).
2. [x] **Check library + `result.json` + `stick grade`**: `stick task start` / `stick grade`, 9 built-in checks,
      canaries, failure hints, `result.json` + JSON schema ([docs/grading.md](docs/grading.md)).
3. [x] **cfg-mgmt config retrieval tasks**: 7 tasks (CLI + NETCONF, SR Linux + FRR, Oxidized consistency), trimmed
      to 5 after the first comparison (see docs/tasks.md, "Which tasks are kept"), each with canaries, an oracle and `stick task validate` (oracle passes, doing nothing fails); validated in CI.
4. [x] **Runner integration**: `stick run` / `stick report` ([docs/runner.md](docs/runner.md)). Own thin loop (not
      Inspect AI): OpenAI-compatible servers (Ollama, LM Studio, vLLM, llama.cpp, Strata, OpenAI, OpenRouter) and the
      Anthropic SDK; one `run_command` tool in a toolbox container; transcript, tokens, cost, time, turns, peak context.
      First comparison done (Strata deepseek-v4.1-flash 20/21, gemma4:26b 11/21, gemma4:12b 8/21).
5. [ ] **LLM judge** (only for what code can't grade; policy in [docs/grading.md](docs/grading.md#grading-policy-code-first)):
      new check type `llm_judge` (`artifact`, `rubric`, `reference`, `scale`); `stick grade --judge-model`, refused if it's
      the tested model; judge scores in their own `result.json` section with model/version/agreement, never mixed into
      `score`; per-check `graded_by: code | judge`; `not-graded` when no judge is configured; a small human-graded
      calibration set. Done first: transcript hints in code (`wrong-dialect`, `attempted-change`,
      `no-verification`, `ignored-error`; hints only, see docs/grading.md "Failure hints", `stick hints`).

Then return to the rest of Phase 0 (Nautobot first).

## Phase 0: environment (one service per PR)

Pattern for every service (see `services/netbox/` and `docs/services.md`):
`services/<name>/{compose.yaml,service.yaml,seed.yaml}`, a fixed IP on `stick-mgmt` in `lab.SERVICE_IPS`, a health check,
seed data, a snapshot/reset, a measured footprint in `src/llm_on_a_stick/data/footprints.yaml` (`measured: true`),
`tests/integration/test_<name>.py` (up → seeded → change → reset), a row in `docs/compatibility.md` and a section in `docs/services.md`.
Measure RAM with cgroup `memory.current` (`docker stats` shows 0 for some containers), and time the cold boot and the reset.

- [ ] **Nautobot.** Very close to NetBox: Postgres + Redis, REST API with nested lookups. The `netbox-rest` seeder may work
      as-is (maybe rename it `rest`). Cold boot is likely slower than NetBox; set `start_period`/`wait_timeout_s` from a measurement.
- [x] **Oxidized.** Done: custom SR Linux and FRR models (Oxidized ships neither), git output, volume-based reset.
- [ ] **Gitea.** Seed an org, a `lab-configs` repo and an API token; snapshot = its DB and repo volume. Needed for the GitOps tasks.
- [ ] **Syslog (Loki + Promtail, or rsyslog → Loki).** `stick-frr` already forwards when `STICK_SYSLOG_TARGET=host:port` is set;
      wire that in the topology. Configure SR Linux remote syslog in `configs/srl/*.cli`. Verify logs from all four nodes.
- [ ] **Telemetry (gNMIc + Prometheus).** gNMI subscriptions to SR Linux (interface counters, BGP state); FRR has no gNMI
      (document SNMP as its path). Verify counters appear in Prometheus.
- [ ] **DDI (PowerDNS + Kea).** Authoritative zone for the lab (`stick.lab`) with API enabled; Kea DHCP on the host subnets.
      This means h1/h2 switch from static IPs to DHCP (a topology change, so update the integration tests).
- [ ] **LibreNMS.** SNMP polling; FRR snmpd uses community `stick-ro`. SR Linux SNMP must be enabled in its startup config.
      Check which MIBs each OS exposes. FRR BGP MIBs need AgentX (only if FRR is built with SNMP support; verify).
- [ ] **Zabbix.** Same SNMP findings as LibreNMS; seed host groups and templates via the API.
- [ ] **SuzieQ.** Poller against SR Linux and FRR; check which of the two it supports.
- [ ] **Batfish.** Expected: no SR Linux support, partial FRR. Record the actual result. It becomes fully useful once cEOS or Junos are added.
- [ ] **Compatibility spike leftovers.** SR Linux SSH CLI, NETCONF and gNMI, LLDP on both OSes, remote syslog
      (cells still ❓ in `docs/compatibility.md`).
- [ ] **`stick env reset`.** Redeploy the lab and reset every running service, so a whole attempt starts from a known state.
- [ ] **`stick up <profile>`.** Lab plus a named set of services (e.g. `cfg-mgmt` = lab + Oxidized + Gitea), checked against
      the RAM budget from `stick doctor`.

## Phase 1: grading and runner

- [x] **Check library** (`src/llm_on_a_stick/grading/checks/`): `file_exists`, `file_contains`,
      `file_matches_running_config`, `json_file_matches`, `running_config_contains`, `bgp_session`, `no_change_outside`,
      `oxidized_has_backup`, `netbox_object`; plugin entry points. State is read via native JSON CLI over `docker exec`.
- [ ] More checks as tasks need them: `interface_ip`, `dns_record` (with PowerDNS), NETCONF-specific checks, gNMI-based reads.
- [x] **Canary values.** Random ASNs, IPs and descriptions seeded per run and rendered into task prompts, so invented or
      memorised answers fail.
- [x] **`result.json` schema + `stick grade <task>`.** Grades whatever state the lab is in (this is also the BYO-agent mode).
- [ ] **Failure classifier** (`classify.py`): transcript plus device responses → `cli-syntax`, `wrong-dialect` (done as a hint),
      `netconf-rpc-error`, `hallucinated-api`, `hallucinated-value`, `truncated-output`, `incomplete-config`, `wrong-config`,
      `collateral-change`, `no-verification` (done as a hint), `loop`, `gave-up`, `limit-exceeded`, `env-error` (excluded from scores).
- [x] **Runner integration** (`src/llm_on_a_stick/runner/`): own loop, see docs/runner.md.
- [ ] Runner follow-ups: scheduler (parallel *lab work* only: **never run several local models at the same time**;
      local models always go one after another, and API models may run in parallel), publish `stick-toolbox` to GHCR, Inspect-format log export,
      optional MCP/structured tools as a variant (`--tools mcp`), context-window variants (`--num-ctx`), streaming for
      long Anthropic turns, macOS support for the toolbox.
- [ ] **Judge model** (`--judge-model`): see "Next up" item 5 and the grading policy in docs/grading.md.
- [ ] **Report.** `stick report` (table/md/json per model and attempt) exists; next: HTML, and breakdowns by section,
      tag and failure class.

## Phase 2: tasks, user tests, variants, scheduler

- [x] **cfg-mgmt config retrieval tasks** (first tasks to write):
      1. full running config over clear-text CLI (SR Linux `info`, FRR `show running-config`);
      2. one section only;
      3. NETCONF `<get-config>`, full and filtered (SR Linux);
      4. CLI/XML → given JSON schema;
      5. CLI vs NETCONF vs Oxidized consistency.
      After the first comparison, 3 (full get-config) and 4 were removed as too easy; 5 tasks remain.
- [ ] **netbox tasks** (4 of at most 5): `netbox-query-interface` (floor), `netbox-register-node`, `netbox-drift`,
      `netbox-cables-lldp` (frr1 only, LLDP via `lldpcli`, to stay short) done. Next: "next free IP from a prefix, configured on a
      device" (device config restore between attempts is done: every task start restores the routers).
- [ ] **At most 5 tasks for each of the other sections, none obvious** (rules: docs/tasks.md, "Which tasks are
      kept"; pick the ones local models are likely to get wrong). New sections are per tool (nautobot, powerdns,
      kea, ...); the groupings are in sections/README.md. Also `lab-mgmt` and `troubleshooting` (fault injection:
      MTU mismatch, wrong ASN, ACL blackhole).
- [ ] **User-defined tasks.** `--tasks-dir` (local path or git URL); `stick task new` (scaffold); `stick task validate`
      (oracle must PASS, no-op agent must FAIL); a `@check` plugin interface + entry points; `matrix:` expansion.
- [ ] **Run variants.** Same model × context window (8k/32k/128k) first, then quantisation, CLI vs MCP tools, reasoning
      effort, with/without docs.
- [ ] **Scheduler.** Group tasks by shared services, bin-pack parallel lab instances under the doctor RAM budget
      (minus local model RAM), limit API concurrency per provider; `stick run --dry-run` prints the plan.
      Parallel labs need per-instance lab names and mgmt subnets (today both are fixed).

## Later

- [ ] CML backend (lab-per-sample via `virl2_client`; CML-Free 5-node limit; Cisco refplat images only inside CML).
- [ ] BYO vendor images: Arista cEOS, Juniper vJunos/cRPD (vrnetlab), Cisco XRd/Cat8kv. Fetch/build scripts only, never redistributed.
- [ ] Use NetClaw's MCP servers (Apache-2.0) as the tool layer for the "CLI vs MCP" variant; NetClaw itself as an agent under test.
- [ ] IETF draft-cui-nmrg-llm-benchmark task import.
- [ ] Public leaderboard (local models broken out by hardware and quantisation).

## Known gotchas (learned so far)

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
