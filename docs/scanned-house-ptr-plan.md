# Plan: scanned House PTRs

Status: **not started** — written 2026-09-24 as a handoff for a fresh session.
Each phase below is self-contained. Do them in order, and stop at the end of
each phase to report to the owner before starting the next.

Origin: session https://claude.ai/code/session_01PTKvPM3DvVAJvwirNCwUsM (the
16-filing Haiku test batch) and PRs #81–#84.

## Ground rules

These apply to every phase. When a rule collides with a task, the rule wins:
stop and ask the owner.

1. **No production writes without an explicit, per-instance go from the
   owner.** That covers `congress.*` tables and the `congress-raw` bucket.
   Read-only SQL (the Supabase MCP `execute_sql` tool, project
   `pcpdttjwowhrzlltnyuw`, always with the `congress.` schema prefix) and
   Storage downloads are fine.
2. **No LLM extraction runs without the owner's go.** They cost money, even
   small ones. Report `total_cost_usd` for every call you make.
3. **Existing golden outputs must not change.** `tests/golden/` is the CI
   regression gate for the deterministic parsers (52 filings). A parser change
   may *add* golden entries; if any existing entry changes, stop and explain
   why before regenerating.
4. **Verify, don't trust.** Every claim about a filing must be checked against
   the PDF itself. This applies to a vision model's extractions *and* to its
   stated reasons for failing: #83 caught one such reason that was invented,
   while another turned out to be true (the Stivers missing page).
   Also check this plan's own claims.
5. `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` come from the environment.
   Never write them to a file.
6. Code, comments, commit messages and PR descriptions in English. Small
   commits, each green on what CI runs: `uv run ruff check .`,
   `uv run ruff format --check .`, `uv run mypy`, `uv run pytest`.
   Never push to `main`.

## Background

