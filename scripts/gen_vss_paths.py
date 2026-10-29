#!/usr/bin/env python3
"""Generate ``capability_framework/semantics/vss_paths.py`` from the catalog.

The catalog names VSS templates; this script expands them against the pinned
VSS and writes the concrete paths as Python constants. Capability code imports
the constants instead of writing path strings by hand, so a typo cannot compile
into a runtime bug.

Usage::

    python scripts/gen_vss_paths.py            # write the module
    python scripts/gen_vss_paths.py --check    # fail if it is out of date
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from capability_framework.semantics import VssCatalog, load_catalog  # noqa: E402

HEADER = '''# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# ---------------------------------------------------------------------------
# GENERATED FILE - DO NOT EDIT.
#
# Expanded from catalog/capabilities/*.yaml and verified against the pinned VSS.
# Regenerate with: python scripts/gen_vss_paths.py
# ---------------------------------------------------------------------------

"""Concrete VSS signal paths for every capability in the catalog."""

from __future__ import annotations

from types import MappingProxyType

#: VSS release the paths were verified against.
VSS_VERSION = {version!r}

#: signal id -> {{instance: path}}
SIGNALS = MappingProxyType({{
{signals}}})

#: every concrete path, deduplicated and sorted
ALL_PATHS = (
{all_paths}
)
'''


def const_name(signal_id: str) -> str:
    return signal_id.replace(".", "_").replace("-", "_").upper()


def render(catalog, vss_version: str) -> str:
    signal_lines: list[str] = []
    all_paths: set[str] = set()

    for spec in sorted(catalog.values(), key=lambda s: s.name):
        signal_lines.append(f"    # {spec.name}")
        by_id: dict[str, dict[str, str]] = {}
        for instance, path, signal in spec.expanded_signals():
            by_id.setdefault(signal.id, {})[instance] = path
            all_paths.add(path)
        for signal_id in sorted(by_id):
            signal_lines.append(f"    {signal_id!r}: MappingProxyType({{")
            for instance in sorted(by_id[signal_id]):
                signal_lines.append(f"        {instance!r}: {by_id[signal_id][instance]!r},")
            signal_lines.append("    }),")
    signal_lines.append("")
    # Emit top-level aliases after the SIGNALS block by appending to the module.
    aliases: list[str] = []
    for spec in sorted(catalog.values(), key=lambda s: s.name):
        seen: set[str] = set()
        for _, _, signal in spec.expanded_signals():
            if signal.id in seen:
                continue
            seen.add(signal.id)
            aliases.append(f"{const_name(signal.id)} = SIGNALS[{signal.id!r}]")

    body = HEADER.format(
        version=vss_version,
        signals="\n".join(signal_lines),
        all_paths="\n".join(f"    {path!r}," for path in sorted(all_paths)),
    )
    if aliases:
        body += "\n# Per-signal aliases\n" + "\n".join(aliases) + "\n"
    body += f"\n__all__ = [\"ALL_PATHS\", \"SIGNALS\", \"VSS_VERSION\", {', '.join(repr(a.split(' = ')[0]) for a in aliases)}]\n"
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "catalog" / "capabilities")
    parser.add_argument("--vss", type=Path, default=ROOT / "third_party" / "generated" / "vss.json")
    parser.add_argument("--lock", type=Path, default=ROOT / "third_party" / "standards.lock.json")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "src" / "capability_framework" / "semantics" / "vss_paths.py")
    parser.add_argument("--check", action="store_true", help="fail instead of writing when stale")
    args = parser.parse_args(argv)

    import json

    catalog = load_catalog(args.catalog)
    version = json.loads(args.lock.read_text(encoding="utf-8"))["standards"]["vss"]["version_label"]

    # Fail generation if any path does not resolve — the catalog is the input,
    # the standard is the authority.
    vss = VssCatalog.from_json(args.vss)
    missing = sorted(
        path for spec in catalog.values() for _, path, _ in spec.expanded_signals()
        if path not in vss
    )
    if missing:
        print("ERROR: catalog paths missing from the pinned VSS:", file=sys.stderr)
        for path in missing:
            print(f"  {path}", file=sys.stderr)
        return 1

    rendered = render(catalog, version)
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.is_file() else ""
        if current != rendered:
            print(f"ERROR: {args.out} is out of date; run scripts/gen_vss_paths.py", file=sys.stderr)
            return 1
        print(f"{args.out} is up to date")
        return 0

    args.out.write_text(rendered, encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
