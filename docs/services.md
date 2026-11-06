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
| `service.yaml` | how `stick` drives it: health URL, endpoints, credentials, seed data, snapshot/restore |
| `seed.yaml` | baseline objects every task starts from (idempotent: existing objects are skipped) |

Resetting between benchmark attempts restores a database snapshot rather than recreating containers, which is
what makes repeated runs cheap.

## NetBox

| | |
|---|---|
| Version | NetBox 4.7.4 (`netboxcommunity/netbox:v4.7.4-5.1.1`), Postgres 18.6, Valkey 9.1.3 |
| Web UI (host) | <http://127.0.0.1:8081> (`STICK_NETBOX_PORT`), user `admin` / `admin` |
| API (from the lab) | `http://172.30.30.100:8080/api/` |
| API token | `Authorization: Bearer nbt_stickadmin01.0123456789abcdef0123456789abcdef01234567` (v2 token) |
| RAM (measured) | ~1.45 GB: NetBox 1046 MiB, worker 257 MiB, Postgres 146 MiB, Valkey 4 MiB |
| Timings (measured) | cold first boot ~150 s; `svc reset` ~21 s |

Seed data: site `stick-lab`; manufacturers Nokia, FRRouting, Generic; roles spine/leaf/host; platforms srlinux, frr,
linux; device types 7220 IXR-D2L, FRR container, Linux host. The lab's devices are **not** seeded: documenting the
lab in NetBox is a benchmark task.

!!! note "NetBox 4.5+ API tokens"
    NetBox 4.5 introduced v2 tokens (`nbt_<key>.<token>`, sent as `Bearer`). The container only creates one when
    `API_TOKEN_PEPPER_1`, a 12-character `SUPERUSER_API_KEY` and a 40-character `SUPERUSER_API_TOKEN` are all set.
    Older guides that use `Authorization: Token <40 hex>` won't work against this version, which is itself a useful
    test of whether a model's NetBox knowledge is current.
