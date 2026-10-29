#!/usr/bin/env python3
"""Compose the VDM specification files into one deterministic GraphQL SDL document.

VDM is authored as many small ``.graphql`` files under ``spec/``. A single
schema is easier to parse, hash, and diff, so vendoring concatenates them in a
stable (sorted-by-path) order.

Usage::

    python scripts/gen_vdm_sdl.py third_party/vdm third_party/generated/vdm.graphql
"""

from __future__ import annotations

import sys
from pathlib import Path

BANNER = """# ---------------------------------------------------------------------------
# GENERATED FILE - DO NOT EDIT.
#
# Composed from the pinned COVESA Vehicle Data Model (VDM) submodule.
# Regenerate with: ./scripts/vendor_standards.sh
#
# Source files (in order):
{files}
# ---------------------------------------------------------------------------

"""


def compose(vdm_root: Path) -> str:
    spec = vdm_root / "spec"
    files = sorted(spec.rglob("*.graphql"))
    if not files:
        raise SystemExit(f"ERROR: no .graphql files found under {spec}")

    header = BANNER.format(files="".join(f"#   {f.relative_to(vdm_root)}\n" for f in files))
    return header + "\n".join(f.read_text(encoding="utf-8").strip() for f in files) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    root, out = Path(argv[1]), Path(argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(compose(root), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
