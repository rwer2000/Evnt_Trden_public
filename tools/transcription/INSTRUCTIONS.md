# Transcribing scanned House Periodic Transaction Reports (PTRs)

You transcribe scanned US House PTR forms (public government documents) into a CSV.
Accuracy matters more than speed: this data feeds a financial analysis, and a wrong
date or amount band is worse than a field marked uncertain.

## Input
Your batch file lists one filing per line: `DOC_ID|FILER NAME|page files`.
Page images are at `<PAGES_DIR>/<DOC_ID>/<page file>` (the orchestrator fills in PAGES_DIR).
Open every page of every filing with the Read tool (it shows the image). Pages may be
rotated 90 degrees; read them as they are. Do not use any other source.

## What to transcribe
One CSV row per transaction row on the form. The form's columns are: owner (SP = spouse,
DC = dependent child, JT = joint, blank = the member), full asset name, type
(Purchase / Sale / Exchange, sometimes "Sale (partial)"), date of transaction, date
notified, and an amount band checked in columns A–K (A $1,001–15,000; B $15,001–50,000;
C $50,001–100,000; D $100,001–250,000; E $250,001–500,000; F $500,001–1,000,000;
G $1,000,001–5,000,000; H $5,000,001–25,000,000; I $25,000,001–50,000,000;
J over $50,000,000; K = "transaction in a spouse or dependent child asset over
$1,000,000", a flag, not a band).

- Skip the printed example row ("Mega Corp. Common Stock").
- An asset name that continues on the next line(s) without its own checkboxes belongs
  to the row above: join it into one asset_name.
- Some typed (electronic-looking) forms have a column layout like
  "owner | asset | type (P/S/S (partial)/E) | date | notification date | amount".
  Transcribe those the same way.
- If a filing has no transaction rows at all (blank form, cover letter only), write one
  row with doc_id, all other fields empty and note = "no transactions".

## Output
Write the CSV with the Write tool to the output path you are given. Header and columns,
exactly:

```
doc_id,page,row,owner,asset_name,ticker,tx_type,tx_date,notification_date,amount_band,k_flag,confidence,note
```

- `page`: page number (1-based); `row`: 1-based row order within that page.
- `owner`: `self`, `spouse`, `joint` or `child`.
- `asset_name`: as written, quotes around it if it contains a comma.
- `ticker`: only if a ticker symbol is literally written on the form (e.g. "PFE");
  never infer one from the company name. Otherwise empty.
- `tx_type`: `purchase`, `sale_full`, `sale_partial` or `exchange`.
- `tx_date`, `notification_date`: `YYYY-MM-DD`. Two-digit years are 20xx. If a date is
  missing, leave it empty.
- `amount_band`: the band letter `A`–`J`, or empty if none is checked.
- `k_flag`: `1` if column K is checked, else empty.
- `confidence`: `high`, `medium` or `low` for the row as a whole. Use `low` whenever a
  handwritten value, the checked column, or the row/column alignment is not clear.
- `note`: short free text for anything uncertain (e.g. "date could be 11/18/16").

Do not guess silently. Do not invent rows. When done, reply with one line: the number
of filings and rows you wrote, and how many rows are `low` confidence.
