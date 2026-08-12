---
name: paper-completion-arxiv-en
description: "Complete the missing sections of a finished paper draft (abstract, introduction, supporting body paragraphs, conclusion, acknowledgments, references) without altering its reasoning or final results. Workflow: extract key theories/formulas/conclusions from the draft → search arXiv for related papers from the past year (top 40) → verify journals online, group by journal tier, and let the user pick 3/5/10 papers → download TeX sources → rewrite and integrate similar theory/method passages with proper citations. Also supports: verifying existing references one by one (journal/volume/article number/year/authors compared against online records), and safely editing paper LaTeX (backup → exact replacement → read-back verification → compile in a temp directory). Triggers: requests to complete/fill in/polish the missing parts of a paper, add or check references, or edit paper LaTeX, when the paper's main body is already written. Not for revising reasoning, changing conclusions, or writing from scratch."
---

# arXiv-Based Paper Completion

## Applicability (verify first)

- The paper body (theoretical derivation + numerical analysis) is already complete; do not change the reasoning or final conclusions.
- The task is to fill in: abstract, introduction, citable supporting paragraphs in the body, conclusion, acknowledgments, references.
- If the user actually wants to revise reasoning/conclusions or write from scratch, state that this skill does not apply and stop; do not force it.

## Workflow

### Step 1: Dissect the draft

Read the whole draft and extract:

- Theory/method keywords (e.g., Floquet theory, tight-binding model, density functional theory, Monte Carlo)
- Key formulas (record symbols and equation numbers)
- Core conclusions and numerical results

Produce a keyword list of theories / formulas / conclusions; base all subsequent searches on it.

### Step 2: Search arXiv (past year, top 40)

Run `scripts/search_arxiv.py` with the keyword list:

```bash
python scripts/search_arxiv.py "floquet theory" --limit 40 --years 1
```

The script prints a relevance-ranked list (arXiv ID, title, authors, publication date, journal_ref if any). Add `--json <file>` to save results for later steps.

If no results: broaden the keywords, drop journal-specific terms or obscure abbreviations, retry; extend `--years` as a fallback. Record the queries actually used.

### Step 3: Classify journals by tier, then let the user choose

1. For each result, use web search to confirm the final journal and its tier (tier refers to journal standing, not field — e.g., Phys. Rev. A/B ≈ second tier, Phys. Rev. Lett. ≈ first tier).
2. Papers with no confirmed journal go under "Unpublished / arXiv preprint".
3. Group results by tier into a table (arXiv ID / Title / Journal / Tier), send it to the user, and ask them to choose 3/5/10 papers for source download (default 5 if unspecified).
4. This is a human-confirmation gate: do not proceed to Step 4 until the user confirms; never decide the downloads yourself.

### Step 4: Download TeX sources

For the selected papers, run:

```bash
python scripts/download_arxiv_sources.py 2401.00001 2401.00002 --out work/tex_sources
```

The script downloads from `https://arxiv.org/e-print/<id>` and unpacks tar.gz / single-file gz / plain TeX, one subdirectory per paper. If a paper has no TeX source (PDF only), note it and fall back to extracting text from the PDF in Step 5.

### Step 5: Material extraction, source tracing, and author-driven integration (core)

Boundaries and principles:

- The agent only provides factual material, bibliographic metadata, and standard-expression drafts of basic theory. The overall narrative logic of the introduction, the research gap, and the novelty argumentation must be designed and finalized by the human author; the agent must not autonomously generate complete survey paragraphs.
- Prioritize tracing the original foundational literature; secondary citations (citing via another paper) are forbidden by default.

For each paper:

1. Open the `.tex` source and extract standalone factual statements, standard theory definitions, and basic method descriptions; do not cut complete survey paragraphs or narrative chains.
2. Identify the original foundational literature for each statement and prefer recommending the original source over the current arXiv preprint.
3. Hand the material to the author, who organizes the paragraph logic; the agent only rewrites and polishes within the author's paragraph framework and completes `\cite` and bib entries; never cut-and-paste ready-made survey paragraphs from other papers.
4. After all papers are processed, remind the author to manually verify every attribution, citation, and formula symbol; the paper is ~95% complete, with plagiarism check, polishing, and gap-filling remaining under human collaboration.

## Reference verification (existing citations)

Applies when the paper already has a `\bibitem`/bib list and every entry must be confirmed real, with journal, volume, page/article number, year, and authors correct.

1. Extract all `\bibitem` (or bib entries) and check each field: journal name, volume, page or article number, year, authors (including the first author when "et al." is used).
2. One search per entry: keywords = author + journal + volume + page + year. Trust APS pages, journal DOIs, ADS/INSPIRE, and publisher records first.
3. If no results or uncertain, change keywords: add title keywords, DOI, arXiv ID, or full author names; if still missing, search "author + title + year" without the journal name; mark the entry as "Uncertain" if it still cannot be found.
4. Record evidence per entry (DOI / ADS bibcode / publisher link). Use only three statuses: "✓ Real / Uncertain / Not real"; list uncertain and not-real entries separately with justification.
5. Write the verification report to the working directory (not the paper directory). Template: references/reference-verification-report.md.

## Safe LaTeX editing and compile verification

Every change to a paper .tex file must follow:

1. Backup: before editing, copy the original file to a timestamped backup in the same directory; never overwrite the only copy.
2. Exact replacement: use `scripts/patch_tex.py` (multiple old→new pairs; validates each occurrence count; preserves CRLF/LF line endings; reads UTF-8-sig, writes UTF-8).
3. Read-back verification: re-read the modified region and confirm the replacements and context.
4. Compile verification: copy the .tex and dependencies such as figures/ to a temp directory, build with `latexmk -pdf`, and check the log for:
   - `LaTeX Error` / `!` (compile errors)
   - `Float too large` (float too tall → shrink image width or adjust the layout)
   - `undefined` / `Undefined` (unresolved citations/cross-references; recompile a second time)
   - Write the produced PDF only to the temp directory; never overwrite the paper directory.
5. If the target file is in a protected directory (Desktop, ~/.codex, etc.), obtain write permission first.

## Undergraduate variant

- If the author is an undergraduate, replace Step 2 with a keyword search on CNKI (https://www.cnki.net). Classification is still by journal tier; extract full-text content from PDFs (no TeX source). Everything else stays the same.

## Rules and boundaries

- Academic integrity: all integrated content must be rewritten and properly cited; the final paper must pass plagiarism checking; prefer citing the original sources.
- Backup before editing: before modifying the paper's source file, always save a timestamped backup copy in the working directory and work from it, so every change can be rolled back; never overwrite the only copy of the source file.
- Intermediate files (search JSON, downloaded sources) go in the working directory, not the paper's directory.
- Step 3 is a human-confirmation gate: do not download or integrate before the user chooses.
