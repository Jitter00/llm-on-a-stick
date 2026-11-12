# Services

The tool stack runs in Docker Compose, one project per service, started on demand. Every service joins the lab's
management network `stick-mgmt` (172.30.30.0/24) at a fixed address, so lab devices and agents always find it in the
same place. The network is shared: whichever starts first (the lab or a service) creates it, and tearing the lab down
leaves it in place while services are still attached.

```bash
uv run stick svc list
uv run stick svc up netbox        # start, seed baseline data, take a snapshot (first boot ~2.5 min)
uv run stick svc status
uv run stick svc reset netbox     # back to the baseline snapshot (~20 s)
uv run stick svc snapshot netbox  # make the current state the new baseline
uv run stick svc down netbox      # stop; add --volumes to delete data and the snapshot
```

`stick svc up a b c` starts services one after another, so a small machine never boots them all at once.

## How a service is defined

Each service is a directory under `services/`:

| File | Purpose |
|---|---|
| `compose.yaml` | containers, health checks, fixed `stick-mgmt` address; credentials are lab defaults, overridable with `STICK_*` environment variables |
| `service.yaml` | how `stick` drives it: health URL, endpoints, credentials, seed data or API settings, one-time `init` steps, snapshot/restore, and the environment variables its client tools need (`env:`, given to the toolbox and to task scripts) |
| `seed.yaml` | baseline objects every task starts from (idempotent: existing objects are skipped) |

Resetting between benchmark attempts restores a database snapshot rather than recreating containers, which is
what makes repeated runs cheap. Tasks that list a service under `reset_services` (all NetBox, Nautobot, aws,
terraform, LibreNMS and Zabbix tasks) do this themselves at `stick task start`, before their setup.

A reset is one of four kinds (`snapshot.kind` in `service.yaml`): `postgres` restores a database dump (NetBox,
Nautobot), `mysql` loads a `mariadb-dump` back into the database (LibreNMS, while it runs; Zabbix, with its server
stopped), `volumes` deletes the
service's volumes and recreates it (Oxidized), and `http` sends one request to the running service (moto).

A service that can't be configured from compose alone (LibreNMS: its admin user, API token and settings)
lists `init` steps: commands run in its containers once, after the first boot, followed by a restart. Zabbix
has them too (its API token and two settings).

A service is healthy when its `health.url` answers 2xx. Zabbix's JSON-RPC API answers 200 to everything, with
errors in the body, so its health check posts a request (`health.post`) and looks for a text in the answer
(`health.expect`).

## MCP servers

