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

## Windows Quick Install

When the user allows automation on Windows, follow this order:

1. Ask the user whether to use the default install location (`C:\Program Files\Pandoc`) or a custom location.
2. Run `scripts/install_windows_toolchain.py` with that location. If the target directory is the default Windows location, try `winget` first and then `choco` for Pandoc; otherwise download the release archive and extract it into the chosen directory.
3. Detect the installed Pandoc major version and download a matching pandoc-crossref release.
4. Check the machine for a usable archive tool before extraction. Prefer 7-Zip or Bandizip; if the selected pandoc-crossref asset is `.7z` and no extractor exists, install 7-Zip first.
5. Verify the installed versions after extraction. Pandoc and pandoc-crossref must match on the major version line before conversion starts. The installer also adds the install directory to the user's PATH and writes a small toolchain record so later runs can rediscover the binaries.
6. If `C:\Program Files\Pandoc` is not usable, prompt the user to switch to `%LOCALAPPDATA%\Pandoc` or enter a custom directory, then continue installation in that location.

If the user chooses a custom location, keep both executables together and reuse that exact directory on later runs. The installer records the chosen toolchain in `~/.pandoc-md-publish/windows-toolchain.json` so later conversions can rediscover the pair without guessing. If the files are moved manually, or if you already know the custom directory such as `D:\Pandoc`, pass both executables back into `scripts/convert_document.py` via `--pandoc-path` and `--pandoc-crossref` instead of relying on PATH. That keeps `pandoc` and `pandoc-crossref` paired and avoids mixing a custom install with an older PATH entry.

| Pandoc | pandoc-crossref build target | Status |
| --- | --- | --- |
| 3.x | 3.x | Supported |
| 2.x | 2.x | Legacy only |
| mixed major versions | mixed major versions | Stop and reinstall a matching pair |

## Default workflow

1. Check whether pandoc and pandoc-crossref are available. Prefer explicit user-supplied executable paths first, then any recorded Windows toolchain hint in `~/.pandoc-md-publish/windows-toolchain.json`, then PATH. If pandoc is missing, inspect the active Python environment for pypandoc or pypandoc_binary. If the Python environment already exposes a usable pandoc path, keep going with it; if pypandoc is installed but pandoc is missing, ask the user whether to use the `--download-pandoc` fallback before continuing. If neither path exists, stop, provide installation guidance, and ask the user whether they want automatic installation before continuing. On Windows, the automatic path is `scripts/install_windows_toolchain.py`.
2. Confirm the target output: docx or pdf.
3. Inspect the Markdown and only the support files already present in the current working directory or at the exact paths the user provided. Do not recursively search parent folders, sibling projects, or prior output locations for missing dependencies.
4. Run scripts/validate_markdown.py before conversion.
5. If validation surfaces obvious issues, fix them before converting unless the user asked for diagnostics only.
6. Run scripts/convert_document.py with the appropriate options. For docx + axmath mode, omit `--axmath-template` first so the postprocessor can auto-discover AxMath from common Windows install locations. Only add `--axmath-template` when AxMath is installed in a custom location or auto-discovery fails, and in that case ask the user for the exact `AxMath.dotm` or `AxMath.exe` path instead of hardcoding a machine-specific default into the workflow.
7. Read the generated conversion report and summarize warnings, unresolved citations, broken image paths, and failed references.

If the user only asks for diagnosis, stop after step 4 and report the findings.

## Dependency lookup policy

- Inspect support files once per conversion request. Do not keep re-checking or re-searching for dependencies in other folders.
- When a custom install is recorded, prefer that paired toolchain over unrelated PATH entries so the converter does not mix executables from different installs.
- Resolve `references.bib`, `*.csl`, and `crossref_config.yaml` in the current working directory or at the exact path the user already supplied first, then fall back to the bundled templates under this skill's `references/` folder when the workspace copy is missing.
- If a workspace copy is missing and a bundled template is used, keep going but record the fallback so the user can override it later if needed.
- Resolve `style_reference.docx` only in the current working directory or at the exact path the user already supplied. If no Word reference template is provided or found, continue without `--reference-doc` so Pandoc uses its built-in default Word styles, and record that no reference template was used.
- Resolve `--axmath-template` only when `--equation-mode axmath` is selected. Prefer an explicit user-supplied `AxMath.dotm` or `AxMath.exe` path first; if it is omitted, let the AxMath postprocessor search common Windows install locations automatically. If no candidate is found, stop and ask the user for the exact path instead of baking a workstation-specific location into the command example.
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

