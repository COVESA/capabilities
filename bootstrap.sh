#!/usr/bin/env bash
# Set up this repository's Python environment (macOS and Linux).
#
# Inside a workspace tracker checkout (a superproject holding workspace.yaml and
# bootstrap.sh) this hands off to the tracker's
# ./bootstrap.sh, which links .venv to the one shared workspace environment.
# A standalone clone gets its own .venv, built with uv:
#   requirements-dev.txt (else requirements.txt), then every tracked
#   pyproject.toml installed editable.
#
#   ./bootstrap.sh                          set up (or update) the environment
#   BOOTSTRAP_STANDALONE=1 ./bootstrap.sh   ignore an enclosing tracker
#   PYTHON_VERSION=3.13 ./bootstrap.sh      standalone interpreter (default 3.14)
#
# Kept bash 3.2 compatible: that is the bash macOS ships.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_VERSION="${PYTHON_VERSION:-3.14}"

if [ "${BOOTSTRAP_STANDALONE:-0}" != "1" ]; then
    dir="$REPO_ROOT"
    while parent="$(git -C "$dir" rev-parse --show-superproject-working-tree 2>/dev/null)" && [ -n "$parent" ]; do
        if [ -f "$parent/workspace.yaml" ] && [ -x "$parent/bootstrap.sh" ]; then
            echo "==> Inside the workspace tracker ($parent); using its shared environment"
            exec "$parent/bootstrap.sh" "$@"
        fi
        dir="$parent"
    done
fi

command -v uv >/dev/null 2>&1 || {
    echo "ERROR: uv is required: https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
}
cd "$REPO_ROOT"

if [ -L .venv ]; then
    echo "ERROR: .venv is a symlink to a shared environment; refusing to rebuild it standalone." >&2
    exit 1
fi

have="$(.venv/bin/python -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || true)"
# Compare at the precision requested, so both 3.14 and 3.14.3 reuse a 3.14.3 venv.
want_parts="$(printf '%s' "$PYTHON_VERSION" | awk -F. '{print NF}')"
have_cut="$(printf '%s' "$have" | cut -d. -f1-"$want_parts")"
if [ "$have_cut" != "$PYTHON_VERSION" ]; then
    [ -n "$have" ] && echo "==> Replacing .venv (Python $have) with Python $PYTHON_VERSION"
    uv venv --clear --quiet --python "$PYTHON_VERSION" .venv
fi

reqs=()
if [ -f requirements-dev.txt ]; then
    reqs=(-r requirements-dev.txt)
elif [ -f requirements.txt ]; then
    reqs=(-r requirements.txt)
fi

# One resolve, so this repo's own packages satisfy siblings that depend on them.
editable=()
while IFS= read -r pyproject; do
    editable+=(-e "./$(dirname "$pyproject")")
done < <(git ls-files '*pyproject.toml' 2>/dev/null)

if [ $(( ${#reqs[@]} + ${#editable[@]} )) -gt 0 ]; then
    echo "==> Installing ${reqs[1]:-no requirements file} + $((${#editable[@]} / 2)) local package(s) editable"
    uv pip install --quiet --python .venv/bin/python ${reqs[@]+"${reqs[@]}"} ${editable[@]+"${editable[@]}"}
fi

echo "==> Ready: $(.venv/bin/python --version) in $REPO_ROOT/.venv"
