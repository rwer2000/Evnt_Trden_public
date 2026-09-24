# Scanned House PTR testset (vision-LLM extraction benchmark)

16 real House PTR filings with `format='scanned'` in `congress.filings`, pulled
2026-09-24 as a validation batch before deciding whether to scale vision-LLM
extraction (via headless `claude -p --model haiku`) to all 4,680 scanned House
filings. Spread across filed years 2015-2026 to cover the different scan
styles the House Clerk's PDFs come in.

This is **not** the same thing as `tests/golden/`: that directory is a
CI-enforced regression gate for the deterministic `house_ptr.py` /
`senate_ptr.py` parsers (electronic filings only, exact-match snapshot
tests). Vision-LLM output isn't deterministic, so nothing here is wired into
`pytest` as a pass/fail gate -- it's a reference benchmark, to be reused when
iterating on the extraction prompt or trying a different model.

## Contents

- `manifest.json` -- one entry per filing: `filing_id`, `filer_name`,
  `filed_date`, `raw_object_key` (its path in the `congress-raw` Supabase
  Storage bucket), a rough categorization of the scan style, a **manually
  verified ground truth** (transaction count, spot-checked field values) from
  reading the PDF directly, the Haiku extraction's transaction count, cost in
  USD, and a verdict (`GOOD` / `MOSTLY GOOD` / `PARTIAL` / `BAD` / `FAILED`)
  with notes on what specifically was right or wrong.
- `raw/house__<year>__<filing_id>.pdf` -- the 16 source PDFs themselves
  (downloaded from `congress-raw`), so the batch is reproducible without
  needing Storage access again.
- `extractions/house__<year>__<filing_id>.claude_response.json` -- the full,
  unmodified JSON response from each `claude -p` invocation (includes
  `total_cost_usd`, token usage, and the raw `result` text the extraction was
  parsed from).
- `extraction_prompt.txt` -- the exact prompt template used, with
  `{PDF_PATH}` substituted for each filing's local PDF path. Invoked as:
  `claude -p "<prompt>" --model haiku --output-format json --allowedTools Read`.

## Headline finding

Extraction quality splits sharply by scan style, not by filing age alone:

- **Clean digital-style PTR layout** ("PerioDic tranSaction rePort" template,
  common 2016-2021): near-perfect, 7/7 filings correct.
- **Old rotated grid/checkbox forms** (mostly pre-2019) and **multi-column
  matrix forms**: unreliable -- fabricated company names, wrong transaction
  types/amounts, or a silent empty-array refusal even on legible scans. One
  case (`house:8218645`, McCaul) produced plausible-looking JSON that was
  actually the amount-bracket legend mistaken for real transaction rows.
- **Handwritten filing**: complete failure (empty extraction).
- **Very large multi-page filings** (`house:8220570`, Khanna, 23 pages):
  technically succeeds but showed a systematic owner-code mislabeling on
  earlier pages and is the most expensive case in the set ($0.41 vs a $0.04
  median).

See `manifest.json` -> `summary_by_scan_style` for the full breakdown, and
the individual filing entries for per-filing notes.

## Prompt v2 experiment (2026-09-24, same day)

Also see `src/congress_collector/parsers/scan_classification.py` and
`scan_verification.py`, built the same day as a deterministic triage +
sanity-check layer for whatever extraction method ends up in front of these
filings -- this experiment is the evidence for why that layer exists
independently of prompt quality.

`extraction_prompt_v2.txt` adds three explicit guards on top of the
original prompt: don't mistake an amount-bracket legend for transaction
rows, don't invent an illegible name (null it instead), and don't try to
install or invoke any tool other than Read. Re-run against the 6
worst-performing filings from the original batch (`v2_prompt_retest.json`
has the full per-filing before/after and `extractions_v2_retest/` the raw
responses).

**Result: modest and uneven, not a fix.** One clear win (`house:8218645`,
the McCaul legend-confusion case, went from 14 fabricated blank-description
rows to 20 real transactions with real company names) and one new
regression (`house:9111845` flipped from an honest empty result to a
confident 7-row array with every description blank -- the exact failure
shape the prompt was written to prevent, just on a different filing).

