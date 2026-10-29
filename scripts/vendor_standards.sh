#!/usr/bin/env bash
# Pin-verify and regenerate the COVESA standards artifacts.
#
#   ./scripts/vendor_standards.sh              verify pins, regenerate, check hashes
#   ./scripts/vendor_standards.sh --update     regenerate and refresh hashes in the lock file
#
# Artifacts (checked in, so builds are reproducible offline):
#   third_party/generated/vss.json     - VSS signal catalog, exported from the pinned submodule
#   third_party/generated/vdm.graphql  - composed VDM SDL
#
# Requires: git, and vss-tools installed in .venv (see requirements-standards.txt).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

LOCK="third_party/standards.lock.json"
GEN="third_party/generated"
PY="${PYTHON:-.venv/bin/python}"
VSPEC="${VSPEC:-.venv/bin/vspec}"
UPDATE=0
[ "${1:-}" = "--update" ] && UPDATE=1

[ -f "$LOCK" ] || { echo "ERROR: missing $LOCK" >&2; exit 1; }
command -v git >/dev/null || { echo "ERROR: git is required" >&2; exit 1; }

lock_field() {  # lock_field <standard> <dotted.key>
    "$PY" - "$LOCK" "$1" "$2" <<'PY'
import json, sys
lock, std, key = sys.argv[1], sys.argv[2], sys.argv[3]
node = json.load(open(lock))["standards"][std]
for part in key.split("."):
    node = node[part]
print(node)
PY
}

echo "==> Initializing submodules"
if [ ! -f third_party/vss/spec/VehicleSignalSpecification.vspec ]; then
    git submodule update --init --depth 1 third_party/vss
fi
if [ ! -d third_party/vdm/spec ]; then
    git submodule update --init --depth 1 third_party/vdm
fi

echo "==> Verifying pins match $LOCK"
for std in vss vdm; do
    want="$(lock_field "$std" commit)"
    have="$(git -C "$(lock_field "$std" path)" rev-parse HEAD)"
    if [ "$want" != "$have" ]; then
        echo "ERROR: $std is at $have but the lock file pins $want" >&2
        echo "       run: git -C $(lock_field "$std" path) checkout $want" >&2
        exit 1
    fi
    printf '    %-4s %s  (%s)\n' "$std" "${have:0:12}" "$(lock_field "$std" ref)"
done

echo "==> Exporting VSS -> $GEN/vss.json"
command -v "$VSPEC" >/dev/null 2>&1 || {
    echo "ERROR: $VSPEC not found. Install the pinned tool: uv pip install -r requirements-standards.txt" >&2
    exit 1
}
mkdir -p "$GEN"
VSS_DIR="$(lock_field vss path)"
"$VSPEC" export json \
    -u "$VSS_DIR/$(lock_field vss inputs.units)" \
    -q "$VSS_DIR/$(lock_field vss inputs.quantities)" \
    -s "$VSS_DIR/$(lock_field vss inputs.root_vspec)" \
    --strict \
    -o "$GEN/vss.json" >/dev/null

echo "==> Composing VDM SDL -> $GEN/vdm.graphql"
"$PY" scripts/gen_vdm_sdl.py "$(lock_field vdm path)" "$GEN/vdm.graphql"

echo "==> Verifying artifacts parse"
"$PY" - "$GEN" <<'PY'
import json, sys
from pathlib import Path
gen = Path(sys.argv[1])
vss = json.loads((gen / "vss.json").read_text(encoding="utf-8"))
count = 0
def walk(node):
    global count
    for value in node.values():
        if isinstance(value, dict):
            if "datatype" in value:
                count += 1
            walk(value)
walk(vss)
print(f"    vss.json   ok ({count} signals)")
try:
    from graphql import build_schema
except ImportError:
    print("    vdm.graphql skipped (graphql-core not installed)")
else:
    schema = build_schema((gen / "vdm.graphql").read_text(encoding="utf-8"))
    print(f"    vdm.graphql ok ({len(schema.type_map)} types)")
PY

echo "==> Updating artifact hashes"
"$PY" - "$LOCK" "$GEN" "$UPDATE" <<'PY'
import hashlib, json, sys
from pathlib import Path

lock_path, gen, update = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3] == "1"
data = json.loads(lock_path.read_text(encoding="utf-8"))

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

artifacts = {"vss": {"vss.json": "third_party/generated/vss.json"},
             "vdm": {"vdm.graphql": "third_party/generated/vdm.graphql"}}

mismatch = False
for std, files in artifacts.items():
    recorded = data["standards"][std].get("artifacts", {})
    fresh = {name: {"path": rel, "sha256": sha(gen / name)} for name, rel in files.items()}
    for name, meta in fresh.items():
        old = recorded.get(name, {}).get("sha256")
        if old and old != meta["sha256"] and not update:
            print(f"    MISMATCH {name}: {old[:12]} -> {meta['sha256'][:12]}", file=sys.stderr)
            mismatch = True
        else:
            print(f"    {name:<14} {meta['sha256'][:12]} ok")
    if update:
        data["standards"][std]["artifacts"] = fresh

if update:
    lock_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"    refreshed {lock_path}")
if mismatch:
    print("ERROR: generated artifacts differ from the lock file. "
          "If intentional, rerun with --update and commit both.", file=sys.stderr)
    raise SystemExit(1)
PY

echo "==> Standards vendor complete"
