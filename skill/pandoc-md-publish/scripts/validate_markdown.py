from __future__ import annotations

import argparse
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from common import analyze_markdown_files, print_report, resolve_path, write_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate Markdown inputs before Pandoc conversion.")
    parser.add_argument("inputs", nargs="+", help="Markdown files to validate.")
    parser.add_argument("--bib", nargs="*", default=[], help="Bibliography files used by citeproc.")
    parser.add_argument(
        "--workspace-root",
        default=".",
        help="Root directory used to resolve relative paths and print relative file names.",
    )
    parser.add_argument("--report-json", help="Optional path to write the validation report as JSON.")
    parser.add_argument(
        "--fail-on-findings",
        action="store_true",
        help="Return a non-zero exit code when warnings such as missing citations or missing images are found.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root).resolve()
    input_files = [resolve_path(path, workspace_root) for path in args.inputs]
    bib_files = [resolve_path(path, workspace_root) for path in args.bib]

    missing_inputs = [str(path) for path in input_files if not path.exists()]
    if missing_inputs:
        for path in missing_inputs:
            print(f"Input file not found: {path}", file=sys.stderr)
        return 2

    report = analyze_markdown_files(input_files, bib_files, workspace_root)
    print_report(report)

    if args.report_json:
        write_json(report, resolve_path(args.report_json, workspace_root))

    if args.fail_on_findings and report["findings"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())