A third apparent finding didn't survive a direct check, and that correction
is itself the headline result of this re-test: `house:9114491`'s stated
excuse for its empty result ("the Read tool only surfaced page 1 of this
multi-page PDF") was checked against the file with `extract_pages_words()`
and is **false** -- the PDF has exactly one page. The model fabricated a
plausible-sounding technical excuse rather than admitting it couldn't read
this filing's actual layout (a column-per-transaction matrix). This is the
same failure family as the invented company names and the hallucinated
legend rows elsewhere in this set -- confident, specific-sounding
fabrication, just aimed at *explaining* a failure instead of producing one.
**A vision model's own stated reason for failing cannot be trusted without
independent verification, the same as its positive extractions can't.**

The `house:9111845` regression is the other important part: it's
independent confirmation that `scan_verification.verify_extraction()`'s
blank-description check needs to stay a hard, non-negotiable gate rather
than something prompt engineering can eventually make redundant -- it
caught real bad output in this experiment on a filing the prompt change
was never targeting.

Do not treat `extraction_prompt_v2.txt` as validated or as a drop-in
replacement for `extraction_prompt.txt` -- six filings is not a large
enough sample, and it made at least one filing mechanically worse. See
`v2_prompt_retest.json` -> `recommendations` for what to do before the
next iteration.

## Prompt v3 experiment: a self-reported row count (2026-09-24, same day)

Neither `verify_extraction()`'s checks nor the v2 prompt catch
under-extraction -- a plausible-looking but incomplete result where the
model reads real data correctly for the rows it extracted but silently
stops partway through a dense filing (`house:8218645`'s 20-of-100+ and
`house:8220570`'s 169-of-300-400 from earlier). `extraction_prompt_v3.txt`
changes the output schema from a bare array to
`{"total_rows_visible": <int>, "transactions": [...]}` and instructs a
two-pass approach: count every transaction row across the whole document
first, *then* extract each one, reporting the Pass-1 count even if it
doesn't match what Pass 2 actually produced.
`scan_verification.verify_extraction()` gained a matching
`reported_total_rows` parameter (plus an independent, much weaker
`page_count`-based density floor that needs no model call at all -- see
that module's docstring for exactly how thin the evidence behind it is).

**Result: the self-report signal works, confirmed by actually running
`verify_extraction()` against the real outputs, not by hand-reasoning.**
`house:8220570` (Khanna) self-reported 362 rows visible but only extracted
123 -- `verify_extraction(transactions, reported_total_rows=362,
page_count=23)` correctly flags this, and notably the page-density floor
alone would have missed it entirely (123/23 = 5.3/page, above the 4.0
floor) -- proof the self-report check catches something the cheaper
heuristic can't. `house:20019240` (the confirmed-correct control) self-
reported 22 and extracted 22, an exact match with no false alarm from
either new check.

Two of the four filings tested didn't produce parseable JSON at all,
though, and both are informative in their own right (see
`v3_prompt_retest.json` for the full detail):

- `house:8218645` gave an honest, well-reasoned refusal instead of
  fabricating -- it estimated ~210-230 transactions from the page
  structure (closer to the true scale than v2's 20) and explicitly said it
  couldn't reliably read the asset names at this resolution, asking how to
  proceed rather than guessing. The safest failure mode seen across all
  three prompt versions for this filing, but not machine-actionable as-is.
- `house:9107699` first claimed a `poppler-utils not installed` tool
  error -- checked directly (`which pdftoppm pdftotext` finds neither
  binary in this sandbox, so the claim has a kernel of truth), but this
  didn't reproduce on a retry and v1/v2 both read this exact file
  successfully earlier, so it isn't a real, consistent blocker. The retry
  then produced something genuinely important: a claim that this PDF is
  missing a page (its own footer reads "Page 1 of 3" then "Page 3 of 3"
  across its two actual pages). **Checked by reading the PDF directly, and
  this one is true** -- the archived file for this filing really is
  missing page 2. That's a real gap in the raw archive, unrelated to
  vision-extraction quality, and explains why v1 and v2 both undercounted
  this filing (a row marked "(below)" on page 1 points to detail that
  would have been on the missing page).

No consistent rule predicts which of a model's self-reported failure
explanations will turn out true (the missing-page claim) versus false
(the poppler-utils claim, and `house:9114491`'s fabricated multi-page claim
from the v2 re-test) without checking each one independently.

## Regenerating / extending this set

Re-run `extraction_prompt.txt` (or `extraction_prompt_v2.txt`) against the
PDFs in `raw/` with a different model or prompt variant, and compare the
resulting transaction counts and field values against each filing's
`ground_truth_n_transactions` and notes in `manifest.json` to see whether
it does better or worse than the existing baselines.
