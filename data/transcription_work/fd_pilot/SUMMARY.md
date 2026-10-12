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

## Final pilot result (2026-10-12, all 20 reports read twice)

| Field | Agreement on matched rows (4,039) |
|---|---|
| asset_name | 98.6% |
| owner | 98.6% |
| value_band | 97.3% |
| income_types | 99.6% |
| income_amount_band | 99.4% |

Row counts differ on 7 of 20 reports, mostly the long brokerage
attachments (Driscoll 3,116 vs 3,117 rows, Roe 271 vs 297, 8208368 227 vs
252: lots vs securities, account headers). `merged_fd.csv` keeps agreed
fields; `disagreements_fd.csv` lists 400 field or row differences (109 value
bands, 138 rows in one reading only) for a third look.

**Decision (owner's rule, 95%+ band agreement): go on** with the remaining
~1,495 paper annual reports, largest filers first. Before that: settle the
lot-vs-security rule for attachments (now in the reader prompt) and give the
attachment-heavy reports a third look.
