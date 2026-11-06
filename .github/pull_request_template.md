## What and why

<!-- The PR title becomes the squash-merge commit on main, so it must be a Conventional Commit:
     feat(cfg-mgmt): add NETCONF get-config retrieval task
     fix(doctor): cap RAM budget by Docker Desktop VM size -->

## How I tested it

- [ ] `uv run pytest` (unit)
- [ ] `uv run pytest -m lab` (base lab), if lab assets or env code changed
- [ ] `uv run stick task lint`, if tasks changed
