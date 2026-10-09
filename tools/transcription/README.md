# Transcribing scanned House PTRs

The method behind `data/transcribed_house_ptrs_*.csv`. It lives here, not in a
session scratchpad, so any Claude session or account can continue a batch.

## Procedure

1. **Pick the filings.** Scanned House PTRs are `filings` rows with
   `format = 'scanned'` and `parse_status = 'paper_deferred'` (DocIDs
   8xxxxxx/9xxxxxx). Choose a batch, for example the filers who miss the
   fewest PTRs first (see `docs/status.md` in the strategy repo).
2. **Fetch and render.** The PDFs are public:
   `https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/<index year>/<DocID>.pdf`.
   The year is the House index year, which is usually the filing year and
   sometimes the year before or after. Render each page with
   `pdftoppm -r 150 -png <DocID>.pdf <PAGES_DIR>/<DocID>/page`.
3. **Make groups.** Split the batch into groups of about 20–25 filings, or
   about 40 pages. Each group is one text file of lines
   `DOC_ID|FILER NAME|page files`. Name the groups `g01`, `g02`, and so on;
   `g12b` is the second half of a split group.
4. **Two independent readings per group.** Run two subagents per group, A and
   B. Each one gets `INSTRUCTIONS.md` with `<PAGES_DIR>` filled in, plus its
   group file and its output path (`out/<group>_A.csv` or
   `out/<group>_B.csv`). The two readings must not see each other's output.
5. **Commit as you go.** After each group, commit both CSVs to the working
   branch under `data/transcription_work/<batch>/` and push. If the session
   or account runs out, another one continues from the next group.
6. **Compare and resolve:**

   ```bash
   python tools/transcription/compare.py --a 'out/*_A.csv' --b 'out/*_B.csv' \
       --out merged.csv --fixes fixes.json
   ```

   Look at the scan again for every row it lists. Do the same for every
   filing whose row counts differ. Record each decision in `fixes.json` and
   rerun until nothing is unresolved.
7. **Owner check, then import.**
   - Copy `merged.csv` to `data/transcribed_house_ptrs_<date>[letter].csv`.
   - Give the owner a sample of about 10 filings, with the scans, to check.
   - After their approval: open a PR. Once it is merged, run the
     `import-transcribed-ptrs` workflow with the CSV path.
   - Remove `data/transcription_work/<batch>/` in the same PR.

## Rules

- Never infer a ticker from a company name; only a ticker written on the form
  counts.
- Mark doubt as `low` confidence with a note; never guess silently.
- Rows without a transaction type become `unknown_tx_type` dq issues on
  import; that is expected.
- The import skips filings that are already parsed, so rerunning it is
  harmless.
