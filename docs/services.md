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
| `service.yaml` | how `stick` drives it: health URL, endpoints, credentials, seed data, snapshot/restore, and the environment variables its client tools need (`env:`, given to the toolbox and to task scripts) |
| `seed.yaml` | baseline objects every task starts from (idempotent: existing objects are skipped) |

Resetting between benchmark attempts restores a database snapshot rather than recreating containers, which is
what makes repeated runs cheap. Tasks that list a service under `reset_services` (all NetBox, Nautobot, aws and
terraform tasks) do this themselves at `stick task start`, before their setup.

A reset is one of three kinds (`snapshot.kind` in `service.yaml`): `postgres` restores a database dump (NetBox,
Nautobot), `volumes` deletes the service's volumes and recreates it (Oxidized), and `http` sends one request to the
running service (moto).

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
