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

## Regenerating / extending this set

Re-run `extraction_prompt.txt` against the PDFs in `raw/` with a different
model or prompt variant, and compare the resulting transaction counts and
field values against each filing's `ground_truth_n_transactions` and notes
in `manifest.json` to see whether it does better or worse than this Haiku
baseline.
