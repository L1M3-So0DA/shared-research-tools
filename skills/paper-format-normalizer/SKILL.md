---
name: paper-format-normalizer
description: Normalize academic manuscript Markdown or mixed Markdown/LaTeX into Pandoc-compatible Markdown before Word or PDF publishing. Use this skill whenever the user asks to unify paper formatting, convert citations, figures, tables, equations, or section references into Pandoc or pandoc-crossref syntax, clean LaTeX-heavy Markdown for Word export, prepare a manuscript for pandoc-md-publish, or debug broken references, even if they only mention [1] citations, Figure 1, Eq. (3), image paths, or Word export problems.
compatibility: Designed to run before pandoc-md-publish. The skill can work from prompt instructions alone; optional deterministic rewrites may use Python 3.9+ scripts if you add them later.
---

# Paper Format Normalizer

Use this skill to rewrite or diagnose manuscript Markdown before publishing with Pandoc.

## What this skill does

- Normalize citations into Pandoc citation syntax.
- Normalize figure, table, equation, and section labels into pandoc-crossref syntax.
- Rewrite Markdown/LaTeX hybrids into Word-friendlier Pandoc Markdown.
- Preserve safe transformations and explicitly report ambiguous cases instead of guessing.
- Prepare the manuscript for pandoc-md-publish.

## When to use a different skill

- If the input is DOCX, PDF, PPTX, or another office document, use third_party/doc-to-markdown first.
- If the Markdown is already valid and the user wants final export, use pandoc-md-publish.
- If the main issue is missing Pandoc, pandoc-crossref, or a LaTeX engine, use pandoc-md-publish troubleshooting instead.

## Working modes

- Rewrite mode: modify the manuscript into cleaner Pandoc-friendly Markdown.
- Diagnostics-only mode: inspect and report unsafe or unresolved patterns without rewriting.

If the user says "just check", "diagnose", "don't modify", or "preflight only", use diagnostics-only mode.

## Target syntax

Prefer these normalized forms:

