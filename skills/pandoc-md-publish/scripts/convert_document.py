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
import zipfile
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
        choices=["word", "raw-latex", "native", "axmath"],
        help="Equation handling mode. docx defaults to 'word'; 'axmath' converts all DOCX equations through AxMath.",
    )
    parser.add_argument(
        "--axmath-template",
        help=(
            "Optional path to AxMath.dotm or AxMath.exe used when --equation-mode axmath is selected. "
            "When omitted, the AxMath postprocessor searches common Windows install locations automatically."
        ),
    )
    parser.add_argument("--axmath-log", help="Path for the AxMath post-processing log.")
    parser.add_argument(
        "--axmath-visible",
        action="store_true",
        help="Show Word while AxMath post-processing runs. Useful when the add-in requires an interactive desktop session.",
    )
    parser.add_argument(
        "--axmath-field-code-equation-numbers",
        action="store_true",
        help=(
            "After AxMath conversion, convert pandoc-crossref numbered equation tables into "
            "tabbed Word paragraphs with SEQ Equation field-code numbers. Off by default."
        ),
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


def validate_equation_mode_for_target(target: str, equation_mode: str) -> None:
    if equation_mode == "axmath" and target != "docx":
        raise ValueError("The axmath equation mode is only supported for docx output.")


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
    return "markdown"


def build_math_to_raw_tex_filter_args(equation_mode: str) -> list[str]:
    if equation_mode not in {"raw-latex", "axmath"}:
        return []
    return ["--lua-filter", str(CURRENT_DIR / "math_to_raw_tex.lua")]


def should_convert_axmath_equation_numbers_to_fields(equation_mode: str, requested: bool) -> bool:
    return equation_mode == "axmath" and requested


def build_axmath_postprocess_command(
    script_path: Path,
    input_docx: Path,
    output_docx: Path,
    log_path: Path,
    template_path: Path | None,
    visible: bool = False,
) -> list[str]:
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-InputDocx",
        str(input_docx),
        "-OutputDocx",
        str(output_docx),
        "-LogPath",
        str(log_path),
        "-Force",
    ]
    if template_path:
        command.extend(["-TemplatePath", str(template_path)])
    if visible:
        command.append("-Visible")
    return command


def run_axmath_postprocessor(command: list[str]) -> dict:
    result = subprocess.run(command, capture_output=True, text=True)
    return {
        "success": result.returncode == 0,
        "command": command,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }


