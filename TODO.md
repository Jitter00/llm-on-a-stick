# TODO

Each item below is meant to be one PR (Conventional Commit title, e.g. `feat(svc): add Nautobot service`).
Items are roughly in order; dependencies are noted. Tick items off in the PR that completes them.

## Repo setup

- [x] Replace the `OWNER` placeholder with the GitHub user (`Jitter00`) in `pyproject.toml`, `mkdocs.yml` and the task schema.
- [x] Repo created (public): https://github.com/Jitter00/llm-on-a-stick; `main` pushed; PR #2 (`feat/netbox`) opened, CI green.
- [x] Branch protection on `main`: all 15 CI jobs required by name (a skipped required check counts as passing, so
      `build` alone isn't enough), up-to-date branches, linear history, conversations resolved, no force pushes. Admins can bypass.
- [x] Squash merge only (PR title becomes the commit), branches deleted after merge, auto-merge allowed.
- [x] GitHub Pages enabled (source: GitHub Actions). Actions may create PRs (needed by release-please).
- [x] `pypi` environment created.
- [ ] **You:** PyPI pending trusted publisher: project `llm-on-a-stick`, owner `Jitter00`, repo `llm-on-a-stick`,
      workflow `release.yml`, environment `pypi`. Needed before the first Release PR is merged.
- [ ] **You:** fine-grained PAT (this repo only; Contents + Pull requests read/write) stored as secret
      `RELEASE_PLEASE_TOKEN` (`gh secret set RELEASE_PLEASE_TOKEN -R Jitter00/llm-on-a-stick`). Without it, the Release PR
      opened by `GITHUB_TOKEN` never runs CI and is blocked by branch protection.
- [ ] When adding or renaming CI jobs, update the required checks in branch protection.
- [x] Licence: MIT.

## Phase 0: environment (one service per PR)

Pattern for every service (see `services/netbox/` and `docs/services.md`):
`services/<name>/{compose.yaml,service.yaml,seed.yaml}`, a fixed IP on `stick-mgmt` in `lab.SERVICE_IPS`, a health check,
seed data, a snapshot/reset, a measured footprint in `src/llm_on_a_stick/data/footprints.yaml` (`measured: true`),
`tests/integration/test_<name>.py` (up → seeded → change → reset), a row in `docs/compatibility.md` and a section in `docs/services.md`.
Measure RAM with cgroup `memory.current` (`docker stats` shows 0 for some containers), and time the cold boot and the reset.

- [ ] **Nautobot.** Very close to NetBox: Postgres + Redis, REST API with nested lookups. The `netbox-rest` seeder may work
      as-is (maybe rename it `rest`). Cold boot is likely slower than NetBox; set `start_period`/`wait_timeout_s` from a measurement.
- [ ] **Oxidized.** Needs a device inventory (generate it from the base topology) and credentials for SR Linux
      (`admin`/`NokiaSrl1!`) and FRR (`admin`/`admin`, which lands in vtysh). Find which Oxidized models fit SR Linux and FRR. Snapshot = its git repo/output dir.
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

- [ ] **Check library** (`src/llm_on_a_stick/checks/`): `bgp_session`, `interface_ip`, `running_config_contains`,
      `file_matches_running_config` (normalised diff), `netbox_object`, `dns_record`, `oxidized_has_backup`,
      `no_change_outside` (config diff limited to allowed devices). Read state via gNMI / native JSON CLI, not pyATS.
- [ ] **Canary values.** Random ASNs, IPs and descriptions seeded per run and rendered into task prompts, so invented or
      memorised answers fail.
- [ ] **`result.json` schema + `stick grade <task>`.** Grades whatever state the lab is in (this is also the BYO-agent mode).
- [ ] **Failure classifier** (`classify.py`): transcript plus device responses → `cli-syntax`, `wrong-dialect`,
      `netconf-rpc-error`, `hallucinated-api`, `hallucinated-value`, `truncated-output`, `incomplete-config`, `wrong-config`,
      `collateral-change`, `no-verification`, `loop`, `gave-up`, `limit-exceeded`, `env-error` (excluded from scores).
- [ ] **Runner integration.** Decide on Inspect AI (leading candidate) vs our own; models via Ollama/vLLM/LM Studio and
      API providers; tools = SSH/API/MCP to the lab. Record tokens, cost, wall time, turns and peak context.
- [ ] **Judge model** (`--judge-model`). Optional failure narratives; never the model under test by default.
- [ ] **Report.** HTML + JSON capability profile per model: by section, tag and failure class.

## Phase 2: tasks, user tests, variants, scheduler

- [ ] **cfg-mgmt config retrieval tasks** (first tasks to write):
      1. full running config over clear-text CLI (SR Linux `info`, FRR `show running-config`);
      2. one section only;
      3. NETCONF `<get-config>`, full and filtered (SR Linux);
      4. CLI/XML → given JSON schema;
      5. CLI vs NETCONF vs Oxidized consistency.
- [ ] 3–5 tasks for each of the other sections: `lab-mgmt`, `sot-ddi`, `validation-observability`, `troubleshooting`
      (fault injection: MTU mismatch, wrong ASN, ACL blackhole, NetBox drift).
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
  and a 40-char `SUPERUSER_API_TOKEN` are all set; `Token <hex>` returns 403. Cold boot is ~150 s, so the health check needs `start_period: 300s`.
- `docker stats` reports 0B for SR Linux containers; read cgroup `memory.current` instead.
- containerlab reuses an existing `stick-mgmt` network and doesn't delete it on destroy while services are attached.
- A local credential-guard hook blocks reading or writing `*.env` files; keep service settings inline in `compose.yaml`.
