# Owner sample check: batch 4, groups g01-g07

File: `data/transcribed_house_ptrs_2026-10-12.csv` (155 filings, 883 rows, 802 transactions). Sample: 10 filings with transactions, seed 20261012.

| DocID | Filer | Rows | PDF |
|---|---|---|---|
| 8213829 | Mr. Harold Dallas Rogers | 8 | https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2014/8213829.pdf |
| 8213892 | Mr. Michael T. McCaul | 312 | https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2014/8213892.pdf |
| 8215811 | Mr. Harold Dallas Rogers | 15 | https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2014/8215811.pdf |
| 8215974 | Mr. Harold Dallas Rogers | 14 | https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2014/8215974.pdf |
| 8216588 | Mr. Harold Dallas Rogers | 12 | https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2014/8216588.pdf |
| 8220844 | Hon. Harold Dallas Rogers | 3 | https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2025/8220844.pdf |
| 9108560 | Hon. Harold Dallas Rogers | 5 | https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2016/9108560.pdf |
| 9109454 | Hon. Harold Dallas Rogers | 12 | https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2016/9109454.pdf |
| 9111840 | Hon. Harold Dallas Rogers | 3 | https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2017/9111840.pdf |
| 9112635 | Hon. Harold Dallas Rogers | 7 | https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2018/9112635.pdf |

After approval: open a PR with `data/transcribed_house_ptrs_2026-10-12.csv`,
merge, then run the `import-transcribed-ptrs` workflow with that path
(tools/transcription/README.md, step 7). The import skips filings already
parsed.
