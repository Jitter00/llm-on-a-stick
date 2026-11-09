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
terraform and LibreNMS tasks) do this themselves at `stick task start`, before their setup.

A reset is one of four kinds (`snapshot.kind` in `service.yaml`): `postgres` restores a database dump (NetBox,
Nautobot), `mysql` loads a `mariadb-dump` back into the running database (LibreNMS), `volumes` deletes the
service's volumes and recreates it (Oxidized), and `http` sends one request to the running service (moto).

A service that can't be configured from compose alone (LibreNMS: its admin user, API token and settings)
lists `init` steps: commands run in its containers once, after the first boot, followed by a restart.

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