- Citations: [@smith2024] or [see @smith2024, pp. 3-5]
- Figure block: ![Overall workflow](images/workflow.png){#fig:workflow}
- Figure reference: @fig:workflow
- Table caption: Table: Benchmark results. {#tbl:benchmark}
- Table reference: @tbl:benchmark
- Display equation:

  $$
  E = mc^2
  $$ {#eq:energy}

- Equation reference: @eq:energy
- Section heading: ## Method {#sec:method}
- Section reference: @sec:method

## Default workflow

1. Identify the source style.
   - Already-close Pandoc Markdown
   - LaTeX-heavy Markdown
   - Journal-template Markdown
   - Word-exported Markdown
   - Mixed Chinese/English academic Markdown
2. Check local support files before rewriting.
   - Inspect the current working directory once for matching `.bib` files.
   - If no `.bib` file is present in the current working directory, do not pretend that citation-key mapping is available.
   - Derive the original image directory from the image paths or HTML `src` values in the source and verify that directory exists before rewriting image blocks.
   - If the original image directory is missing, report it as a missing asset directory and keep the rewrite conservative.
3. Read the target syntax rules when needed.
   - Read ../pandoc-md-publish/references/pandoc-markdown-checklist.md for citation, label, image, and equation rules.
   - Read ../pandoc-md-publish/references/crossref_config.yaml when reference prefixes or numbering behavior matter.
4. Normalize citations.
5. Normalize figures and images.
6. Normalize tables and table captions.
7. Normalize equations and equation references.
8. Normalize section labels and section references.
9. Run a final consistency pass.
10. Hand off to pandoc-md-publish.

## Local dependency and asset checks

- Check the current working directory for one or more `.bib` files before modifying citation formats.
- Treat the absence of a `.bib` file in the current working directory as a real constraint, not as permission to guess citation keys.
- If the source cites by explicit Pandoc keys or explicit LaTeX keys and the mapping is already written in the source, you may still normalize syntax without inventing new keys.
- Derive the original image directory from the source paths exactly as written, such as `images/`, `figures/`, or `assets/figures/`, and verify that directory exists.
- If the image directory does not exist, report `missing_image_directory` and avoid rewrites that would imply the assets were verified successfully.
- Do not search parent folders, sibling projects, or alternate asset locations.

## Citation normalization rules 

- Prefer Pandoc citation syntax such as [@key] and [see @key, pp. 2-4].
- Convert LaTeX commands such as \cite{...}, \citep{...}, \citet{...}, \autocite{...}, and similar author-year commands when the bibliography key mapping is explicit.
- Check whether the current working directory contains a `.bib` file before claiming citation rewrites are ready for downstream publishing.
- If no `.bib` file is present in the current working directory, call that out explicitly in the report.
- If the source already uses Pandoc citation syntax, keep it unless the key is clearly malformed.
- If the source uses numbered citations such as [1], [2-4], superscript numbers, or bracketed groups, convert them only when the mapping to bibliography keys is explicit or can be inferred from a clearly provided bibliography order.
- Never invent bibliography keys.
- If a numeric citation cannot be mapped safely, leave it in place and report it as unresolved_numeric_citation.
- Strip stray backticks and trailing periods from citation keys.

## Figure and image rules

- Prefer Markdown image syntax with a caption and a figure label.
- Convert HTML img, LaTeX includegraphics, or image-plus-caption patterns when the pairing is unambiguous.
- Check that the original image directory exists before rewriting image blocks.
- Keep image paths relative to the source Markdown file.
- Do not search unrelated folders for missing images.
- If the original image directory is missing, report that before any per-file image rewrite notes.
- If the image path contains spaces, prefer angle-bracket path syntax when needed.
- Convert textual references such as Figure 1, Fig. 1, Figure I, or see the figure above into @fig:... only when the target figure is unambiguous.
- If the figure exists but has no label, generate a stable short label and report the mapping.

## Table rules

- Prefer Pandoc table captions with {#tbl:...}.
- Convert plain text table caption lines such as Table 1. Results. into Pandoc captions when the caption-table association is unambiguous.
- Convert textual references such as Table 2 or Tbl. 2 into @tbl:... when the target is clear.
- If a table is referenced in text but no matching table target exists, report unresolved_table_reference.

## Equation rules

- Prefer inline math with single dollar delimiters.
- Prefer display math with double dollar delimiters.
- Convert LaTeX \label{eq:...}, \ref{eq:...}, and \eqref{eq:...} into Pandoc-style labels and references when the mapping is clear.
- For Word-oriented output, remove or flag raw \tag{...} blocks because they often break docx math conversion.
- Prefer cross-reference numbering over hardcoded equation numbers.
- If the source uses complex raw environments that Pandoc may not handle reliably for Word, keep the math but report suspicious_raw_latex_math.

## Section rules

- Preserve or add {#sec:...} labels to section headings when cross-references exist or are likely to be useful.
- Convert textual references such as Section 3, Sec. 2.1, or Chapter 3 into @sec:... only when there is a stable target.
- If a section reference cannot be mapped safely, report unresolved_section_reference.

## Ambiguity policy

- Safe partial normalization is better than aggressive guessing.
- If a transformation is not safe, keep the original text and report it.
- Never silently discard unresolved references.
- Never invent missing figures, tables, sections, or bibliography keys.
- Separate rewritten, left unchanged, and needs manual mapping in the report.

## Diagnostics checklist

Check at least the following:

- Whether the current working directory contains a `.bib` file
- Missing bibliography files
- Citation keys referenced but not found in the bibliography
- Missing original image directories
- Cross-references used but not defined
- Missing local images
- Numeric citations without safe key mapping
- Raw LaTeX equation constructs likely to break Word conversion
- Captions that are visually present but not attached to a figure or table block

## Output requirements

When using this skill, return:

1. The detected source style
2. The mode used: rewrite or diagnostics-only
3. A short local check summary that states whether a `.bib` file was found in the current working directory and whether the original image directory exists
4. A normalization summary grouped by citations, figures, tables, equations, and sections
5. A list of ambiguous or skipped rewrites
6. A short hand-off note for pandoc-md-publish
7. If content was rewritten, provide the normalized Markdown first and the report second
8. If diagnostics-only mode was used, do not rewrite content

## Hand-off to pandoc-md-publish

After normalization, suggest the next step:

- Run ../pandoc-md-publish/scripts/validate_markdown.py for preflight checks
- Then run ../pandoc-md-publish/scripts/convert_document.py for docx or pdf export

## Notes

- Prefer fixing root-cause Markdown issues before export.
- Keep labels stable once introduced so later references do not drift.
- If the user cares mainly about Word output, prefer Word-friendly math and cross-reference forms.
- If the repository already uses a working label or caption convention, align to it instead of inventing a new style.