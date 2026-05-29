# Pandoc Markdown Checklist

Use this checklist before conversion when the user wants reliable references, figures, tables, equations, and images.

## Bibliography citations

- Prefer Pandoc citation syntax such as [@smith2024] or [see @smith2024, pp. 1-3].
- Keep citation keys aligned with the keys in the .bib file after removing stray backticks and trailing periods.
- If a citation renders as plain text or Pandoc warns that a citation was not found, verify the .bib key first.

## Figure, table, and equation references

- Use explicit labels such as {#fig:workflow}, {#tbl:results}, and {#eq:loss}.
- Refer to them with @fig:workflow, @tbl:results, and @eq:loss.
- Keep the fig/tbl/eq prefixes consistent with pandoc-crossref expectations.
- If a reference exists in text but the label is missing from the source, pandoc-crossref cannot resolve it.

## Images

- Prefer Markdown image syntax such as ![Caption](images/figure1.png){#fig:workflow}.
- Keep local image paths relative to the Markdown file or add the containing folder to Pandoc resource paths.
- Remote images over http/https are not validated locally by this skill.
- If a local path contains spaces, prefer angle-bracket syntax around the target when needed.

## Equations

- Use standard inline math like $a+b$ and display math like $$E=mc^2$$.
- For equation cross-references, add labels such as {#eq:loss} to display equations.
- For docx output, LaTeX tag commands like \tag{1} often need to be removed or converted before Pandoc can build Word equations reliably.
- If the user wants to preserve raw LaTeX instead of rendering Word equations, use the raw-latex mode in the conversion script.
- For a DOCX in which all formulas are AxMath objects, use `--equation-mode axmath`; write inline formulas as `$...$` and display formulas as `$$...$$`.
- AxMath conversion requires Windows, Word, and the AxMath add-in. The postprocessor groups formula-containing body paragraphs, skips headings, and runs `AMSTeX2AM` on each group so heading sizes do not affect formula sizes.
- Use `--axmath-visible` only for diagnosis when Word COM or the AxMath add-in appears to hang; a successful run should include `Segmented body AMSTeX2AM conversion finished.` and `residual_tex=0` in the `.axmath.log`.

## Word style reference

- Use a .docx reference document with named styles already defined.
- Match pandoc-crossref style-related configuration, such as Figure, with styles that actually exist in the reference document.

## Typical failure causes

- Missing .bib entries for cited keys.
- Missing local image files.
- Cross-reference labels referenced in text but never defined.
- Missing pandoc-crossref executable.
- Missing LaTeX engine during PDF conversion.