Six services also have an **MCP server**: what a model works through in the
[`mcp`](tasks.md#mcp-the-same-tools-through-mcp-servers) and [`loki`](tasks.md#loki-the-routers-syslog) sections, instead of a shell. They are the published
servers, pinned, all in one image (`images/mcp`, built as `stick-mcp:dev`; one virtualenv each, from
hash-pinned requirement files). `stick run` starts one container per server and attempt and talks to it over
stdio.

| Service | Server | Version | Tools shown | Can change things | Notes |
|---|---|---|---|---|---|
| netbox | [netboxlabs/netbox-mcp-server](https://github.com/netboxlabs/netbox-mcp-server) | 1.2.2 | 4 of 4 | no | Read-only by design; takes object types (`dcim.device`) and API filters; returns 5 objects unless asked for more |
| moto | [awslabs.aws-api-mcp-server](https://github.com/awslabs/mcp/tree/main/src/aws-api-mcp-server) | 1.6.0 | 1 of 2 | yes | `call_aws` runs one AWS CLI command per call. It accepts another endpoint only on a loopback address, and downloads AWS's service reference at every start (internet access needed). AWS has stopped developing it. `suggest_aws_commands` asks a hosted AWS service: not shown |
| nautobot | [nautobot-mcp](https://github.com/bsmeding/nautobot-mcp-server) | 0.2.5 | 28 of 77 | yes (`NAUTOBOT_MCP_ALLOW_WRITES`) | A young community server. Typed list and get tools, free prefixes and addresses, generic REST and GraphQL tools |
| librenms | [librenms-mcp](https://github.com/mhajder/librenms-mcp) | 1.13.0 | 33 of 113 | yes | Hides SNMP communities in what it returns |
| zabbix | [zabbix-mcp](https://github.com/mhajder/zabbix-mcp) | 0.8.0 | 16 of 53 | yes | Supports Zabbix up to 7.4: it only talks to 8.0 with `ZABBIX_SKIP_VERSION_CHECK`, and the calls the tasks use work |
| loki | [mcp-grafana](https://github.com/grafana/mcp-grafana) | 2.2.0 | 6 of 63 | no (started with `--disable-write`) | Grafana's own server; it reads Loki through Grafana's datasource, so a query names the datasource (`loki`). 10 lines per query unless asked for more, 100 at most; timestamps in nanoseconds. Not shown: dashboards, alerting, incidents, Prometheus, and `grafana_api_request` |

A server is declared in the service's `service.yaml`:

```yaml
mcp:
  server: zabbix            # its name in the stick-mcp image
  version: 0.8.0            # for the record; the image pins it
  env: {ZABBIX_URL: ..., ZABBIX_TOKEN: ...}
  allow: [host_get, maintenance_create, ...]   # the tools the model is shown; leave out to show all
```

The `allow` list keeps the tool list small enough for local models (every tool's name, description and schema
is sent on every turn): a unit test holds each server to 40 tools and 24,000 characters. Each service's lab
tests start its server, compare the tools it offers with `tests/fixtures/mcp_tools/<service>.json` and make one
call. To move a server to a new version: change `images/mcp/requirements/<server>.in`, compile it again (the
command is in the Dockerfile), raise the image's version label and `MCP_IMAGE_VERSION`, then refresh the
snapshot with `STICK_UPDATE_MCP_SNAPSHOTS=1` and read the diff.

## NetBox

| | |
|---|---|
| Version | NetBox 4.7.4 (`netboxcommunity/netbox:v4.7.4-5.1.1`), Postgres 18.6, Valkey 9.1.3 |
| Web UI (host) | <http://127.0.0.1:8081> (`STICK_NETBOX_PORT`), user `admin` / `admin` |
| API (from the lab) | `http://172.30.30.100:8080/api/` |
| API token | `Authorization: Bearer nbt_stickadmin01.0123456789abcdef0123456789abcdef01234567` (v2 token) |
| RAM (measured) | ~1.45 GB: NetBox 1046 MiB, worker 257 MiB, Postgres 146 MiB, Valkey 4 MiB |
| Timings (measured) | cold first boot ~150 s on a desktop, 5–6 min on a 4-vCPU CI runner; `svc reset` ~21 s |

Seed data: site `stick-lab`; manufacturers Nokia, FRRouting, Generic; roles spine/leaf/host; platforms srlinux, frr,
linux; device types 7220 IXR-D2L, FRR container, Linux host. The lab's devices are **not** seeded: documenting the
lab in NetBox is a benchmark task.

!!! note "NetBox 4.5+ API tokens"
    NetBox 4.5 introduced v2 tokens (`nbt_<key>.<token>`, sent as `Bearer`). The container only creates one when
    `API_TOKEN_PEPPER_1`, a 12-character `SUPERUSER_API_KEY` and a 40-character `SUPERUSER_API_TOKEN` are all set.
    Older guides that use `Authorization: Token <40 hex>` won't work against this version, which is itself a useful
    test of whether a model's NetBox knowledge is current.

## Nautobot

| | |
|---|---|
| Version | Nautobot 3.2.8 (`networktocode/nautobot:3.2.8-py3.12`), Postgres 18.6, Valkey 9.1.3 |
| Web UI (host) | <http://127.0.0.1:8082> (`STICK_NAUTOBOT_PORT`), user `admin` / `admin` |
| API (from the lab) | `http://172.30.30.102:8080/api/`, GraphQL at `/api/graphql/` |
| API token | `Authorization: Token 0123456789abcdef0123456789abcdef01234567` |
| RAM (measured) | ~1.27 GB after some API use: Nautobot 867 MiB, Postgres 401 MiB, Valkey 5 MiB |
| Timings (measured) | cold first boot ~150 s on a desktop; `svc reset` ~25 s (every start runs `post_upgrade`) |

There is no Celery worker: it only runs Jobs and webhooks, which no task uses, and its health check would add
about 30 s to every reset.

Seed data: location type Site and location `stick-lab`; manufacturers Nokia, FRRouting, Generic; roles Spine, Leaf,
Host; platforms SR Linux, FRR, Linux; device types 7220 IXR-D2L, FRR container, Linux host; a namespace
`stick-lab` holding the management prefix 172.30.30.0/24. Statuses (Active, Connected, ...) and the Global
namespace come with Nautobot. As with NetBox, the lab's devices are **not** seeded.

!!! note "Nautobot is not NetBox"
    Nautobot 2.0 forked away from NetBox's data model, and 3.x keeps it. What trips models that know NetBox:

    - the API token is sent as `Token`, not `Bearer`: the NetBox 4 form gets HTTP 403;
    - no sites, regions or slugs: devices sit in a **location**, related objects are referenced by UUID or by
      attributes (`{"role": {"name": "Leaf"}}`);
    - `status` is required on devices, interfaces, IP addresses, prefixes and cables, and is a Status object
      (`{"name": "Active"}`, case-sensitive), not a choice like `"active"`;
    - IP addresses live in a **namespace** and need a parent prefix in it;
    - an IP address is linked to an interface through `ipam/ip-address-to-interface`; NetBox's
      `assigned_object_type`/`assigned_object_id` are **silently ignored**, so the address is created unlinked, and
      it can't then be a device's primary IP;
    - cables still use `termination_a_type`/`termination_a_id` (NetBox 4 moved to `a_terminations`);
    - related objects come back as `{id, object_type, url}` unless the request adds `?depth=1`.

## moto (emulated AWS)

| | |
|---|---|
| Version | moto 5.2.5 (`motoserver/moto:5.2.5`), one container, everything in memory |
| AWS API (host) | <http://127.0.0.1:8083> (`STICK_MOTO_PORT`); dashboard at `/moto-api/` |
| AWS API (from the lab) | `http://172.30.30.103:5000` |
| Credentials | any access key and secret (not checked); account `123456789012`; region `eu-west-1` |
| Environment for the tools | `AWS_ENDPOINT_URL=http://127.0.0.1:8083 AWS_ACCESS_KEY_ID=testing AWS_SECRET_ACCESS_KEY=testing AWS_DEFAULT_REGION=eu-west-1` |
| Client tools (toolbox image) | AWS CLI 2.39.6, boto3 1.43.126, Terraform 1.17.1 with `hashicorp/aws` 6.72.0 |
| RAM (measured) | ~180 MiB after EC2, IAM and S3 use |
| Timings (measured) | start ~3 s; `svc reset` ~0.2 s |

moto answers the AWS API for EC2 and VPC, IAM, S3 and many more services, so the `aws` and `terraform` sections run
in seconds, for free, and start from an empty account every time. It needs neither the lab nor a seed: each task's
setup creates what it needs.

The tools find it through environment variables (`AWS_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`, from `env:` in `services/moto/service.yaml`). The runner sets them
in the toolbox of every task that requires moto, so `aws`, boto3 and an empty `provider "aws" {}` block work as
they would against a configured account. The model is tested on AWS, not on emulator flags.

Terraform's AWS provider is unpacked in the toolbox image at `/usr/share/terraform/plugins`, where Terraform
looks for local copies: `terraform init` takes about a second and needs no registry. Other providers would be
downloaded.

!!! note "What an emulator can and can't test"
    moto stores resources and returns them; it enforces nothing. A security group filters no packets, an IAM
    policy denies no call, an instance runs no software. So the tasks are graded on **resource state** (what
    `describe-*` returns, what `terraform plan` reports), never on behaviour. Other limits found so far:

    - moto is laxer than AWS: it accepts some calls AWS would refuse (resizing a running instance), so a wrong
      order of operations can pass;
    - Terraform's `aws_s3_bucket` fails against an endpoint given as an IP address (the provider calls
      S3 Control at `<account>.127.0.0.1`), so the terraform tasks use VPC, EC2 and IAM resources. S3 works with
      the AWS CLI and boto3;
    - the grader looks at one region (eu-west-1): resources created elsewhere count as not created.

## LibreNMS

| | |
|---|---|
| Version | LibreNMS 26.10.2 (`librenms/librenms:26.10.2`, web + dispatcher), MariaDB 11.8, Valkey 9.1.3 |
| Web UI (host) | <http://127.0.0.1:8084> (`STICK_LIBRENMS_PORT`), user `admin` / `Stick-lab-9x!Qz` |
| API (from the lab) | `http://172.30.30.104:8000/api/v0/`; the dispatcher polls from 172.30.30.105 |
| API token | `X-Auth-Token: 0123456789abcdef0123456789abcdef` (`STICK_LIBRENMS_TOKEN`) |
| RAM (measured) | ~830 MiB with 3 devices: dispatcher 426 MiB, web 212 MiB, MariaDB 189 MiB, Valkey 5 MiB |
| Timings (measured) | cold first boot ~30 s on a desktop (plus the images); `svc reset` ~1 s; discover + poll one SR Linux ~6 s |

No seed: the baseline is an empty LibreNMS, and each task's setup adds the devices it needs over SNMPv2c
(community `stick-ro` on every router, set in `images/frr/snmpd.conf` and `configs/srl/*.cli`). The dispatcher
discovers and polls a device within seconds of its being added through the API, so a model can see the result
of its work; the grader doesn't wait for it and runs `lnms device:poll` itself. Settings made by `init`:
no fallback community (by default LibreNMS retries a failing device with `public` and adds it anyway), and no
automatic discovery of neighbours over LLDP, BGP or OSPF.

What LibreNMS makes of the lab: SR Linux is detected as `srlinux` (hardware `7220 IXR-D2L`), its port
descriptions become `ifAlias`, and it needs a few seconds to show a configuration change over SNMP. FRR is
`linux` (net-snmp): interface descriptions set in FRR do **not** reach `ifAlias`, and there is no BGP MIB.

!!! note "What trips models"
    - the token header is `X-Auth-Token`, not `Authorization`; there is also a newer `/api/v1` with a
      different shape, and most knowledge is about `/api/v0`;
    - `POST /devices` checks SNMP reachability and refuses a wrong community; `force_add: true` adds the
      device anyway, as down;
    - `POST /rules` creates the rule and still answers an error about transports (26.10): a retry makes a
      duplicate, and the alert checks want exactly one rule of that name;
    - alert rules take effect at the next poll of each device; `GET /alerts?state=1` lists what fired;
    - a device deleted and added again has a new id and no history: the `librenms_unchanged` check counts
      that as deleting it.

## Zabbix

| | |
|---|---|
| Version | Zabbix 8.0.0 (`zabbix/zabbix-server-mysql` and `zabbix-web-nginx-mysql`, `alpine-8.0.0`), MariaDB 11.8 |
| Web UI (host) | <http://127.0.0.1:8085> (`STICK_ZABBIX_PORT`), user `Admin` / `zabbix` |
| API | JSON-RPC: `POST http://127.0.0.1:8085/api_jsonrpc.php`; from the lab `http://172.30.30.107:8080/api_jsonrpc.php`. The server polls from 172.30.30.106 |
| API token | `Authorization: Bearer 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef` (`STICK_ZABBIX_TOKEN`) |
| RAM (measured) | ~1.25 GiB with 4 hosts: MariaDB 1140 MiB (mostly cache), web 53 MiB, server 47 MiB |
| Timings (measured) | cold first boot ~25 s on a desktop (plus the images); `svc reset` ~10 s; a new host is reached over SNMP ~10 s after a forced poll |

No seed: the baseline is a Zabbix with no hosts, and each task's setup adds the ones it needs over SNMPv2c,
the way Zabbix's own templates expect it: the interface's community is `{$SNMP_COMMUNITY}` and the host has
that macro. Hosts use the stock template `Network Generic Device by SNMP`. Settings made by `init`: a fixed API
token for `Admin`, the global `{$SNMP_COMMUNITY}` set to something that is not a lab community (it ships as
`public`), the image's own "Zabbix server" host removed, and a host group `Routers`. The server is tuned for
a small lab: it reads new configuration every 5 s and gives up on an unreachable host after a few seconds.

Zabbix polls on its own schedule (a port's status once a minute, port discovery once an hour). Setup scripts
and the grader don't wait: they have the server reload its configuration (`zabbix_server -R
config_cache_reload`) and poll the items they need now (API `task.create`, type 6), then wait for the result
they are looking for. A reset stops the server, loads the database and starts the server again: loaded
under a running server, what it holds in memory (problems, availability) would be written back.

What Zabbix makes of the lab: both SR Linux and FRR answer the generic template. Port discovery only keeps
ports that are administratively up (3 on srl1 out of the box), and names each port's items after the port
and its description, e.g. `Interface ethernet-1/1(to frr1): Operational status`, key
`net.if.status[ifOperStatus.32768]` (1 = up, 2 = down).

!!! note "What trips models"
    - every call is a `POST` of a JSON-RPC envelope to one URL, and an error comes back with HTTP 200;
    - the token goes in `Authorization: Bearer`; the `auth` property in the body, which most examples
      still show, was removed in 7.2, and `user.login` is not needed;
    - `host.create` takes any community: a wrong one only shows as an interface with `available: 2`
      (0 = not known yet, 1 = reached);
    - `status: 0` means a host (or trigger) is enabled;
    - the community is usually not on the interface but in the host macro `{$SNMP_COMMUNITY}`;
    - a trigger expression names the host and the item key (`last(/srl1/net.if.status[ifOperStatus.32776])=2`),
      and the key of a port's item has its ifIndex, not its name;
    - maintenance times are epoch seconds, the default type is "with data collection", and a maintenance
      needs a time period as well as `active_since`/`active_till`;
    - a host deleted and added again has a new id and no history: the `zabbix_unchanged` check counts that
      as deleting it.

## Loki

The routers' syslog. Three containers: **Loki** keeps the lines, **Alloy** receives syslog from the routers
and pushes it to Loki, and **Grafana** has Loki as its only datasource. Models reach it through Grafana's MCP
server only.

| | |
|---|---|
| Version | Loki 3.7.9, Alloy 1.21.3, Grafana 13.3.1 |
| Grafana (host) | <http://127.0.0.1:8086> (`STICK_GRAFANA_PORT`), user `admin` / `Stick-lab-9x!Qz` (`STICK_GRAFANA_PASSWORD`); datasource uid `loki` |
| Loki API (host) | `http://127.0.0.1:8087/loki/api/v1/` (`STICK_LOKI_PORT`), no authentication; task scripts use it |
| Syslog (from the lab) | `172.30.30.108:1514`, UDP and TCP, RFC 5424 |
| Labels | `host` (the router's name), `app` (the program), `severity`, `facility`, `job="syslog"` |
| Start | about 10 s |
| Reset | about 5 s: Loki and Alloy are removed with Loki's volume and started again, so the store is empty |
| Memory | about 0.4 GB (Grafana most of it) |

- **The routers always send**, whether the service runs or not (`topologies/base.clab.yml` sets
  `STICK_SYSLOG_TARGET` on the FRR nodes, `configs/srl/*.cli` configures `system logging remote-server`). What
  they log while Loki is down is lost. A lab deployed before this was added does not send: rebuild the FRR
  image and deploy again (`stick image build frr`, `stick env down`, `stick env up`).
- **What is logged.** SR Linux: every commit with the user's name, every CLI command, logins, port and BGP
  events. FRR: BGP neighbour changes and SSH logins; not who changed its configuration.
- **Noise is part of it.** SR Linux's gRPC server logs a warning every second, about 7,000 lines an hour from
  the two of them: a query without a filter returns little else.
- **Routers are restored before services are reset**, so what the restore itself logs (a commit, sessions
  that drop) is gone when a task's setup starts.
- **Failed logins.** FRR's `sshd` runs with `PerSourcePenalties=no`, so that each of several failed logins
  in a row is answered and logged. SR Linux's turns a source away after a few.

## Oxidized

| | |
|---|---|
| Version | Oxidized 0.37.0 (`oxidized/oxidized:0.37.0`) |
| Web UI / API (host) | <http://127.0.0.1:8888> (`STICK_OXIDIZED_PORT`) |
| API (from the lab) | `http://172.30.30.101:8888/nodes.json` |
| Useful endpoints | `/nodes.json` (status per device), `/node/fetch/<node>` (latest backup), `/node/next/<node>` (back up now), `/node/version.json?node_full=<node>` (history) |
| Inventory | `services/oxidized/router.db`: srl1, srl2, frr1, frr2 (hosts aren't backed up); a test keeps it in sync with the topology |
| RAM (measured) | ~47 MiB |
| Timings (measured) | start ~5 s; all four devices backed up within ~5 s; `svc reset` ~1 s |

Bring the lab up first: Oxidized backs up every device when it starts. Backups go into a git repo, so each change is a
new version. Reset deletes that repo and Oxidized re-fetches every device: the baseline is "one backup per device, of
whatever the device runs now".

!!! note "Custom models"
    Oxidized 0.37 has no model for SR Linux or FRR (upstream PRs ytti/oxidized#2927, #2036 and #2572 were never
    merged). `services/oxidized/model/` adds both. They use SSH **exec** mode, so no prompt matching is needed:
    SR Linux runs `info flat`, and FRR's `admin` user has vtysh as its login shell, so the exec becomes
    `vtysh -c "show running-config"`.
