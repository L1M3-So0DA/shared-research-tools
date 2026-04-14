from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from common import (
    analyze_markdown_files,
    merge_bibliography_files,
    parse_pandoc_messages,
    print_report,
    read_text,
    resolve_path,
    write_json,
)


DEFAULT_PANDOC_PATHS = [
    Path(r"C:\Program Files\Pandoc\pandoc.exe"),
]

DEFAULT_PANDOC_CROSSREF_PATHS = [
    Path(r"C:\Program Files\Pandoc\pandoc-crossref.exe"),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert Markdown to docx or pdf with Pandoc.")
    parser.add_argument("inputs", nargs="+", help="Markdown files to merge and convert.")
    parser.add_argument("--to", choices=["docx", "pdf"], required=True, help="Target output format.")
    parser.add_argument("--output", required=True, help="Output file path.")
    parser.add_argument("--bib", nargs="*", default=[], help="Bibliography files used by citeproc.")
    parser.add_argument("--csl", help="CSL file used for bibliography formatting.")
    parser.add_argument("--csl-url", help="Optional URL to download the CSL file if it is missing.")
    parser.add_argument("--crossref-config", help="YAML file used by pandoc-crossref.")
    parser.add_argument("--reference-doc", help="Reference docx file used for Word formatting.")
    parser.add_argument("--workspace-root", default=".", help="Root directory for resolving relative paths.")
    parser.add_argument(
        "--equation-mode",
        choices=["word", "raw-latex", "native"],
        help="Equation handling mode. docx defaults to 'word'; pdf defaults to 'native'.",
    )
    parser.add_argument("--pdf-engine", default="xelatex", help="PDF engine used for pdf conversion.")
    parser.add_argument(
        "--pandoc-path",
        default="pandoc",
        help="Pandoc executable or absolute path. Fixed install paths are checked before PATH lookup.",
    )
    parser.add_argument(
        "--pandoc-crossref",
        default="pandoc-crossref",
        help="pandoc-crossref executable or absolute path. Fixed install paths are checked before PATH lookup.",
    )
    parser.add_argument(
        "--resource-path",
        action="append",
        default=[],
        help="Additional resource path entries for Pandoc. Repeat this flag to add more paths.",
    )
    parser.add_argument(
        "--metadata",
        action="append",
        default=[],
        help="Extra metadata entries in key=value form. Repeat this flag to add more.",
    )
    parser.add_argument(
        "--reference-section-title",
        default="参考文献",
        help="Title used for the generated bibliography section.",
    )
    parser.add_argument(
        "--report-json",
        help="Optional path to write a structured conversion report. Defaults to <output>.conversion-report.json.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Stop before Pandoc if preflight validation finds missing citations, unresolved crossrefs, or broken images.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep the generated temporary merged Markdown and bibliography files for debugging.",
    )
    return parser


def resolve_executable(command_or_path: str, preferred_paths: list[Path] | None = None) -> str | None:
    for preferred_path in preferred_paths or []:
        if preferred_path.exists():
            return str(preferred_path)

    as_path = Path(command_or_path)
    if as_path.exists():
        return str(as_path)
    return shutil.which(command_or_path)


def maybe_download_csl(csl_path: Path, csl_url: str | None) -> None:
    if csl_path.exists() or not csl_url:
        return
    csl_path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(csl_url, csl_path)


def determine_equation_mode(target: str, requested_mode: str | None) -> str:
    if requested_mode:
        return requested_mode
    return "word" if target == "docx" else "native"


def get_version_output(executable: str) -> str:
    result = subprocess.run([executable, "--version"], capture_output=True, text=True)
    return (result.stdout or result.stderr).strip()


def inspect_toolchain(pandoc: str, pandoc_crossref: str) -> dict:
    pandoc_version_output = get_version_output(pandoc)
    crossref_version_output = get_version_output(pandoc_crossref)

    pandoc_match = re.search(r"pandoc(?:\.exe)?\s+([0-9][^\s]*)", pandoc_version_output, re.IGNORECASE)
    crossref_match = re.search(r"built with Pandoc v([0-9][^,\s]*)", crossref_version_output, re.IGNORECASE)

    pandoc_version = pandoc_match.group(1) if pandoc_match else None
    crossref_built_with = crossref_match.group(1) if crossref_match else None
    compatible = True
    warning = None

    if pandoc_version and crossref_built_with:
        pandoc_major = pandoc_version.split(".", 1)[0]
        crossref_major = crossref_built_with.split(".", 1)[0]
        compatible = pandoc_major == crossref_major
        if not compatible:
            warning = (
                f"Pandoc version {pandoc_version} does not match pandoc-crossref build target "
                f"{crossref_built_with}. This commonly breaks filter execution."
            )

    return {
        "pandoc_version": pandoc_version,
        "pandoc_version_output": pandoc_version_output,
        "pandoc_crossref_build_target": crossref_built_with,
        "pandoc_crossref_version_output": crossref_version_output,
        "compatible": compatible,
        "warning": warning,
    }


def build_input_format(equation_mode: str) -> str:
    input_format = "markdown"
    if equation_mode == "raw-latex":
        input_format += "-tex_math_dollars-tex_math_single_backslash-tex_math_double_backslash-raw_tex"
    return input_format


def merge_markdown_files(input_files: list[Path], remove_tags: bool) -> str:
    merged_parts: list[str] = []
    for file_path in input_files:
        content = read_text(file_path)
        if remove_tags:
            content = content.replace("\r\n", "\n")
            content = re.sub(r"\\tag\{.*?\}", "", content)
        merged_parts.append(content.rstrip())
    return "\n\n".join(part for part in merged_parts if part) + "\n"


def build_resource_path_args(workspace_root: Path, input_files: list[Path], extra_paths: list[str]) -> list[str]:
    ordered_paths: list[str] = []
    seen: set[str] = set()

    candidates = [path.parent for path in input_files]
    candidates.extend(resolve_path(path, workspace_root) for path in extra_paths)

    for candidate in candidates:
        normalized = str(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered_paths.append(normalized)

    return ["--resource-path", os.pathsep.join(ordered_paths)] if ordered_paths else []


def parse_metadata_values(items: list[str]) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    for item in items:
        if "=" not in item:
            raise ValueError(f"Invalid metadata item '{item}'. Expected key=value.")
        key, value = item.split("=", 1)
        parsed.append((key.strip(), value.strip()))
    return parsed


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root).resolve()
    input_files = [resolve_path(path, workspace_root) for path in args.inputs]
    bib_files = [resolve_path(path, workspace_root) for path in args.bib]
    output_path = resolve_path(args.output, workspace_root)
    csl_path = resolve_path(args.csl, workspace_root) if args.csl else None
    crossref_config = resolve_path(args.crossref_config, workspace_root) if args.crossref_config else None
    reference_doc = resolve_path(args.reference_doc, workspace_root) if args.reference_doc else None
    report_path = (
        resolve_path(args.report_json, workspace_root)
        if args.report_json
        else output_path.with_name(output_path.name + ".conversion-report.json")
    )

    missing_inputs = [str(path) for path in input_files if not path.exists()]
    if missing_inputs:
        for path in missing_inputs:
            print(f"Input file not found: {path}", file=sys.stderr)
        return 2

    pandoc = resolve_executable(args.pandoc_path, DEFAULT_PANDOC_PATHS)
    if not pandoc:
        print(f"Pandoc executable not found: {args.pandoc_path}", file=sys.stderr)
        return 2

    pandoc_crossref = resolve_executable(args.pandoc_crossref, DEFAULT_PANDOC_CROSSREF_PATHS)
    if not pandoc_crossref:
        print(f"pandoc-crossref executable not found: {args.pandoc_crossref}", file=sys.stderr)
        return 2

    toolchain = inspect_toolchain(pandoc, pandoc_crossref)
    if toolchain["warning"]:
        print(toolchain["warning"], file=sys.stderr)

    if csl_path:
        maybe_download_csl(csl_path, args.csl_url)
        if not csl_path.exists():
            print(f"CSL file not found: {csl_path}", file=sys.stderr)
            return 2

    if crossref_config and not crossref_config.exists():
        print(f"Crossref config not found: {crossref_config}", file=sys.stderr)
        return 2

    if reference_doc and not reference_doc.exists():
        print(f"Reference doc not found: {reference_doc}", file=sys.stderr)
        return 2

    preflight = analyze_markdown_files(input_files, bib_files, workspace_root)
    print_report(preflight)
    if args.strict and preflight["findings"]:
        write_json(
            {
                "success": False,
                "stage": "preflight",
                "preflight": preflight,
                "toolchain": toolchain,
                "messages": [],
            },
            report_path,
        )
        print("Strict mode enabled; conversion stopped because preflight findings were detected.", file=sys.stderr)
        return 1

    equation_mode = determine_equation_mode(args.to, args.equation_mode)
    input_format = build_input_format(equation_mode)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        metadata_items = parse_metadata_values(args.metadata)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    keep_temp_dir = None
    with tempfile.TemporaryDirectory(prefix="pandoc-md-publish-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        merged_markdown = temp_dir / "merged.md"
        merged_markdown.write_text(
            merge_markdown_files(input_files, remove_tags=(equation_mode == "word")),
            encoding="utf-8",
        )

        merged_bib = None
        bib_merge_report = None
        if bib_files:
            merged_bib = temp_dir / "merged.bib"
            bib_merge_report = merge_bibliography_files(bib_files, merged_bib)

        command = [pandoc, str(merged_markdown), "-f", input_format, "-o", str(output_path)]
        command.extend(["--filter", pandoc_crossref])

        if crossref_config:
            command.extend(["-M", f"crossrefYaml={crossref_config}"])

        if merged_bib:
            command.extend(["--citeproc", "--bibliography", str(merged_bib)])

        if csl_path:
            command.extend(["--csl", str(csl_path)])

        command.extend(["-M", f"reference-section-title={args.reference_section_title}"])
        command.extend(["-M", "link-citations=true"])

        for key, value in metadata_items:
            command.extend(["-M", f"{key}={value}"])

        command.extend(build_resource_path_args(workspace_root, input_files, args.resource_path))

        if args.to == "docx" and reference_doc:
            command.extend([f"--reference-doc={reference_doc}"])

        if args.to == "pdf":
            command.extend(["--pdf-engine", args.pdf_engine])

        result = subprocess.run(command, capture_output=True, text=True)
        parsed_messages = parse_pandoc_messages(result.stdout, result.stderr)

        if args.keep_temp:
            keep_temp_dir = output_path.parent / (output_path.stem + "-pandoc-debug")
            keep_temp_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(merged_markdown, keep_temp_dir / merged_markdown.name)
            if merged_bib and merged_bib.exists():
                shutil.copy2(merged_bib, keep_temp_dir / merged_bib.name)

        report = {
            "success": result.returncode == 0,
            "stage": "conversion",
            "target": args.to,
            "output": str(output_path),
            "equation_mode": equation_mode,
            "toolchain": toolchain,
            "command": command,
            "preflight": preflight,
            "bib_merge": bib_merge_report,
            "messages": parsed_messages,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "temp_dir": str(keep_temp_dir) if keep_temp_dir else None,
        }
        write_json(report, report_path)

        if result.stdout.strip():
            print(result.stdout.strip())
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)

        warning_count = len([message for message in parsed_messages if message["severity"] == "warning"])
        error_count = len([message for message in parsed_messages if message["severity"] == "error"])
        if result.returncode == 0:
            print(f"Conversion succeeded: {output_path}")
        else:
            print(f"Conversion failed with return code {result.returncode}.", file=sys.stderr)
        print(f"Pandoc message summary: warnings={warning_count}, errors={error_count}")
        print(f"Structured report written to: {report_path}")

        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())