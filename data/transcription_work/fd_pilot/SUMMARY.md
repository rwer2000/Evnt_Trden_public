# FD pilot (E2): interim agreement, 2026-10-11

Sample: 20 paper House annual reports (seed 20261011, `sample.csv`), 539
pages in 15 groups. Two independent readings per group (A, B), method in
`tools/transcription/INSTRUCTIONS_FD.md`.

Interim, groups g01 and g04-g14 (11 reports, both readings complete),
`compare_fd.py`:

| Field | Agreement on matched rows (1,021) |
|---|---|
| asset_name | 97.7% |
| owner | 95.0% |
| value_band | 97.7% |
| income_types | 99.9% |
| income_amount_band | 100.0% |

- Row counts differ on 2 of 11 reports: Roe (8212552, 160 vs 186 rows: one
  reader wrote one row per tax lot on attached Merrill statements, the other
  one row per security) and Jenkins (9107156, handwritten, 58 vs 57).
- Most asset-name differences are spelling ("Ell" vs "EII"); owner
  differences are mostly attached spouse accounts with no owner code.
- Value-band agreement is above the 95% bar, but the pilot is not complete:
  groups g02, g03 (both readings) and g15 B are still to read (rate limit).
  The decision to continue waits for those and for a third look at the 171
  disagreements.
- Instruction fix for the next round: one row per security (use the
  subtotal), not per lot; owner `SP` when the attached account is in the
  spouse's name.