### Convert to Word with all formulas as AxMath objects

This mode requires Windows, Microsoft Word, and AxMath. It first creates a raw-LaTeX DOCX, then opens Word and converts only the body paragraph ranges that contain TeX formulas. Heading paragraphs are excluded from the AxMath selection so heading font sizes do not affect formula object sizes. This is the only AxMath conversion route: it does not select the whole document, apply AxMath's default equation format, or run proportional object-size fixups after conversion. Run it from a logged-in desktop session and use `--axmath-visible` only when diagnosis needs a visible Word window.

```powershell
python scripts/convert_document.py `
  paper.md `
  --to docx `
  --output paper-axmath.docx `
  --equation-mode axmath `
  --workspace-root .
```

By default, do not pass `--axmath-template`. The AxMath postprocessor will auto-discover `AxMath.dotm` from common Windows install locations. If auto-discovery fails or AxMath is installed in a custom location, ask the user for the exact `AxMath.dotm` or `AxMath.exe` path and rerun with `--axmath-template`.

If AxMath is installed in a custom location and the user already knows the path, pass it explicitly:

```powershell
python scripts/convert_document.py `
  paper.md `
  --to docx `
  --output paper-axmath.docx `
  --equation-mode axmath `
  --axmath-template "C:\path\to\AxMath.dotm" `
  --workspace-root .
