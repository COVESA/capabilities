#!/usr/bin/env bash
# Move the pinned COVESA standards to new refs and report what changed.
#
#   ./scripts/bump_standards.sh v6.2                    # VSS only (VDM unchanged)
#   ./scripts/bump_standards.sh v6.2 36bc939           # VSS + VDM
#
# The script does the mechanical part and refuses to hide the consequences:
#   1. update the submodules and the lock file refs
#   2. regenerate artifacts
#   3. report VSS changes with `vspec diff` (when a previous snapshot exists)
#   4. run the capability rules and the full test suite
#
# It never commits. Review the artifact diff, the rule findings, and the report under
# docs/upgrades/ before committing.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VSS_REF="${1:-}"
VDM_REF="${2:-}"
LOCK="third_party/standards.lock.json"
PY="${PYTHON:-.venv/bin/python}"

if [ -z "$VSS_REF" ]; then
    echo "usage: $0 <vss-ref> [vdm-ref]" >&2
    exit 2
fi

TODAY="$(date +%Y-%m-%d)"
REPORT="docs/upgrades/${TODAY}-${VSS_REF}.md"
mkdir -p "$(dirname "$REPORT")"

echo "==> Recording the current state"
PREV_VSS="$("$PY" -c "import json;print(json.load(open('$LOCK'))['standards']['vss']['ref'])")"
PREV_VSS_COMMIT="$("$PY" -c "import json;print(json.load(open('$LOCK'))['standards']['vss']['commit'])")"
PREV_VDM_COMMIT="$("$PY" -c "import json;print(json.load(open('$LOCK'))['standards']['vdm']['commit'])")"
mkdir -p third_party/snapshots
cp third_party/generated/vss.json "third_party/snapshots/vss-${PREV_VSS_COMMIT:0:12}.json"

echo "==> Fetching VSS $VSS_REF"
git -C third_party/vss fetch --depth 1 origin tag "$VSS_REF" 2>/dev/null || git -C third_party/vss fetch origin "$VSS_REF"
git -C third_party/vss checkout -q "$VSS_REF"
NEW_VSS_COMMIT="$(git -C third_party/vss rev-parse HEAD)"

NEW_VDM_COMMIT="$PREV_VDM_COMMIT"
if [ -n "$VDM_REF" ]; then
    echo "==> Fetching VDM $VDM_REF"
    git -C third_party/vdm fetch --depth 1 origin "$VDM_REF" 2>/dev/null || git -C third_party/vdm fetch origin
    git -C third_party/vdm checkout -q "$VDM_REF"
    NEW_VDM_COMMIT="$(git -C third_party/vdm rev-parse HEAD)"
fi

echo "==> Updating $LOCK"
"$PY" - "$LOCK" "$VSS_REF" "$NEW_VSS_COMMIT" "$NEW_VDM_COMMIT" <<'PY'
import json, sys
lock_path, vss_ref, vss_commit, vdm_commit = sys.argv[1:5]
data = json.load(open(lock_path))
vss = data["standards"]["vss"]
vss["ref"] = vss_ref
vss["commit"] = vss_commit
label = vss_ref.lstrip("v")
vss["version_label"] = ".".join(label.split(".")[:2])
data["standards"]["vdm"]["commit"] = vdm_commit
data["standards"]["vdm"]["ref"] = vdm_commit
json.dump(data, open(lock_path, "w"), indent=2)
open(lock_path, "a").write("\n")
print(f"    vss {vss_ref} ({vss_commit[:12]}), vdm {vdm_commit[:12]}")
PY

echo "==> Regenerating artifacts"
./scripts/vendor_standards.sh --update

echo "==> VSS diff"
DIFF_FILE="third_party/snapshots/noexpand-${NEW_VSS_COMMIT:0:12}.json"
if .venv/bin/vspec export json-noexpand --help >/dev/null 2>&1; then
    .venv/bin/vspec export json --no-expand \
        -u third_party/vss/spec/units.yaml -q third_party/vss/spec/quantities.yaml \
        -s third_party/vss/spec/VehicleSignalSpecification.vspec --strict \
        -o "$DIFF_FILE" >/dev/null 2>&1 || true
fi
if [ -f "$DIFF_FILE" ] && [ -f "third_party/snapshots/noexpand-${PREV_VSS_COMMIT:0:12}.json" ]; then
    .venv/bin/vspec diff \
        "third_party/snapshots/noexpand-${PREV_VSS_COMMIT:0:12}.json" "$DIFF_FILE" \
        > "$REPORT" 2>/dev/null || echo "vspec diff unavailable on this version" >> "$REPORT"
    echo "    wrote $REPORT"
else
    echo "    no previous no-expand snapshot; skipping structured diff" > "$REPORT"
fi

echo "==> Regenerating VSS path constants"
"$PY" scripts/gen_vss_paths.py

echo "==> Capability rules"
set +e
PYTHONPATH=src "$PY" -m capability_framework.checker --strict --no-color
CHECKS=$?
echo "==> Tests"
PYTHONPATH=src "$PY" -m pytest tests -q
TESTS=$?
set -e

cat >> "$REPORT" <<EOF

## Framework impact

- capability-check exit code: $CHECKS
- test suite exit code: $TESTS
- capability API versions touched: review \`catalog/capabilities/*.yaml\` diffs
EOF

echo
echo "Bump complete. Review:"
echo "  git diff third_party/generated third_party/standards.lock.json"
echo "  $REPORT"
echo "If a mapping broke, bump the capability's api_version and note it in the report."
[ "$CHECKS" -eq 0 ] && [ "$TESTS" -eq 0 ]
