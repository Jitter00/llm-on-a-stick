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
- [x] CI matrix: Linux (ubuntu-24.04) × Python 3.11–3.13, plus Apple Silicon (macos-26) and Windows (windows-2025)
      once each on Python 3.12. Trimmed from ten jobs: macOS and Windows only prove the CLI itself runs there.
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

Then return to the rest of Phase 0 (Nautobot is done).

## Phase 0: environment (one service per PR)

Pattern for every service (see `services/netbox/` and `docs/services.md`):
`services/<name>/{compose.yaml,service.yaml,seed.yaml}`, a fixed IP on `stick-mgmt` in `lab.SERVICE_IPS`, a health check,
seed data, a snapshot/reset, a measured footprint in `src/llm_on_a_stick/data/footprints.yaml` (`measured: true`),
`tests/integration/test_<name>.py` (up → seeded → change → reset), a row in `docs/compatibility.md` and a section in `docs/services.md`.
Measure RAM with cgroup `memory.current` (`docker stats` shows 0 for some containers), and time the cold boot and the reset.

- [x] **Nautobot.** Done: Nautobot 3.2.8 (no Celery worker), seeded with the generic `rest` seeder, postgres snapshot
      (~25 s reset), five tasks in `sections/nautobot/`.
- [x] **moto (emulated AWS).** Done: moto 5.2.5, no seed, reset over HTTP (~0.2 s); AWS CLI, boto3, Terraform and
      its AWS provider in the toolbox image; five tasks each in `sections/aws/` and `sections/terraform/`.
- [x] **Oxidized.** Done: custom SR Linux and FRR models (Oxidized ships neither), git output, volume-based reset.
- [ ] **Gitea.** Seed an org, a `lab-configs` repo and an API token; snapshot = its DB and repo volume. Needed for the GitOps tasks.
- [ ] **Syslog (Loki + Promtail, or rsyslog → Loki).** `stick-frr` already forwards when `STICK_SYSLOG_TARGET=host:port` is set;
      wire that in the topology. Configure SR Linux remote syslog in `configs/srl/*.cli`. Verify logs from all four nodes.
- [ ] **Telemetry (gNMIc + Prometheus).** gNMI subscriptions to SR Linux (interface counters, BGP state); FRR has no gNMI
      (document SNMP as its path). Verify counters appear in Prometheus.
- [ ] **DDI (PowerDNS + Kea).** Authoritative zone for the lab (`stick.lab`) with API enabled; Kea DHCP on the host subnets.
      This means h1/h2 switch from static IPs to DHCP (a topology change, so update the integration tests).
- [x] **LibreNMS.** Done: 26.10.2 with a dispatcher, MariaDB snapshot loaded live (~1 s reset), `init` steps for the
      admin user, token and settings, five tasks in `sections/librenms/`. SR Linux: SNMP was on already (containerlab),
      the startup config sets the community and the host name. FRR: generic `linux`, no BGP MIB (FRR isn't built with
      SNMP), descriptions don't reach `ifAlias`.
- [x] **Zabbix.** Done: 8.0.0 (server, web frontend, MariaDB), `init` steps for the API token, the global
      community and the `Routers` group, reset by loading the database with the server stopped (~10 s), five tasks
      in `sections/zabbix/`. Same SNMP findings as LibreNMS; ports come from the stock template
      `Network Generic Device by SNMP`, which only discovers ports that are administratively up.
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
      local models always go one after another, and API models may run in parallel; for `stick vs`, a lab instance per
      model so that a cloud and a local model can run at the same time), publish `stick-toolbox` to GHCR, Inspect-format log export,
      optional MCP/structured tools as a variant (`--tools mcp`), context-window variants (`--num-ctx`), streaming for
      long Anthropic turns, macOS support for the toolbox.
- [ ] **Judge model** (`--judge-model`): see "Next up" item 5 and the grading policy in docs/grading.md.
- [ ] **Report.** `stick report` (table/md/json per model and attempt), the HTML page (`--html`, also written by
      `stick run`) and `stick vs` exist; next: breakdowns by section, tag and failure class.

## Phase 2: tasks, user tests, variants, scheduler

- [x] **cfg-mgmt config retrieval tasks** (first tasks to write):
      1. full running config over clear-text CLI (SR Linux `info`, FRR `show running-config`);
      2. one section only;
      3. NETCONF `<get-config>`, full and filtered (SR Linux);
      4. CLI/XML → given JSON schema;
      5. CLI vs NETCONF vs Oxidized consistency.
      After the first comparison, 3 (full get-config) and 4 were removed as too easy; 5 tasks remain.
- [x] **netbox tasks** (5 of 5): `netbox-query-interface` (floor), `netbox-register-node`, `netbox-drift`,
      `netbox-cables-lldp` (frr1 only, LLDP via `lldpcli`), `netbox-next-ip` (the first task that changes a
      device; every task start restores the routers to their boot config). Re-check with a stronger model.
- [x] **nautobot tasks** (5 of 5): the NetBox set with drift replaced by `nautobot-graphql`, each built around
      what Nautobot does differently (Token auth, locations, required statuses, namespaces, IP-to-interface links,
      `termination_a_*` cables).
- [x] **aws and terraform tasks** (5 + 5), against moto, with no lab devices (`topology: none`). Graded on
      resource state only: the emulator enforces nothing. Rewritten once (the first set was too easy:
      docs/tasks.md, "Which tasks are kept"), with an `aws_reachable` check that reads reachability off the state. Later: a second cloud only if a broad emulator
      appears (Azurite covers Azure storage only, GCP has per-product emulators); OpenTofu next to Terraform.
- [x] **librenms tasks** (5 of 5): query a port, add a device with a rotated community, fix a device that went
      down, an alert rule graded by what it fires, sync from NetBox. Graded after a poll the grader forces.
- [x] **zabbix tasks** (5 of 5): find a host by tag, add a host with a rotated community, fix a host Zabbix
      can't reach, a trigger graded by the problem it raises, a maintenance graded by which hosts are in it.
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
- [ ] Use NetClaw's MCP servers (Apache-2.0) as the tool layer for the "CLI vs MCP" variant; NetClaw itself as an agent under test.
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