```

If the user explicitly wants pandoc-crossref numbered display equations converted from DOCX tables into tabbed Word paragraphs with `SEQ Equation` field-code numbers, add `--axmath-field-code-equation-numbers`. Do not enable this by default. If the source Markdown has no equation labels such as `{#eq:...}` or no equation references, leave the option off.

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

### Python-side pandoc fallback

If the user already has pypandoc or pypandoc_binary in the active Python environment, pandoc can be installed or discovered from that environment without requiring a separate system-wide pandoc package.

```powershell
python scripts/convert_document.py \
  paper.md \
  --to docx \
  --output paper.docx \
  --download-pandoc \
  --workspace-root .
```

## Equation modes

- docx defaults to word mode: remove LaTeX tag blocks like \tag{...} before conversion because they often break docx math conversion.
- raw-latex mode keeps raw TeX instead of asking Pandoc to parse math. Use this when the user explicitly wants the LaTeX source preserved.
- axmath mode is available for docx output only. It first creates a temporary DOCX with delimited TeX, then runs AxMath's `AMSTeX2AM` conversion in Word over formula-containing body paragraph ranges while skipping headings. This avoids AxMath sizing formulas from title or heading styles when a document contains mixed-size headings and body text. It verifies that the formulas became AxMath OLE objects and that no delimited TeX remains. After AxMath conversion, it removes italic formatting that AxMath can leak into immediately following CJK text runs and records the cleaned run count in the conversion report. If `--axmath-template` is omitted, the postprocessor auto-discovers `AxMath.dotm` from common Windows install locations; if discovery fails, ask the user for the exact template or executable path and rerun with `--axmath-template`. If `--axmath-field-code-equation-numbers` is explicitly supplied, pandoc-crossref numbered equation tables are converted into tabbed Word paragraphs with `SEQ Equation` field-code numbers; otherwise this structural rewrite is skipped. Failed conversions, or runs with `--keep-temp`, preserve a raw-LaTeX diagnostic DOCX.
- pdf defaults to native mode so Pandoc can typeset formulas normally.

## Supporting files

The following files can be provided to customize the conversion. Only the Markdown input file is strictly required; the rest are optional and control bibliography, formatting, and cross-reference behavior.

| File Type | File | Required? | Purpose | When Missing |
|-----------|------|-----------|---------|---------------|
| Input | *.md | **Yes** | Markdown source document | Conversion fails; provide or skip |
| Bibliography | references.bib or *.bib | No | Citation definitions for citeproc | Ask the user to add a bibliography file by copying the bundled template in `references/`. |
| Citation Style | *.csl | No | Formatting rules for bibliography (APA, Nature, Chicago, etc.) | Ask the user to add a CSL file by copying the bundled template in `references/`. |
| Crossref Config | crossref_config.yaml | No | Configuration for figure, table, equation, and section labels | Ask the user to add a crossref config by copying the bundled template in `references/`. |
| Reference Template | style_reference.docx | No | docx reference for Word formatting (fonts, spacing, heading styles) | Continue with Pandoc's built-in default Word styles and report that no reference template was provided. |

If bibliography, CSL, or crossref configuration is not provided when the user intends to use it, the conversion still succeeds but produces a degraded output. Report the missing file and direct the user to the bundled templates under `references/`; do not try to find substitutes elsewhere. If no Word reference template is provided, do not treat it as a failure: let Pandoc use its built-in default Word styles and tell the user that the output did not use a custom reference docx.

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
- pypandoc and pypandoc_binary can help with pandoc only. pandoc-crossref still needs to be installed separately because it is the filter that resolves figure, table, equation, and section references.
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
6. After successful conversion, include the exact summary block below. This block is mandatory and must appear verbatim. Do not paraphrase it and do not omit fields.
7. If any bibliography, CSL, or crossref file was missing and a bundled template from `references/` was used instead, append a short note immediately after the block that names each missing file, names the bundled file used in its place, and tells the user they can copy and adapt the example files under `references/` to provide their own version.
8. If no reference-doc was provided or found, append a short note immediately after the block that says Pandoc's built-in default Word styles were used because no custom Word reference template was provided.

```
Markdown to Word Conversion Complete

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

- If Pandoc executable not found or pandoc-crossref executable not found appears, stop and handle that as toolchain setup. Provide installation guidance first, then ask whether the user wants automatic installation through `scripts/install_windows_toolchain.py`.
- If docx or pdf conversion fails before reading the Markdown, check the Pandoc and pandoc-crossref version pairing first.
- If Pandoc says it could not fetch a resource, treat that as a broken image or asset path and tell the user whether Pandoc replaced it with alt text or description.
- If pdf conversion fails with xelatex or another engine error, separate environment issues from Markdown issues in the report.
- If equations fail in docx output, retry with word mode first and only fall back to raw-latex mode when the user explicitly wants LaTeX preserved.
- If `AxMath template not found` appears, do not hardcode a repo-wide path. First retry without `--axmath-template` so the postprocessor can search common install locations. If it still fails, ask the user for the exact `AxMath.dotm` or `AxMath.exe` path and pass it explicitly.
- If AxMath mode cannot start Word COM or waits during macro execution in a noninteractive runner, rerun it in the logged-in Windows desktop session with `--axmath-visible` and inspect the `.axmath.log`. A successful segmented run should include `Segmented body conversion ranges`, `Segmented body AMSTeX2AM conversion finished`, and `residual_tex=0`.
- If a user asks for HTML-specific rendering fixes such as list wrapping or hard line breaks, note that this skill is optimized for docx and pdf, not general HTML export.

## Notes

- Prefer fixing root-cause Markdown issues before retrying conversion.
- If the repository already has a working conversion workflow, align options with that workflow instead of inventing a new flag set.
- If a local image path contains spaces, prefer angle-bracket path syntax in Markdown or verify the exact Pandoc-supported form.
- If PDF export fails and the log points to missing TeX tooling, report that directly instead of masking it as a Markdown issue.
- If pandoc-crossref was built against a different major Pandoc version, call that out explicitly because it can break conversion even when the Markdown is correct.