`congress.filings` has 4,680 House PTRs (`chamber='house'`,
`filing_type='P'`) with `format='scanned'` and `parse_status='paper_deferred'`,
each with an archived PDF (`raw_object_key`). None have transactions.
`scan_classification.classify_scan_tier()` (#81) splits them by document ID:

| Tier | ID shape | Filings | Years |
|---|---|---|---|
| CLEAN | 8 digits starting `20` | 2,826 | 2015–2022 only |
| RISKY | 7 digits starting `8` or `9` | 1,854 | 2015–now; the only series for new scans |

The eval set lives in `tests/fixtures/scanned_house_ptr_llm_testset/`
(16 filings: 7 CLEAN, 9 RISKY; PDFs, raw `claude -p` responses, prompts v1–v3,
`manifest.json` with hand-checked ground truth). Its `README.md` records the
Haiku results: CLEAN near-perfect, RISKY unreliable in dangerous ways
(invented company names, a legend read as transaction rows, silent
under-extraction, a handwritten filing returned empty).
`scan_verification.verify_extraction()` (#81, #84) is the mechanical sanity
check for LLM output.

### Key finding: the CLEAN tier is not scanned at all

Checked on all 7 CLEAN filings in the eval set: each has a real text layer
(106–637 words, including every transaction row). They are ordinary
electronic filings. Two case-sensitive checks in `house_ptr.py` misclassify
them:

- `is_electronic()` (`house_ptr.py:215`) looks for the words `Notification`
  and `Transaction`. In these filings the text layer renders the column
  headers in lowercase (`iD owner asset transaction type Date notification
  Date amount`), the same font quirk the module docstring already describes
  for tx-type codes. So `is_electronic()` returns `False`, and
  `ingest/house_ptrs.py:76` marks the filing `scanned` / `paper_deferred`.
- `_detect_column_bounds()` (`house_ptr.py:222`) looks for `Owner`, `Asset`,
  `Transaction`, `Notification` and `Amount`, misses the lowercase header, and
  falls back to the 2026-era bounds. For the 2018–2021 layout the tx-type
  column sits at x0≈246, left of the fallback `ASSET_MAX_X = 260`, so no row
  is ever recognized as a transaction. The 2016–2017 layout (x0≈269) happens
  to fit the fallback. `_is_header_line()` (`house_ptr.py:372`) has the same
  case-sensitivity.

Prototype (monkeypatched, never committed): with only the header words
matched case-insensitively (in `_detect_column_bounds` and
`_is_header_line`), the existing parser extracted **32 of 32 transactions
across all 7 CLEAN filings, with every per-filing count matching ground
truth**, including the 22-row `house:20019240`. One remaining gap:
`house:20006123` writes `10/6/2016`, and `_DATE_RE` (`house_ptr.py:142`)
requires two-digit month and day, so its dates came out `None`.

Caveat: this is 7 files, not 2,826. Phase 1.3 exists to check it at scale.

This contradicts the `scan_classification.py` docstring on `main`, which says
all of `format='scanned'` is image-only. It says so based on 25 samples where
`is_electronic()` was `False` "even where pdfplumber extracted 100–900 words
of unrelated coversheet/letterhead text". Those words were probably the
filings themselves. Which tier those 25 came from is unknown; re-check.

---

## Phase 1 — Parse the CLEAN tier deterministically

Goal: the 2,826 CLEAN filings go through the existing parser at zero model
cost, deterministically and under CI, instead of through a vision model.

### 1.1 Parser fix (`src/congress_collector/parsers/house_ptr.py`)

- [ ] `_detect_column_bounds()`: match header words case-insensitively
      (`owner`, `asset`, `transaction`, `date`, `notification`, `amount`,
      `cap.`).
- [ ] `_is_header_line()`: same.
- [ ] `_DATE_RE` accepts 1–2 digit month and day; `_to_iso_date()`
      zero-pads, so `10/6/2016` becomes `2016-10-06`.
- [ ] `is_electronic()`: **don't just lowercase the word check.** Main's
      docstring reports genuine scans with 100–900 words of coversheet text;
      a loose word check could flip a real scan to electronic. Preferably
      define "electronic" as "a header row with owner/asset/transaction/
      notification/amount on one line was found", sharing the logic with
      `_detect_column_bounds()`. Decide based on 1.3's data, not on this
      suggestion.
- [ ] Update the module docstring (a fifth pre-2022 quirk: lowercase column
      headers, and the resulting misclassification).

### 1.2 Tests

- [ ] Unit tests in `tests/test_house_ptr_parser.py` for a lowercase header
      row and a single-digit date.
- [ ] Add the 7 CLEAN PDFs to the golden set: copy them from
      `tests/fixtures/scanned_house_ptr_llm_testset/raw/house__*__20*.pdf`
      to `tests/golden/raw/` (same `house__<year>__<id>.pdf` naming), run
      `uv run python tests/golden/regenerate.py`, and confirm the diff
      **only adds** entries. Hand-check each new entry against the PDF.
- [ ] `tests/test_scan_classification.py` still passes, or is updated
      deliberately (see Phase 2).

### 1.3 Read-only validation at scale

Nothing is written in this step.

- [ ] Sample ~100 CLEAN filings stratified by filed year (2015–2022) plus
      ~50 RISKY ones. Download from `congress-raw`, run the patched
      `is_electronic()` + `parse_ptr_transactions()` locally.
- [ ] Report per tier and year: share with a text layer, share classified
      electronic, share with ≥1 parsed row, and any parse errors.
- [ ] **False-positive check:** no RISKY filing may flip to electronic. If
      any does, open it and find out why before going further.
- [ ] Hand-check ~10 CLEAN filings row by row against the PDF, spread over
      the years, including a multi-page one.
- [ ] Also parse a few older filings with `format='electronic'` to confirm
      nothing regresses outside the golden set.
- [ ] Stop and report to the owner.

### 1.4 Backfill (owner go required)

- [ ] Write a one-off script following `ingest/reparse_failed_house_ptrs.py`
      (#73): select `chamber='house'`, `filing_type='P'`,
      `format='scanned'`, `parse_status='paper_deferred'`. For each filing:
      download, run the fixed classifier and parser. On success, set
      `format='electronic'`, save the transactions, and set `parse_status`
      the way the live path does. Leave filings that still don't parse
      untouched.
- [ ] Dry-run by default (counts only, no writes); a real run needs an
      explicit flag. Idempotent and safe to re-run.
- [ ] **No Telegram notifications.** These are historical filings; the live
      `notify_parsed_transactions()` in `ingest/house_ptrs.py` must not fire.
- [ ] Present the dry-run numbers to the owner. Run for real only on their
      explicit go.
- [ ] Afterwards: re-run the per-tier counts and the DQ report, and record
      how many filings are left in `format='scanned'` (expected ≈1,854).

The live pipeline needs no separate change: new filings pass through the
same fixed `is_electronic()`.

---

## Phase 2 — Correct the record

Documentation and data only; no behaviour change beyond what Phase 1 did.

- [ ] `src/congress_collector/parsers/scan_classification.py` docstring:
  - the claim that all of `format='scanned'` is image-only (lines ~11–15) is
    wrong for the CLEAN series;
  - CLEAN is not "a cleanly laid-out, checkbox-style scanned form"
    (line ~20). It is the electronic e-filing template with a text layer.
  - After Phase 1, CLEAN filings are no longer `scanned`. Decide with the
    owner whether the CLEAN tier stays (as a historical note) or goes.
- [ ] `tests/fixtures/scanned_house_ptr_llm_testset/manifest.json`, known
      errors from the original batch:
  1. `extrapolated_cost_usd_4680.using_sample_median_plus_one_outlier`
     ($227.37) is mislabeled: it is the mean *excluding* the Khanna outlier
     × 4,679 + $0.41. Median × 4,680 is ≈$195.
  2. `house:9114491` notes say it tried `apt-get install poppler-utils`.
     Wrong filing: that was `house:20019240`'s first attempt. `9114491`
     claimed poor scan quality and asked for Python/OCR tools.
  3. `house:8220570` `scan_style` says "nette digitale PTR-layout". Wrong:
     it is a hand-delivered paper form with typed attachment pages and no
     text layer (0 words).
  4. `house:8220570` was worse than recorded. Besides the DC→`self`
     owner error, the SP sale rows on page 11 (Corning, Carter's, Bank of
     America, Infinera) were extracted as `purchase`. The v1 extraction
     appears to stop around page 11 of 23. The #81 commit message calls the
     rows "otherwise-correct"; it can't be amended, so correct the claim in
     the manifest and in the `scan_classification.py` docstring
     (line ~30).
  5. `house:9107699`: the archived PDF is missing page 2 (see the testset
     README). Its ground truth "6–8" is partly unknowable; say so.
  6. The per-filing notes are in Dutch; the rest of the repo is English.
     Translate while you are in there.
- [ ] Update the testset `README.md` summary: CLEAN-tier results are now a
      parser question, not a vision question.

---

## Phase 3 — The RISKY tier (1,854 filings plus every new scan)

This is the real vision problem. Cost is not the constraint: Haiku cost
roughly $0.06 (median) to $0.10 (mean) per RISKY filing in the test batch,
≈$100–180 for one pass. Quality is the constraint: failures here were
confident fabrications, not just gaps. **Nothing from this tier goes into
the database without human review, whatever the extraction method.**

### 3.1 Stronger-model eval (owner go required)

- [ ] Run the 9 RISKY eval filings through a stronger model (Sonnet and/or
      Opus via `claude -p --model <alias> --output-format json
      --allowedTools Read`) with `extraction_prompt_v3.txt` (self-reported
      row count). Run a timeout of at least 420 s: Khanna needed ~373 s with
      Haiku, and 180 s killed two runs.
- [ ] Store raw responses next to the existing ones, e.g.
      `extractions_v3_<model>/`.
- [ ] Score each against the manifest ground truth. Run
      `verify_extraction(transactions, reported_total_rows=…, page_count=…)`
      on every result and record what it flags.
- [ ] Report per filing and in total: correct / partial / fabricated /
      empty, cost, and duration.

### 3.2 Decision (owner)

Present the 3.1 results with a recommendation. Options:

- **A.** LLM extraction + `verify_extraction()` + a mandatory human review
  queue before anything is written. Needs a review design (staging table or
  flag, who reviews, how corrections are recorded).
- **B.** No extraction. Keep RISKY filings as `paper_deferred`, and only
  notify with a link to the PDF (the Senate paper-filing pattern).
- **C.** Hybrid: extract only when `verify_extraction()` passes and the
  filing is small (e.g. ≤ 20 rows), still with review; B for the rest.

### 3.3 Build what was decided

Scope it once the owner has chosen. Consider new live filings first: every
scanned filing since 2023 is RISKY, so this is what the live tool would see.

---

## Phase 4 — Make the eval set measurable

The eval set can't measure under-extraction on the two largest filings,
because their ground truth is an estimate.

- [ ] Transcribe full row-level ground truth for `house:8218645` (McCaul,
      6 pages; v3 estimated ~210–230 rows) and `house:8220570` (Khanna,
      23 pages; v3 self-reported 362). Store it as data (e.g.
      `ground_truth/<filing>.json`, same fields as `ParsedTransaction`),
      not as prose.
- [ ] Add row-level ground truth for the other RISKY filings (they are
      small).
- [ ] A small scoring script that compares any extraction to the row-level
      ground truth: rows found / missed / invented, and per-field accuracy
      (owner, tx_type, dates, amount bracket, asset name).
- [ ] Re-score the existing v1/v2/v3 Haiku extractions with it, so Phase 3
      has a real baseline.

Phase 4 can run in parallel with Phase 1. It should finish before the 3.2
decision.

## Open questions for the owner

1. Phase 1.4: go for the backfill after seeing the dry-run numbers?
2. Phase 3.1: budget and go for the stronger-model eval run.
3. Phase 3.2: option A, B or C, and if A or C, who reviews.
