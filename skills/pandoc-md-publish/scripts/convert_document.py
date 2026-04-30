from __future__ import annotations

import argparse
import json
import importlib
from importlib import metadata
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

SKILL_REFERENCES_DIR = CURRENT_DIR.parent / "references"

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

TOOLCHAIN_HINT_FILE = Path.home() / ".pandoc-md-publish" / "windows-toolchain.json"


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
        help="Pandoc executable or absolute path. PATH lookup is checked before the Windows fallback install path.",
    )
    parser.add_argument(
        "--pandoc-crossref",
        default="pandoc-crossref",
        help="pandoc-crossref executable or absolute path. PATH lookup is checked before the Windows fallback install path.",
    )
    parser.add_argument(
        "--download-pandoc",
        action="store_true",
        help="Download pandoc through pypandoc when no system pandoc is available.",
    )
    parser.add_argument(
        "--pandoc-version",
        help="Optional pandoc version to download when --download-pandoc is used.",
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
    as_path = Path(command_or_path)
    if as_path.exists():
        return str(as_path)

    resolved = shutil.which(command_or_path)
    if resolved:
        return resolved

    for preferred_path in preferred_paths or []:
        if preferred_path.exists():
            return str(preferred_path)

    return None


def resolve_executable_from_preferred_paths(command_or_path: str, preferred_paths: list[Path] | None = None) -> str | None:
    as_path = Path(command_or_path)
    if as_path.exists():
        return str(as_path)

    for preferred_path in preferred_paths or []:
        if preferred_path.exists():
            return str(preferred_path)

    return shutil.which(command_or_path)


def load_registered_toolchain_paths() -> tuple[list[Path], list[Path]]:
    try:
        payload = json.loads(TOOLCHAIN_HINT_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return [], []

    if not isinstance(payload, dict):
        return [], []

    pandoc_paths: list[Path] = []
    crossref_paths: list[Path] = []
    seen: set[str] = set()

    def add_candidate(candidate: Path, destination: list[Path]) -> None:
        normalized = str(candidate)
        if normalized in seen:
            return
        if candidate.exists():
            destination.append(candidate)
            seen.add(normalized)

    install_dir = payload.get("install_dir")
    if isinstance(install_dir, str) and install_dir:
        install_path = Path(install_dir)
        add_candidate(install_path / "pandoc.exe", pandoc_paths)
        add_candidate(install_path / "pandoc-crossref.exe", crossref_paths)

    pandoc_path = payload.get("pandoc_path")
    if isinstance(pandoc_path, str) and pandoc_path:
        add_candidate(Path(pandoc_path), pandoc_paths)

    crossref_path = payload.get("pandoc_crossref_path")
    if isinstance(crossref_path, str) and crossref_path:
        add_candidate(Path(crossref_path), crossref_paths)

    return pandoc_paths, crossref_paths


def resolve_support_file(
    raw_path: str | None,
    workspace_root: Path,
    fallback_filename: str | None = None,
) -> tuple[Path | None, str | None]:
    if raw_path:
        resolved_path = resolve_path(raw_path, workspace_root)
        if resolved_path.exists():
            return resolved_path, "workspace"

        if fallback_filename:
            fallback_path = SKILL_REFERENCES_DIR / fallback_filename
            if fallback_path.exists():
                return fallback_path, "skill-references"

        return resolved_path, "workspace-missing"

    if fallback_filename:
        fallback_path = SKILL_REFERENCES_DIR / fallback_filename
        if fallback_path.exists():
            return fallback_path, "skill-references"

    return None, None


def resolve_bibliography_files(raw_bib_paths: list[str], workspace_root: Path) -> tuple[list[Path], list[dict]]:
    resolved_paths: list[Path] = []
    notes: list[dict] = []
    seen: set[str] = set()

    def add_path(path: Path, source: str, note: str | None = None) -> None:
        normalized = str(path)
        if normalized in seen:
            return
        seen.add(normalized)
        resolved_paths.append(path)
        if note:
            notes.append(
                {
                    "kind": "bibliography_fallback",
                    "source": source,
                    "path": str(path),
                    "message": note,
                }
            )

    fallback_path = SKILL_REFERENCES_DIR / "references.bib"
    fallback_available = fallback_path.exists()

    if raw_bib_paths:
        for raw_path in raw_bib_paths:
            resolved_path = resolve_path(raw_path, workspace_root)
            if resolved_path.exists():
                add_path(resolved_path, "workspace")
                continue

            if fallback_available:
                add_path(
                    fallback_path,
                    "skill-references",
                    f"Bibliography file '{resolved_path}' was not found; using bundled {fallback_path.name} instead.",
                )
                continue

            add_path(resolved_path, "workspace-missing")
        return resolved_paths, notes

    if fallback_available:
        add_path(
            fallback_path,
            "skill-references",
            f"No bibliography file was provided; using bundled {fallback_path.name} as the starter bibliography.",
        )

    return resolved_paths, notes


def maybe_download_csl(csl_path: Path, csl_url: str | None) -> None:
    if csl_path.exists() or not csl_url:
        return
    csl_path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(csl_url, csl_path)


def format_support_file_note(label: str, path: Path | None, source: str | None) -> dict | None:
    if not path or not source:
        return None

    messages = {
        "workspace": f"Using workspace {label}: {path}",
        "skill-references": f"Using bundled {label}: {path}",
        "workspace-missing": f"Workspace {label} was not found: {path}",
    }

    return {
        "kind": f"{label.replace(' ', '_')}_source",
        "path": str(path),
        "source": source,
        "message": messages.get(source, f"Using {label}: {path}"),
    }


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
        elif pandoc_version != crossref_built_with:
            warning = (
                f"Pandoc runtime version {pandoc_version} differs from pandoc-crossref build target "
                f"{crossref_built_with}. The major versions match, but pandoc-crossref may still emit a runtime warning."
            )

    return {
        "pandoc_version": pandoc_version,
        "pandoc_version_output": pandoc_version_output,
        "pandoc_crossref_build_target": crossref_built_with,
        "pandoc_crossref_version_output": crossref_version_output,
        "compatible": compatible,
        "warning": warning,
    }


def detect_python_pandoc_support(pypandoc_module=None, download_api_available: bool | None = None) -> dict:
    support = {
        "available": False,
        "module_name": None,
        "package_versions": [],
        "pandoc_path": None,
        "download_api_available": False,
        "detail": None,
    }

    if pypandoc_module is None:
        try:
            pypandoc_module = importlib.import_module("pypandoc")
        except ModuleNotFoundError as exc:
            support["detail"] = str(exc)
            return support

    support["available"] = True
    support["module_name"] = getattr(pypandoc_module, "__name__", "pypandoc")

    for package_name in ("pypandoc_binary", "pypandoc"):
        try:
            package_version = metadata.version(package_name)
        except metadata.PackageNotFoundError:
            continue
        support["package_versions"].append(f"{package_name}=={package_version}")

    if download_api_available is None:
        try:
            download_module = importlib.import_module("pypandoc.pandoc_download")
        except ModuleNotFoundError:
            download_api_available = False
        else:
            download_api_available = hasattr(download_module, "download_pandoc")
    support["download_api_available"] = bool(download_api_available)

    try:
        support["pandoc_path"] = str(pypandoc_module.get_pandoc_path())
    except Exception as exc:
        support["detail"] = str(exc)

    return support


def install_pandoc_via_pypandoc(
    version: str | None = None,
    pypandoc_module=None,
    download_func=None,
) -> str:
    if pypandoc_module is None:
        try:
            pypandoc_module = importlib.import_module("pypandoc")
        except ModuleNotFoundError as exc:
            raise RuntimeError("pypandoc is not available in the active Python environment.") from exc

    if download_func is None:
        download_module = importlib.import_module("pypandoc.pandoc_download")
        download_func = download_module.download_pandoc

    download_kwargs = {}
    if version:
        download_kwargs["version"] = version
    download_func(**download_kwargs)

    pandoc_path = pypandoc_module.get_pandoc_path()
    if not pandoc_path:
        raise RuntimeError("pypandoc did not report an installed pandoc path after download.")
    return str(pandoc_path)


def classify_python_pandoc_source(python_pandoc_support: dict) -> str:
    package_names = {
        package_version.split("==", 1)[0]
        for package_version in python_pandoc_support.get("package_versions", [])
    }
    if "pypandoc_binary" in package_names:
        return "python-binary"
    if "pypandoc" in package_names:
        return "python-package"
    return "python-env"


def build_toolchain_report(
    pandoc: str | None,
    pandoc_source: str | None,
    pandoc_crossref: str | None,
    pandoc_crossref_source: str | None,
    python_pandoc_support: dict,
) -> dict:
    report = {
        "pandoc": {
            "path": pandoc,
            "source": pandoc_source,
        },
        "pandoc_crossref": {
            "path": pandoc_crossref,
            "source": pandoc_crossref_source,
        },
        "python_pandoc": python_pandoc_support,
    }

    if pandoc and pandoc_crossref:
        report.update(inspect_toolchain(pandoc, pandoc_crossref))
    else:
        report.update(
            {
                "pandoc_version": None,
                "pandoc_version_output": None,
                "pandoc_crossref_build_target": None,
                "pandoc_crossref_version_output": None,
                "compatible": None,
                "warning": None,
            }
        )

    return report


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


def write_report(report: dict, report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(report, report_path)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root).resolve()
    input_files = [resolve_path(path, workspace_root) for path in args.inputs]
    bib_files, bibliography_notes = resolve_bibliography_files(args.bib, workspace_root)
    output_path = resolve_path(args.output, workspace_root)
    csl_path, csl_source = resolve_support_file(args.csl, workspace_root, "sample-author-date.csl")
    crossref_config, crossref_source = resolve_support_file(args.crossref_config, workspace_root, "crossref_config.yaml")
    reference_doc = resolve_path(args.reference_doc, workspace_root) if args.reference_doc else None
    support_notes: list[dict] = []
    support_notes.extend(bibliography_notes)
    csl_note = format_support_file_note("CSL file", csl_path, csl_source)
    if csl_note:
        support_notes.append(csl_note)
    crossref_note = format_support_file_note("crossref config", crossref_config, crossref_source)
    if crossref_note:
        support_notes.append(crossref_note)
    reference_doc_note = format_support_file_note("reference doc", reference_doc, "workspace" if reference_doc and reference_doc.exists() else None)
    if reference_doc_note:
        support_notes.append(reference_doc_note)
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

    equation_mode = determine_equation_mode(args.to, args.equation_mode)
    python_pandoc_support = detect_python_pandoc_support()

    registered_pandoc_paths, registered_crossref_paths = load_registered_toolchain_paths()

    pandoc = resolve_executable_from_preferred_paths(args.pandoc_path, registered_pandoc_paths + DEFAULT_PANDOC_PATHS)
    pandoc_source = "system" if pandoc else None
    pandoc_crossref = resolve_executable_from_preferred_paths(
        args.pandoc_crossref,
        registered_crossref_paths + DEFAULT_PANDOC_CROSSREF_PATHS,
    )
    pandoc_crossref_source = "system" if pandoc_crossref else None

    if not pandoc:
        python_pandoc_path = python_pandoc_support.get("pandoc_path")
        if python_pandoc_path and Path(python_pandoc_path).exists():
            pandoc = python_pandoc_path
            pandoc_source = classify_python_pandoc_source(python_pandoc_support)
        elif args.download_pandoc and python_pandoc_support["available"] and python_pandoc_support["download_api_available"]:
            try:
                pandoc = install_pandoc_via_pypandoc(args.pandoc_version)
                pandoc_source = "python-download"
                python_pandoc_support = detect_python_pandoc_support()
            except Exception as exc:
                report = {
                    "success": False,
                    "stage": "toolchain",
                    "target": args.to,
                    "output": str(output_path),
                    "equation_mode": equation_mode,
                    "toolchain": build_toolchain_report(
                        pandoc,
                        pandoc_source,
                        pandoc_crossref,
                        pandoc_crossref_source,
                        python_pandoc_support,
                    ),
                    "messages": [
                        {
                            "kind": "pandoc_download_failed",
                            "severity": "error",
                            "message": f"Automatic pandoc download via pypandoc failed: {exc}",
                        }
                    ],
                    "reason": str(exc),
                    "preflight": None,
                    "bib_merge": None,
                    "command": None,
                    "stdout": "",
                    "stderr": "",
                    "returncode": 2,
                    "temp_dir": None,
                }
                write_report(report, report_path)
                print(f"Automatic pandoc download via pypandoc failed: {exc}", file=sys.stderr)
                return 2

    toolchain = build_toolchain_report(
        pandoc,
        pandoc_source,
        pandoc_crossref,
        pandoc_crossref_source,
        python_pandoc_support,
    )

    if not pandoc or not pandoc_crossref:
        missing_messages: list[dict] = []
        if not pandoc:
            missing_messages.append(
                {
                    "kind": "missing_pandoc_executable",
                    "severity": "error",
                    "message": "Pandoc executable not found.",
                }
            )
        if not pandoc_crossref:
            missing_messages.append(
                {
                    "kind": "missing_pandoc_crossref_executable",
                    "severity": "error",
                    "message": "pandoc-crossref executable not found.",
                }
            )

        report = {
            "success": False,
            "stage": "toolchain",
            "target": args.to,
            "output": str(output_path),
            "equation_mode": equation_mode,
            "toolchain": toolchain,
            "support_files": support_notes,
            "messages": missing_messages,
            "reason": "One or more required executables are missing.",
            "preflight": None,
            "bib_merge": None,
            "command": None,
            "stdout": "",
            "stderr": "",
            "returncode": 2,
            "temp_dir": None,
        }
        write_report(report, report_path)

        for message in missing_messages:
            print(message["message"], file=sys.stderr)

        if not pandoc:
            available_packages = ", ".join(python_pandoc_support["package_versions"]) or "none"
            if not python_pandoc_support["available"]:
                print(
                    "No pypandoc or pypandoc_binary package was detected in the current Python environment.",
                    file=sys.stderr,
                )
            else:
                print(f"Detected Python pandoc support: {available_packages}", file=sys.stderr)
                if not python_pandoc_support["pandoc_path"] and not args.download_pandoc:
                    print(
                        "Re-run with --download-pandoc to install pandoc into that Python environment, or install pandoc system-wide.",
                        file=sys.stderr,
                    )

        if not pandoc_crossref:
            print(
                "pandoc-crossref is still required as a separate executable for figure, table, equation, and section cross-references.",
                file=sys.stderr,
            )
        return 2

    if toolchain["compatible"] is False:
        report = {
            "success": False,
            "stage": "toolchain",
            "target": args.to,
            "output": str(output_path),
            "equation_mode": equation_mode,
            "toolchain": toolchain,
            "support_files": support_notes,
            "messages": [
                {
                    "kind": "pandoc_toolchain_incompatible",
                    "severity": "error",
                    "message": toolchain["warning"] or "Pandoc and pandoc-crossref versions are incompatible.",
                }
            ],
            "reason": "Pandoc and pandoc-crossref major versions do not match.",
            "preflight": None,
            "bib_merge": None,
            "command": None,
            "stdout": "",
            "stderr": "",
            "returncode": 2,
            "temp_dir": None,
        }
        write_report(report, report_path)
        print(
            toolchain["warning"] or "Pandoc and pandoc-crossref major versions do not match.",
            file=sys.stderr,
        )
        return 2

    for note in support_notes:
        print(note["message"], file=sys.stderr)

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
        write_report(
            {
                "success": False,
                "stage": "preflight",
                "target": args.to,
                "output": str(output_path),
                "equation_mode": equation_mode,
                "toolchain": toolchain,
                "support_files": support_notes,
                "preflight": preflight,
                "messages": [],
            },
            report_path,
        )
        print("Strict mode enabled; conversion stopped because preflight findings were detected.", file=sys.stderr)
        return 1

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
            "support_files": support_notes,
            "command": command,
            "preflight": preflight,
            "bib_merge": bib_merge_report,
            "messages": parsed_messages,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
            "temp_dir": str(keep_temp_dir) if keep_temp_dir else None,
        }
        write_report(report, report_path)

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