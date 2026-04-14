from __future__ import annotations

import json
import re
from pathlib import Path


CROSSREF_PREFIXES = {"fig", "tbl", "eq", "sec"}
ENTRY_PATTERN = re.compile(r"^(@\w+\{)\s*([^,]+)\s*,", re.MULTILINE)
ENTRY_SPLIT_PATTERN = re.compile(r"(?=^@\w+\{)", re.MULTILINE)
IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
INLINE_REFERENCE_PATTERN = re.compile(r"(?<![\w@])@([A-Za-z0-9][A-Za-z0-9:._/\-]*)")
LABEL_PATTERN = re.compile(r"\{#([A-Za-z0-9][A-Za-z0-9:._/\-]*)\}")


def normalize_cite_key(key: str) -> str:
    normalized = key.strip().rstrip(".")
    return normalized.replace("`", "")


def read_text(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8")


def parse_bibliography_keys(bib_files: list[Path]) -> set[str]:
    keys: set[str] = set()

    for bib_file in bib_files:
        if not bib_file.exists():
            continue

        bib_text = read_text(bib_file)
        for entry in ENTRY_SPLIT_PATTERN.split(bib_text):
            if not entry.strip():
                continue

            match = ENTRY_PATTERN.search(entry)
            if match:
                keys.add(normalize_cite_key(match.group(2)))

    return keys


def merge_bibliography_files(bib_files: list[Path], output_path: Path) -> dict:
    merged_entries: list[str] = []
    seen_keys: set[str] = set()
    duplicate_keys: list[str] = []
    missing_files: list[str] = []

    for bib_file in bib_files:
        if not bib_file.exists():
            missing_files.append(str(bib_file))
            continue

        bib_text = read_text(bib_file)
        for entry in ENTRY_SPLIT_PATTERN.split(bib_text):
            if not entry.strip():
                continue

            match = ENTRY_PATTERN.search(entry)
            if not match:
                continue

            raw_key = match.group(2)
            normalized_key = normalize_cite_key(raw_key)

            if normalized_key in seen_keys:
                duplicate_keys.append(normalized_key)
                continue

            normalized_entry = ENTRY_PATTERN.sub(rf"\1{normalized_key},", entry, count=1)
            merged_entries.append(normalized_entry.strip())
            seen_keys.add(normalized_key)

    output_path.write_text("\n\n".join(merged_entries) + ("\n" if merged_entries else ""), encoding="utf-8")

    return {
        "output": str(output_path),
        "entry_count": len(merged_entries),
        "duplicate_keys": sorted(set(duplicate_keys)),
        "missing_files": missing_files,
    }


def resolve_path(candidate: str, base_dir: Path) -> Path:
    path = Path(candidate)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def split_image_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        closing = target.find(">")
        return target[1:closing].strip()

    parts = target.split()
    return parts[0].strip() if parts else target


def is_external_resource(target: str) -> bool:
    lowered = target.lower()
    return lowered.startswith(("http://", "https://", "data:"))


def collect_file_insights(markdown_path: Path, workspace_root: Path) -> dict:
    content = read_text(markdown_path)
    citations: set[str] = set()
    crossrefs: set[str] = set()
    labels = set(LABEL_PATTERN.findall(content))
    missing_images: list[dict] = []
    external_images: list[str] = []

    for match in INLINE_REFERENCE_PATTERN.finditer(content):
        token = normalize_cite_key(match.group(1))
        prefix = token.split(":", 1)[0] if ":" in token else ""
        if prefix in CROSSREF_PREFIXES:
            crossrefs.add(token)
        else:
            citations.add(token)

    for match in IMAGE_PATTERN.finditer(content):
        raw_target = match.group(1)
        target = split_image_target(raw_target)

        if not target:
            continue

        if is_external_resource(target):
            external_images.append(target)
            continue

        resolved = resolve_path(target, markdown_path.parent)
        if not resolved.exists():
            missing_images.append(
                {
                    "source": str(markdown_path.relative_to(workspace_root)),
                    "target": target,
                    "resolved": str(resolved),
                }
            )

    return {
        "file": str(markdown_path.relative_to(workspace_root)),
        "citations": sorted(citations),
        "crossrefs": sorted(crossrefs),
        "labels": sorted(labels),
        "missing_images": missing_images,
        "external_images": sorted(set(external_images)),
    }


def analyze_markdown_files(input_files: list[Path], bib_files: list[Path], workspace_root: Path) -> dict:
    file_reports = [collect_file_insights(path, workspace_root) for path in input_files]
    known_bib_keys = parse_bibliography_keys(bib_files)
    missing_bib_files = [str(path.relative_to(workspace_root)) for path in bib_files if not path.exists()]
    all_labels = {label for report in file_reports for label in report["labels"]}
    all_citations = {cite for report in file_reports for cite in report["citations"]}
    all_crossrefs = {ref for report in file_reports for ref in report["crossrefs"]}

    missing_citations = sorted(all_citations - known_bib_keys)
    unresolved_crossrefs = sorted(all_crossrefs - all_labels)
    missing_images = [image for report in file_reports for image in report["missing_images"]]

    findings: list[dict] = []
    for bib_file in missing_bib_files:
        findings.append(
            {
                "kind": "missing_bibliography_file",
                "severity": "warning",
                "message": f"Bibliography file '{bib_file}' does not exist.",
            }
        )

    for key in missing_citations:
        findings.append(
            {
                "kind": "missing_bibliography_entry",
                "severity": "warning",
                "message": f"Citation key '{key}' was referenced in Markdown but not found in bibliography files.",
            }
        )

    for label in unresolved_crossrefs:
        findings.append(
            {
                "kind": "unresolved_crossref",
                "severity": "warning",
                "message": f"Cross-reference '{label}' was used but no matching label was found in the Markdown inputs.",
            }
        )

    for image in missing_images:
        findings.append(
            {
                "kind": "missing_image",
                "severity": "warning",
                "message": f"Image '{image['target']}' referenced from {image['source']} does not exist at {image['resolved']}.",
            }
        )

    return {
        "workspace_root": str(workspace_root),
        "input_files": [str(path.relative_to(workspace_root)) for path in input_files],
        "bibliography_files": [str(path.relative_to(workspace_root)) for path in bib_files if path.exists()],
        "missing_bibliography_files": missing_bib_files,
        "file_reports": file_reports,
        "summary": {
            "input_count": len(input_files),
            "citation_count": len(all_citations),
            "crossref_count": len(all_crossrefs),
            "label_count": len(all_labels),
            "missing_bibliography_file_count": len(missing_bib_files),
            "missing_citation_count": len(missing_citations),
            "unresolved_crossref_count": len(unresolved_crossrefs),
            "missing_image_count": len(missing_images),
        },
        "findings": findings,
    }


def parse_pandoc_messages(stdout_text: str, stderr_text: str) -> list[dict]:
    messages: list[dict] = []
    combined = []
    if stdout_text.strip():
        combined.extend(stdout_text.splitlines())
    if stderr_text.strip():
        combined.extend(stderr_text.splitlines())

    for raw_line in combined:
        line = raw_line.strip()
        if not line:
            continue

        lowered = line.lower()
        kind = "info"
        severity = "info"

        if "warning" in lowered:
            kind = "pandoc_warning"
            severity = "warning"
        if "error" in lowered:
            kind = "pandoc_error"
            severity = "error"
        if lowered.startswith("unknown extension:") or lowered.startswith("unknown reader:"):
            kind = "pandoc_error"
            severity = "error"
        if "incompatible api versions" in lowered or "filter returned error status" in lowered:
            kind = "pandoc_error"
            severity = "error"
        if "could not find image" in lowered or "image not found" in lowered:
            kind = "missing_image"
            severity = "warning"
        if "citation" in lowered and "not found" in lowered:
            kind = "missing_bibliography_entry"
            severity = "warning"
        if "reference" in lowered and "not found" in lowered:
            kind = "unresolved_crossref"
            severity = "warning"

        messages.append(
            {
                "kind": kind,
                "severity": severity,
                "message": line,
            }
        )

    return messages


def print_report(report: dict) -> None:
    summary = report["summary"]
    print(
        "Preflight summary: "
        f"files={summary['input_count']}, "
        f"citations={summary['citation_count']}, "
        f"crossrefs={summary['crossref_count']}, "
        f"labels={summary['label_count']}, "
        f"missing_bib_files={summary['missing_bibliography_file_count']}, "
        f"missing_citations={summary['missing_citation_count']}, "
        f"unresolved_crossrefs={summary['unresolved_crossref_count']}, "
        f"missing_images={summary['missing_image_count']}"
    )

    if not report["findings"]:
        print("No preflight issues detected.")
        return

    print("Findings:")
    for finding in report["findings"]:
        print(f"- [{finding['severity']}] {finding['message']}")


def write_json(data: dict, output_path: Path) -> None:
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")