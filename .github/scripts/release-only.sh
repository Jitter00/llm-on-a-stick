#!/bin/bash
# Is this pull request a release-please Release PR that changes nothing but the release metadata?
#   release-only.sh <base sha> <head sha> <head branch>   -> prints "true" or "false" (and why, on stderr)
#
# If so, ci-pr.yml skips the full OS x Python matrix and the lab: branch protection requires PRs to be up to
# date with main before merging (and we squash), so main's code was already fully tested by the PR that
# merged it. Anything beyond a version bump and the changelog gets the full run.
set -euo pipefail
base=$1 head=$2 branch=$3

no() { echo "full CI: $*" >&2; echo false; exit 0; }

[[ "$branch" == release-please--* ]] || no "not a release-please branch ($branch)"

# Only these files, and in them only version lines.
while read -r file; do
    case "$file" in
        CHANGELOG.md | .release-please-manifest.json) ;;
        pyproject.toml | uv.lock) pattern='^version = "[^"]+"$' ;;
        src/llm_on_a_stick/__init__.py) pattern='^[[:space:]]*__version__ = "[^"]+"$' ;;
        *) no "the release PR changes $file" ;;
    esac
    case "$file" in
        CHANGELOG.md | .release-please-manifest.json) continue ;;
    esac
    # Changed lines (not the +++/--- headers) must all be version lines.
    other=$(git diff -U0 "$base...$head" -- "$file" | grep -E '^[+-]' | grep -vE '^(\+\+\+|---) ' \
        | cut -c2- | grep -vE "$pattern" || true)
    [[ -z "$other" ]] || no "$file changes more than its version: $(head -n 1 <<<"$other")"
done < <(git diff --name-only "$base...$head")

# uv.lock: only this package's own entry may change (another package's version line would also match).
lock_names=$(git diff -U3 "$base...$head" -- uv.lock | grep -E '^ name = ' | sort -u || true)
[[ -z "$lock_names" || "$lock_names" == ' name = "llm-on-a-stick"' ]] \
    || no "uv.lock changes other packages: $lock_names"

echo "release-only: version bump and changelog" >&2
echo true
