# Licensed under the Apache License, Version 2.0 (the "License");
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

"""
capability_framework.checker.cli
================================
``capability-check`` — validate catalog entries against the pinned standards.

Exit codes: 0 clean, 1 findings (errors, or warnings under ``--strict``), 2 usage.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..semantics import CatalogError
from .engine import CheckContext, report, run_checks

__all__ = ["main"]


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from *start* to the directory holding the standards lock file."""
    for candidate in [start or Path.cwd(), *Path(start or Path.cwd()).parents]:
        if (candidate / "third_party" / "standards.lock.json").is_file():
            return candidate
    # Installed as a wheel: fall back to the current directory.
    return Path.cwd()


def build_parser() -> argparse.ArgumentParser:
    root = find_repo_root()
    parser = argparse.ArgumentParser(
        prog="capability-check",
        description="Check capability catalog entries against the pinned COVESA standards.",
    )
    parser.add_argument("--catalog", type=Path, default=root / "catalog" / "capabilities",
                        help="directory of <capability>.yaml entries")
    parser.add_argument("--contracts", type=Path, default=root / "contracts",
                        help="directory holding northbound OpenAPI contracts")
    parser.add_argument("--standards", type=Path, default=root / "third_party" / "generated",
                        help="directory holding generated vss.json and vdm.graphql")
    parser.add_argument("--tests", type=Path, default=root / "tests",
                        help="directory searched for the tests operations reference")
    parser.add_argument("--baseline", type=Path,
                        default=root / "src" / "capability_framework" / "checker" / "baseline.yaml",
                        help="time-boxed exemptions (see docs/capability-rules.md)")
    parser.add_argument("--only", action="append", metavar="CAPABILITY",
                        help="limit to one capability (repeatable)")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    parser.add_argument("--format", choices=("text", "json", "junit"), default="text")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colour")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    vss_json = args.standards / "vss.json"
    vdm_graphql = args.standards / "vdm.graphql"

    missing = [str(p) for p in (vss_json, vdm_graphql) if not p.is_file()]
    if missing:
        print(
            "ERROR: missing generated standards artifacts: " + ", ".join(missing) +
            "\n       run ./scripts/vendor_standards.sh",
            file=sys.stderr,
        )
        return 2

    try:
        context = CheckContext.from_paths(
            catalog_dir=args.catalog,
            contracts_dir=args.contracts,
            repo_root=find_repo_root(args.catalog.parent),
            vss_json=vss_json,
            vdm_graphql=vdm_graphql,
            tests_dir=args.tests,
            baseline_path=args.baseline,
        )
        result = run_checks(context, only=args.only)
    except CatalogError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(report(result, fmt=args.format, use_color=not args.no_color and sys.stdout.isatty()))
    if not result.ok:
        return 1
    if args.strict and result.warnings:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
