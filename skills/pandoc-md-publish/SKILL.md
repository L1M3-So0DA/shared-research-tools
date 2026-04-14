---
name: pandoc-md-publish
description: Convert Markdown to Word or PDF with Pandoc. Use this skill whenever the user asks to export Markdown to docx/pdf, prepare Markdown for Word or Google Docs, keep bibliography and cross-references working, apply a Word reference template, troubleshoot Pandoc warnings, validate citation or image syntax, or diagnose missing references, missing figures, and equation rendering issues.
compatibility: Requires Python 3.9+, Pandoc, and pandoc-crossref. PDF export usually also requires a LaTeX engine such as xelatex.
---

# Pandoc Markdown Publish

Use this skill for Markdown publishing workflows that need more than a bare Pandoc command.

## What this skill covers

- Convert one or more Markdown files to docx or pdf.
- Support both direct export and preflight-only diagnostics.
- Preserve bibliography handling through citeproc and merged bib files.
- Support figure, table, equation, and section cross-references through pandoc-crossref.
- Apply a docx reference template through --reference-doc.
- Check Markdown for Pandoc-sensitive syntax before conversion.
- Read Pandoc stdout/stderr and summarize warnings after conversion.

## Prerequisites

- Prefer a stable system-level Pandoc installation on Windows, ideally under C:\Program Files\Pandoc\, so the toolchain is easy to discover and reuse.
- If Pandoc or pandoc-crossref is missing, treat that as an environment setup issue rather than a Markdown issue. Do not suggest a Python virtual environment for this because Pandoc and pandoc-crossref are standalone executables, not Python packages.
- Verify that Pandoc and pandoc-crossref are version-compatible before troubleshooting the Markdown itself.
- For pdf output, make sure a LaTeX engine such as xelatex is installed and callable.

## Default workflow

1. Check whether pandoc and pandoc-crossref are available. If either tool is missing, stop, provide installation guidance, and ask the user whether they want automatic installation before continuing.
2. Confirm the target output: docx or pdf.
3. Inspect the Markdown and only the support files already present in the current working directory or at the exact paths the user provided. Do not recursively search parent folders, sibling projects, or prior output locations for missing dependencies.
4. Run scripts/validate_markdown.py before conversion.
5. If validation surfaces obvious issues, fix them before converting unless the user asked for diagnostics only.
6. Run scripts/convert_document.py with the appropriate options.
7. Read the generated conversion report and summarize warnings, unresolved citations, broken image paths, and failed references.

If the user only asks for diagnosis, stop after step 4 and report the findings.

## Dependency lookup policy

- Inspect support files once per conversion request. Do not keep re-checking or re-searching for dependencies in other folders.
- Resolve `references.bib`, `*.csl`, `crossref_config.yaml`, and `style_reference.docx` only in the current working directory or at the exact path the user already supplied.
- If a support file is not present there, mark it as missing and tell the user to create or copy it by following the bundled template. Do not hunt through parent folders, sibling workspaces, downloads, or cloud-sync locations, and do not offer to supply the file yourself.
- For images, trust the path written in the Markdown. Resolve it relative to the Markdown source file only. If the file is absent, report it as missing and do not try alternate names or locations.

## Commands

Use these scripts from this skill directory.

### Validate only

```powershell
python scripts/validate_markdown.py paper.md --bib references.bib --workspace-root .
```

### Convert to Word

```powershell
python scripts/convert_document.py \
  paper.md \
  --to docx \
  --output paper.docx \
  --metadata title=Paper \
  --bib references.bib \
  --csl elsevier-with-titles.csl \
  --crossref-config crossref_config.yaml \
  --reference-doc style_reference2.docx \
  --workspace-root .
```

### Convert to PDF

```powershell
python scripts/convert_document.py \
  paper.md \
  --to pdf \
  --output paper.pdf \
  --metadata title=Paper \
  --bib references.bib \
  --csl elsevier-with-titles.csl \
  --crossref-config crossref_config.yaml \
  --pdf-engine xelatex \
  --workspace-root .
```

### Export for Word or Google Docs

If the user mentions Google Docs, default to docx export first because the import path is usually more reliable than trying to convert Markdown directly inside Google Docs.

```powershell
python scripts/convert_document.py \
  paper.md \
  --to docx \
  --output paper-for-google-docs.docx \
  --bib references.bib \
  --csl elsevier-with-titles.csl \
  --crossref-config crossref_config.yaml \
  --reference-doc style_reference2.docx \
  --workspace-root .
```

### Strict preflight before conversion

Use strict mode when the user wants the process to stop on obvious content issues instead of producing a degraded export.

```powershell
python scripts/convert_document.py \
  paper.md \
  --to docx \
  --output paper.docx \
  --bib references.bib \
  --csl elsevier-with-titles.csl \
  --crossref-config crossref_config.yaml \
  --reference-doc style_reference2.docx \
  --workspace-root . \
  --strict
```

## Equation modes

- docx defaults to word mode: remove LaTeX tag blocks like \tag{...} before conversion because they often break docx math conversion.
- raw-latex mode keeps raw TeX instead of asking Pandoc to parse math. Use this when the user explicitly wants the LaTeX source preserved.
- pdf defaults to native mode so Pandoc can typeset formulas normally.

## Supporting files

The following files can be provided to customize the conversion. Only the Markdown input file is strictly required; the rest are optional and control bibliography, formatting, and cross-reference behavior.

