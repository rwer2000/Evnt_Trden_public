# Transcribing Schedule A of scanned House annual Financial Disclosure reports

You transcribe Schedule A ("Assets and 'Unearned' Income") of scanned US House annual
Financial Disclosure reports (public government documents) into a CSV. Accuracy
matters more than speed: this data feeds a financial analysis, and a wrong value band
is worse than a field marked uncertain.

## Input
Your group file is `<GROUP_FILE>`. It lists one report per line:
`DOC_ID|FILER NAME|comma-separated absolute page file paths`.
The page images live under `<PAGES_DIR>/<DOC_ID>/`. Open every page of every report
with the Read tool (it shows the image); a report can have 5-40 pages and Schedule A
can be anywhere among them, including continuation pages and attached brokerage
statements labelled as Schedule A. Pages may be rotated; read them as they are.
Use only these images: no other source, no PDF text, no web lookups.

Large reports (some run to 200 pages, mostly attached brokerage statements) are split
over several groups: then a group line lists only part of that report's pages. Read
and transcribe only the pages listed, keep the real page numbers, and if none of the
listed pages has Schedule A content write the single "no schedule A" row described
below with note = "no schedule A on listed pages".

## What to transcribe
Only Schedule A (titled "Assets and 'Unearned' Income", sometimes without the
quotes or with "SCHEDULE III" in older handwritten headers). Ignore every other schedule (earned income,
transactions, liabilities, gifts, positions, agreements, etc.), cover pages and the
printed example rows (e.g. "Simple Mega Corp. Common Stock", "Keystone Equity Fund").
Attached statements that list purchases and sales with dates are transactions
(Schedule B), not Schedule A: skip them. An attachment counts as Schedule A only if it
is labelled as such (or as a continuation of it) or lists holdings with a value at
year end and/or income for the year.

Schedule A columns are, left to right: the asset name (with, on some forms, an owner
code and an asset-type code), BLOCK B "Value of asset" at the end of the reporting
period, BLOCK C "Type of income" and BLOCK D "Amount of income". Value and income
amount are either a checked column in a grid of bands or written-in text. Handwritten
and typed forms both occur, and some filers attach their own typed table instead of
the grid.

One CSV row per asset line on Schedule A:
- An asset name that continues on the next line(s) without its own value or income
  entries belongs to the row above: join it into one asset_name.
- A brokerage or retirement account with sub-holdings listed under it: one row per
  line that has its own value or income entry; if the account header line has no
  entries of its own, still write it as a row (empty bands) so the structure is kept,
  with note "account header".
- If a report has no Schedule A content at all (blank schedule, "None", cover letter
  only, extension request), write a single row with doc_id, filer_name, page empty,
  all other fields empty and note = "no schedule A".

## Output
Write the CSV with the Write tool to `<OUT_PATH>`. Header and columns, exactly:

```
doc_id,filer_name,page,row_in_page,asset_name,ticker_on_form,asset_type_code,owner,value_band,income_types,income_amount_band,confidence,note
```

- `doc_id`, `filer_name`: copied from the group file line.
- `page`: the page number = the number in the image file name (`page-07.png` is 7).
- `row_in_page`: 1-based order of the asset line within that page.
- `asset_name`: as written, without the owner code. Quote the field if it contains a
  comma or a quote (standard CSV quoting).
- `ticker_on_form`: only if a ticker symbol is literally written on the form (e.g.
  "(PFE)"); never infer one from the company name. Otherwise empty.
- `asset_type_code`: only if a code is literally written (e.g. "ST", "MF", "RP");
  otherwise empty.
- `owner`: `SP` (spouse), `JT` (joint), `DC` (dependent child), or empty for the
  member (or when no owner is indicated).
- `value_band`: the exact text of the checked or written value band, normalised to the
  form's wording, e.g. `$1,001 - $15,000`, `$15,001 - $50,000`, `Over $50,000,000`,
  `None`; written-in exact values as written (e.g. `$23,450`). For a grid, read the
  band from the column header above the check mark. If nothing is entered, leave empty.
  Some forms show "Spouse/DC asset over $1,000,000" as its own column: write
  `Over $1,000,000 (spouse/DC)`.
- `income_types`: the income type(s) as written or checked, separated by `;` (e.g.
  `Dividends;Capital Gains`, `Interest`, `None`, `Rent`). Empty if nothing is entered.
- `income_amount_band`: exact text of the checked or written income amount band, e.g.
  `$201 - $1,000`, `None (or less than $201)`, `$1,001 - $2,500`; a written-in exact
  amount as written (e.g. `$345`). Empty if nothing is entered.
- `confidence`: `high`, `medium` or `low` for the row as a whole. Use `low` whenever a
  handwritten value, the checked column, or the row/column alignment is not clear.
- `note`: short free text for anything uncertain (e.g. "value could be $50,001 -
  $100,000"), or "no schedule A" / "account header" as above.

Do not guess silently. Do not invent rows. Do not skip rows because they look
unimportant. When done, reply with one line: the number of reports and rows you wrote,
and how many rows are `low` confidence.
