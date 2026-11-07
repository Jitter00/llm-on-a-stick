# Contributing

## Setup

```bash
uv sync
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
```

## Commit messages: Conventional Commits

Every commit, and every PR title (squash merge uses it as the commit on `main`), must follow
[Conventional Commits](https://www.conventionalcommits.org/):

```
feat(cfg-mgmt): add NETCONF get-config retrieval task
fix(doctor): cap RAM budget by Docker Desktop VM size
docs: explain the compatibility matrix
ci(release): publish stick-frr to GHCR
feat!: rename task.yaml `checks` field   # breaking change
```

Types: `feat`, `fix`, `perf`, `docs`, `refactor`, `test`, `ci`, `build`, `chore`, `revert`. Use a section or module as
the scope. The commit-msg hook and CI both check this.

Versions and the changelog come from these messages (release-please): `fix` → patch, `feat` → minor, breaking →
major (minor while we're below 1.0).

## Pipeline

| When | What runs |
|---|---|
| Push to a branch | lint → unit tests (Linux, Python 3.12) |
| Pull request to `main` | PR-title check; lint → unit tests (Linux, macOS 26 Apple Silicon, Windows × Python 3.11–3.13, plus one Intel Mac job) + base-lab integration tests → build (wheel, multi-arch `stick-frr`) → release dry run → docs preview → `ci-ok` gate (the only check branch protection requires) |
| Merge to `main` | release-please updates the Release PR |
| Merge of the Release PR | build → GitHub Release + tag → PyPI, `ghcr.io/<owner>/stick-frr`, docs on GitHub Pages |

## Tests

```bash
uv run pytest            # unit tests, no Docker needed
uv run pytest -m lab     # deploys the base lab; needs Docker + containerlab + `stick image build frr`
```