| File Type | File | Required? | Purpose | When Missing |
|-----------|------|-----------|---------|---------------|
| Input | *.md | **Yes** | Markdown source document | Conversion fails; provide or skip |
| Bibliography | references.bib or *.bib | No | Citation definitions for citeproc | Ask the user to add a bibliography file by copying the bundled template in `references/`. |
| Citation Style | *.csl | No | Formatting rules for bibliography (APA, Nature, Chicago, etc.) | Ask the user to add a CSL file by copying the bundled template in `references/`. |
| Crossref Config | crossref_config.yaml | No | Configuration for figure, table, equation, and section labels | Ask the user to add a crossref config by copying the bundled template in `references/`. |
| Reference Template | style_reference.docx | No | docx reference for Word formatting (fonts, spacing, heading styles) | Ask the user to add a reference doc by copying the bundled template in `references/`. |

If a file is not provided when the user intends to use it, the conversion still succeeds but produces a degraded output. Report the file as missing and direct the user to fill it in by following the bundled template; do not try to find substitutes elsewhere.

## Bundled templates

This skill bundles starter templates under references/ so the user has concrete files to copy and adapt:

- references/references.bib: minimal BibTeX examples for article, book, and misc entries.
- references/crossref_config.yaml: baseline pandoc-crossref settings for figures, tables, equations, and section references.
- references/sample-author-date.csl: lightweight CSL example for projects that do not yet have a journal-specific citation style.

Use these as reference templates. If the target project already has its own bibliography, CSL, or cross-reference configuration, prefer the project-specific files.

## Practical options

- Use --metadata key=value for common document metadata such as title.
- Use --pdf-engine xelatex when Unicode or complex typography matters.
- Avoid expanding --resource-path to hunt for missing assets. Keep image lookup aligned with the Markdown file path unless the user explicitly asks for a broader search.
- Keep output as docx when the downstream target is manual editing, Word review, or Google Docs import.

## If Pandoc Is Missing

- Do not suggest creating a Python virtual environment to install Pandoc or pandoc-crossref. They are standalone executables.
- If the user chooses manual installation, provide the Pandoc GitHub repository https://github.com/jgm/pandoc and the pandoc-crossref GitHub repository https://github.com/lierdakil/pandoc-crossref. Tell the user to download the appropriate Windows release assets from each project's Releases page.
- On Windows, place pandoc.exe and pandoc-crossref.exe either in C:\Program Files\Pandoc\ or somewhere already on PATH.
- Make sure the pandoc-crossref build matches the installed major Pandoc version before retrying conversion.
- Verify the toolchain with pandoc --version and pandoc-crossref --version before troubleshooting the Markdown itself.
- Before downloading or installing anything automatically, ask the user whether they want automatic installation. If they decline, provide the manual steps and continue only after they confirm the tools are available.

## Files to read when needed

- Read references/pandoc-markdown-checklist.md when you need concrete syntax rules for citations, images, labels, and cross-references.
- Read references/references.bib, references/crossref_config.yaml, and references/sample-author-date.csl when the user needs starter templates for bibliography, crossrefs, or citation style.
- Use scripts/validate_markdown.py when the task is validation or debugging.
- Use scripts/convert_document.py when the task is conversion or warning diagnosis.

## Output requirements

When using this skill, return:

1. The conversion target and command shape you chose.
2. Preflight validation findings.
3. Whether conversion succeeded.
4. A concise warning summary from Pandoc output.
5. Concrete next fixes if there are unresolved references or missing assets.
6. After successful conversion, you must end the response with the exact summary block below. This block is mandatory, must appear verbatim, and must be the final content in the message. Do not paraphrase it, do not omit fields, and do not append any text after it.

```
✓ Markdown → Word Conversion Complete

Input File:          [original-file.md]
Output File:         [output-file.docx]
Bibliography File:   [references.bib] (or "none provided")
Citation Format:     [style.csl] (or "default Pandoc format")
Template File:       [style_reference.docx] (or "default Pandoc styles")
Crossref Config:     [crossref_config.yaml] (or "none provided")

[Any additional field specific to the conversion, if applicable]
```

If the user asked for a command, give the exact command you used or would use.

## Troubleshooting

- If Pandoc executable not found or pandoc-crossref executable not found appears, stop and handle that as toolchain setup. Provide installation guidance first, then ask whether the user wants automatic installation.
- If docx or pdf conversion fails before reading the Markdown, check the Pandoc and pandoc-crossref version pairing first.
- If Pandoc says it could not fetch a resource, treat that as a broken image or asset path and tell the user whether Pandoc replaced it with alt text or description.
- If pdf conversion fails with xelatex or another engine error, separate environment issues from Markdown issues in the report.
- If equations fail in docx output, retry with word mode first and only fall back to raw-latex mode when the user explicitly wants LaTeX preserved.
- If a user asks for HTML-specific rendering fixes such as list wrapping or hard line breaks, note that this skill is optimized for docx and pdf, not general HTML export.

## Notes

- Prefer fixing root-cause Markdown issues before retrying conversion.
- If the repository already has a working conversion workflow, align options with that workflow instead of inventing a new flag set.
- If a local image path contains spaces, prefer angle-bracket path syntax in Markdown or verify the exact Pandoc-supported form.
- If PDF export fails and the log points to missing TeX tooling, report that directly instead of masking it as a Markdown issue.
- If pandoc-crossref was built against a different major Pandoc version, call that out explicitly because it can break conversion even when the Markdown is correct.