def cleanup_axmath_cjk_italic_leaks(docx_path: Path) -> int:
    """Remove italic formatting that AxMath can leak into following CJK text runs."""
    word_document = "word/document.xml"
    paragraph_pattern = re.compile(r"<w:p(?:\s[^>]*)?>.*?</w:p>", re.DOTALL)
    run_pattern = re.compile(r"<w:r(?:\s[^>]*)?>.*?</w:r>", re.DOTALL)
    text_pattern = re.compile(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", re.DOTALL)
    italic_pattern = re.compile(r"<w:i(?:\s[^>]*)?/>|<w:iCs(?:\s[^>]*)?/>")

    def has_axmath_object(run_xml: str) -> bool:
        return "ProgID=\"Equation.AxMath\"" in run_xml or "ProgID='Equation.AxMath'" in run_xml

    def run_text(run_xml: str) -> str:
        return "".join(match.group(1) for match in text_pattern.finditer(run_xml))

    def has_cjk(text: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in text)

    def remove_italic(run_xml: str) -> tuple[str, bool]:
        updated = italic_pattern.sub("", run_xml)
        updated = re.sub(r"<w:rPr>\s*</w:rPr>", "", updated)
        return updated, updated != run_xml

    def clean_paragraph(paragraph_xml: str) -> tuple[str, int]:
        pieces: list[str] = []
        cursor = 0
        cleaned = 0
        after_axmath_object = False

        for match in run_pattern.finditer(paragraph_xml):
            pieces.append(paragraph_xml[cursor : match.start()])
            run_xml = match.group(0)

            if has_axmath_object(run_xml):
                pieces.append(run_xml)
                after_axmath_object = True
                cursor = match.end()
                continue

            text = run_text(run_xml)
            if not text.strip():
                pieces.append(run_xml)
                cursor = match.end()
                continue

            if after_axmath_object and has_cjk(text):
                updated_run, changed = remove_italic(run_xml)
                pieces.append(updated_run)
                if changed:
                    cleaned += 1
                after_axmath_object = False
                cursor = match.end()
                continue

            pieces.append(run_xml)
            after_axmath_object = False
            cursor = match.end()

        pieces.append(paragraph_xml[cursor:])
        return "".join(pieces), cleaned

    with zipfile.ZipFile(docx_path, "r") as source_archive:
        try:
            document_xml = source_archive.read(word_document)
        except KeyError:
            return 0
        archive_entries = {entry.filename: source_archive.read(entry.filename) for entry in source_archive.infolist()}

    cleaned_count = 0
    document_text = document_xml.decode("utf-8")

    pieces: list[str] = []
    cursor = 0
    for match in paragraph_pattern.finditer(document_text):
        pieces.append(document_text[cursor : match.start()])
        updated_paragraph, paragraph_cleaned = clean_paragraph(match.group(0))
        pieces.append(updated_paragraph)
        cleaned_count += paragraph_cleaned
        cursor = match.end()
    pieces.append(document_text[cursor:])

    if cleaned_count == 0:
        return 0

    archive_entries[word_document] = "".join(pieces).encode("utf-8")
    temp_zip_path = docx_path.with_name(docx_path.name + ".tmp")
    with zipfile.ZipFile(temp_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as target_archive:
        for filename, content in archive_entries.items():
            target_archive.writestr(filename, content)
    shutil.move(str(temp_zip_path), str(docx_path))
    return cleaned_count


def convert_numbered_equation_tables_to_field_paragraphs(docx_path: Path) -> int:
    """Convert numbered display-equation tables to tabbed paragraphs with SEQ fields."""
    word_document = "word/document.xml"
    table_pattern = re.compile(r"<w:tbl(?:\s[^>]*)?>.*?</w:tbl>", re.DOTALL)
    grid_pattern = re.compile(r"<w:tblGrid>.*?</w:tblGrid>", re.DOTALL)
    grid_col_pattern = re.compile(r'<w:gridCol\s+w:w="(\d+)"\s*/>')
    cell_pattern = re.compile(r"<w:tc(?:\s[^>]*)?>.*?</w:tc>", re.DOTALL)
    paragraph_pattern = re.compile(r"<w:p(?:\s[^>]*)?>.*?</w:p>", re.DOTALL)
    paragraph_properties_pattern = re.compile(r"<w:pPr(?:\s[^>]*)?>.*?</w:pPr>", re.DOTALL)
    run_pattern = re.compile(r"<w:r(?:\s[^>]*)?>.*?</w:r>", re.DOTALL)
    number_text_pattern = re.compile(r"<w:t(?:\s[^>]*)?>\(?(\d+(?:\.\d+)*)\)\.?</w:t>")
    bookmark_start_pattern = re.compile(r'<w:bookmarkStart\b[^>]*/>')
    bookmark_end_pattern = re.compile(r'<w:bookmarkEnd\b[^>]*/>')

    def has_axmath(cell_xml: str) -> bool:
        return "ProgID=\"Equation.AxMath\"" in cell_xml or "ProgID='Equation.AxMath'" in cell_xml

    def plain_number(cell_xml: str) -> str | None:
        if has_axmath(cell_xml):
            return None
        match = number_text_pattern.search(cell_xml)
        return match.group(1) if match else None

    def first_paragraph(cell_xml: str) -> str | None:
        match = paragraph_pattern.search(cell_xml)
        return match.group(0) if match else None

    def formula_runs(paragraph_xml: str) -> str:
        runs = [run.group(0) for run in run_pattern.finditer(paragraph_xml)]
        return "".join(run_xml for run_xml in runs if "Equation.AxMath" in run_xml)

    def bookmarks(table_xml: str) -> tuple[str, str]:
        starts = "".join(match.group(0) for match in bookmark_start_pattern.finditer(table_xml))
        ends = "".join(match.group(0) for match in bookmark_end_pattern.finditer(table_xml))
        return starts, ends

    def paragraph_style(paragraph_xml: str) -> str:
        match = paragraph_properties_pattern.search(paragraph_xml)
        if not match:
            return ""
        style_match = re.search(r'<w:pStyle\s+w:val="([^"]+)"\s*/>', match.group(0))
        if not style_match:
            return ""
        return f'<w:pStyle w:val="{style_match.group(1)}"/>'

    def field_number_run(number: str) -> str:
        # The cached display text keeps the exported DOCX readable before Word updates fields.
        return (
            '<w:fldSimple w:instr=" SEQ Equation \\* ARABIC \\# &quot;(0)&quot; ">'
            f'<w:r><w:t>({number})</w:t></w:r>'
            '</w:fldSimple>'
        )

    def convert_table(table_xml: str) -> tuple[str, bool]:
        cells = cell_pattern.findall(table_xml)
        number = plain_number(cells[1]) if len(cells) == 2 else None
        if len(cells) != 2 or not has_axmath(cells[0]) or not number:
            return table_xml, False

        grid = grid_pattern.search(table_xml)
        if not grid:
            return table_xml, False
        widths = [int(match.group(1)) for match in grid_col_pattern.finditer(grid.group(0))]
        if len(widths) != 2:
            return table_xml, False

        total_width = sum(widths)
        if total_width <= 0:
            return table_xml, False

        paragraph_xml = first_paragraph(cells[0])
        if not paragraph_xml:
            return table_xml, False
        runs = formula_runs(paragraph_xml)
        if not runs:
            return table_xml, False

        bookmark_starts, bookmark_ends = bookmarks(table_xml)
        center_tab = total_width // 2
        style = paragraph_style(paragraph_xml)
        converted = (
            f"{bookmark_starts}"
            '<w:p><w:pPr>'
            f"{style}"
            '<w:tabs>'
            f'<w:tab w:val="center" w:pos="{center_tab}"/>'
            f'<w:tab w:val="right" w:pos="{total_width}"/>'
            '</w:tabs>'
            '<w:jc w:val="left"/>'
            '</w:pPr>'
            '<w:r><w:tab/></w:r>'
            f"{runs}"
            '<w:r><w:tab/></w:r>'
            f"{field_number_run(number)}"
            '</w:p>'
            f"{bookmark_ends}"
        )
        return converted, True

    with zipfile.ZipFile(docx_path, "r") as source_archive:
        try:
            document_xml = source_archive.read(word_document)
        except KeyError:
            return 0
        archive_entries = {entry.filename: source_archive.read(entry.filename) for entry in source_archive.infolist()}

    document_text = document_xml.decode("utf-8")
    balanced_count = 0
    pieces: list[str] = []
    cursor = 0
    for match in table_pattern.finditer(document_text):
        pieces.append(document_text[cursor : match.start()])
        balanced_table, changed = convert_table(match.group(0))
        pieces.append(balanced_table)
        if changed:
            balanced_count += 1
        cursor = match.end()
    pieces.append(document_text[cursor:])

    if balanced_count == 0:
        return 0

    archive_entries[word_document] = "".join(pieces).encode("utf-8")
    temp_zip_path = docx_path.with_name(docx_path.name + ".tmp")
    with zipfile.ZipFile(temp_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as target_archive:
        for filename, content in archive_entries.items():
            target_archive.writestr(filename, content)
    shutil.move(str(temp_zip_path), str(docx_path))
    return balanced_count


def combine_axmath_stage_success(pandoc_returncode: int, postprocess: dict | None) -> bool:
    if pandoc_returncode != 0:
        return False
    return bool(postprocess and postprocess.get("success"))


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
    try:
        validate_equation_mode_for_target(args.to, equation_mode)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
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
        print(
            toolchain["warning"] or "Pandoc and pandoc-crossref major versions do not match.",
            file=sys.stderr,
        )

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
    axmath_postprocess = None
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

        pandoc_output_path = temp_dir / (output_path.stem + ".raw-latex.docx") if equation_mode == "axmath" else output_path
        command = [pandoc, str(merged_markdown), "-f", input_format, "-o", str(pandoc_output_path)]
        command.extend(["--filter", pandoc_crossref])
        command.extend(build_math_to_raw_tex_filter_args(equation_mode))

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

        if equation_mode == "axmath" and result.returncode == 0:
            axmath_log_path = (
                resolve_path(args.axmath_log, workspace_root)
                if args.axmath_log
                else output_path.with_name(output_path.name + ".axmath.log")
            )
            axmath_template_path = resolve_path(args.axmath_template, workspace_root) if args.axmath_template else None
            postprocess_command = build_axmath_postprocess_command(
                script_path=CURRENT_DIR / "postprocess_axmath.ps1",
                input_docx=pandoc_output_path,
                output_docx=output_path,
                log_path=axmath_log_path,
                template_path=axmath_template_path,
                visible=args.axmath_visible,
            )
            axmath_postprocess = run_axmath_postprocessor(postprocess_command)
            axmath_postprocess["raw_latex_docx"] = str(pandoc_output_path)
            axmath_postprocess["log_path"] = str(axmath_log_path)
            if axmath_postprocess["success"]:
                axmath_postprocess["cjk_italic_leak_cleaned_runs"] = cleanup_axmath_cjk_italic_leaks(output_path)
                convert_equation_numbers_to_fields = should_convert_axmath_equation_numbers_to_fields(
                    equation_mode,
                    args.axmath_field_code_equation_numbers,
                )
                axmath_postprocess["field_code_equation_numbers_requested"] = convert_equation_numbers_to_fields
                axmath_postprocess["field_code_equation_number_paragraphs"] = (
                    convert_numbered_equation_tables_to_field_paragraphs(output_path)
                    if convert_equation_numbers_to_fields
                    else 0
                )

        if equation_mode == "axmath" and (
            args.keep_temp or result.returncode != 0 or not axmath_postprocess or not axmath_postprocess["success"]
        ):
            if pandoc_output_path.exists():
                diagnostic_raw_docx = output_path.with_name(output_path.stem + ".raw-latex.docx")
                shutil.copy2(pandoc_output_path, diagnostic_raw_docx)
                if axmath_postprocess is not None:
                    axmath_postprocess["raw_latex_docx"] = str(diagnostic_raw_docx)

        conversion_success = (
            combine_axmath_stage_success(result.returncode, axmath_postprocess)
            if equation_mode == "axmath"
            else result.returncode == 0
        )
        final_returncode = (
            axmath_postprocess["returncode"]
            if equation_mode == "axmath" and result.returncode == 0 and axmath_postprocess is not None
            else result.returncode
        )
        report = {
            "success": conversion_success,
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
            "returncode": final_returncode,
            "temp_dir": str(keep_temp_dir) if keep_temp_dir else None,
            "axmath_postprocess": axmath_postprocess,
        }
        write_report(report, report_path)

        if result.stdout.strip():
            print(result.stdout.strip())
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        if axmath_postprocess and axmath_postprocess["stdout"].strip():
            print(axmath_postprocess["stdout"].strip())
        if axmath_postprocess and axmath_postprocess["stderr"].strip():
            print(axmath_postprocess["stderr"].strip(), file=sys.stderr)

        warning_count = len([message for message in parsed_messages if message["severity"] == "warning"])
        error_count = len([message for message in parsed_messages if message["severity"] == "error"])
        if conversion_success:
            print(f"Conversion succeeded: {output_path}")
        else:
            print(f"Conversion failed with return code {final_returncode}.", file=sys.stderr)
        print(f"Pandoc message summary: warnings={warning_count}, errors={error_count}")
        print(f"Structured report written to: {report_path}")

        return final_returncode


if __name__ == "__main__":
    raise SystemExit(main())
