# PTR batch 4: House filers whose PTRs are all on paper

Prepared 2026-10-11 (queue item E3). Procedure: `tools/transcription/README.md`;
reader prompt: `tools/transcription/INSTRUCTIONS.md` with `<PAGES_DIR>` =
`/tmp/claude-0/-home-user/78448495-d1e0-50f1-a203-938f4f1d75f9/scratchpad/ptr4/pages`.
The page paths in the group files are absolute paths into that scratchpad; a new
session must re-download and re-render (step 2 of the procedure) into its own
directory and rewrite the paths.

## Method

- Source: `congress.filings` via PostgREST GET (2026-10-11), House rows with
  `filing_type = 'P'` (PTR).
- Filer key: `bioguide_id`; for unlinked rows, the name without honorifics,
  suffixes and quoted nicknames (first + last token), mapped to a bioguide id when
  exactly one linked filer has that name. Name variants ("Hon." / "Mr.") merge.
- All on paper: the filer has at least one `scanned` / `paper_deferred` PTR and no
  `electronic` PTR under any variant. Filers with electronic PTRs belong to batch 3
  and are excluded. "Hon. James M. Costa" (unlinked) is excluded as Jim Costa
  (C001059), who files electronically.
- Filings already in `data/transcribed_house_ptrs_*.csv` are excluded (none of
  them belonged to these filers).
- Order: number of paper PTRs, descending.
- Result: 83 filers, 1,806 filings. The strategy repo's
  status table says 107 / 1,976; that count was not reproducible from the live
  table with this definition (grouping by raw filer name gives 123 / 1,872, and
  it wrongly counts name variants of electronic filers such as Ann Wagner).
- PDFs: `https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/<year>/<DocID>.pdf`,
  year = filed year (all 306 found there), rendered with `pdftoppm -r 150 -png`.
- Groups: filings in filer order, then filed date; a new group starts at 25
  filings or when the next filing would push it past 40 pages.

## Groups prepared

Filers in the prepared groups: Harold Dallas Rogers (154 filings) and Michael T.
McCaul (M001157, 152 filings): 306 filings, 1455 pages.

| Group | Filings | Pages | Filer(s) | Read A | Read B |
|---|---|---|---|---|---|
| g01 | 16 | 37 | Harold Dallas Rogers | - | - |
| g02 | 19 | 40 | Harold Dallas Rogers | - | - |
| g03 | 25 | 29 | Harold Dallas Rogers | - | - |
| g04 | 25 | 27 | Harold Dallas Rogers | - | - |
| g05 | 25 | 29 | Harold Dallas Rogers | - | - |
| g06 | 25 | 26 | Harold Dallas Rogers | - | - |
| g07 | 20 | 35 | Harold Dallas Rogers, Michael T. McCaul | - | - |
| g08 | 3 | 34 | Michael T. McCaul | - | - |
| g09 | 4 | 35 | Michael T. McCaul | - | - |
| g10 | 4 | 32 | Michael T. McCaul | - | - |
| g11 | 4 | 38 | Michael T. McCaul | - | - |
| g12 | 4 | 36 | Michael T. McCaul | - | - |
| g13 | 4 | 40 | Michael T. McCaul | - | - |
| g14 | 3 | 32 | Michael T. McCaul | - | - |
| g15 | 3 | 34 | Michael T. McCaul | - | - |
| g16 | 3 | 34 | Michael T. McCaul | - | - |
| g17 | 3 | 32 | Michael T. McCaul | - | - |
| g18 | 3 | 31 | Michael T. McCaul | - | - |
| g19 | 3 | 32 | Michael T. McCaul | - | - |
| g20 | 4 | 36 | Michael T. McCaul | - | - |
| g21 | 4 | 34 | Michael T. McCaul | - | - |
| g22 | 4 | 38 | Michael T. McCaul | - | - |
| g23 | 3 | 32 | Michael T. McCaul | - | - |
| g24 | 4 | 40 | Michael T. McCaul | - | - |
| g25 | 3 | 30 | Michael T. McCaul | - | - |
| g26 | 4 | 36 | Michael T. McCaul | - | - |
| g27 | 3 | 31 | Michael T. McCaul | - | - |
| g28 | 4 | 40 | Michael T. McCaul | - | - |
| g29 | 4 | 40 | Michael T. McCaul | - | - |
| g30 | 6 | 31 | Michael T. McCaul | - | - |
| g31 | 6 | 37 | Michael T. McCaul | - | - |
| g32 | 6 | 31 | Michael T. McCaul | - | - |
| g33 | 3 | 35 | Michael T. McCaul | - | - |
| g34 | 6 | 37 | Michael T. McCaul | - | - |
| g35 | 6 | 40 | Michael T. McCaul | - | - |
| g36 | 6 | 36 | Michael T. McCaul | - | - |
| g37 | 4 | 38 | Michael T. McCaul | - | - |
| g38 | 5 | 40 | Michael T. McCaul | - | - |
| g39 | 5 | 30 | Michael T. McCaul | - | - |
| g40 | 6 | 36 | Michael T. McCaul | - | - |
| g41 | 7 | 40 | Michael T. McCaul | - | - |
| g42 | 7 | 34 | Michael T. McCaul | - | - |

## Groups read

None yet.

## Filer order (all filers, paper PTRs to transcribe)

| # | Filer key | Filer name | Filings | In prepared groups |
|---|---|---|---|---|
| 1 | name:harold rogers | Hon. Harold Dallas Rogers | 154 | yes |
| 2 | M001157 | Hon. Michael T. McCaul | 152 | yes |
| 3 | D000620 | Hon. John K. Delaney | 120 |  |
| 4 | K000389 | Hon. Rohit Khanna | 120 |  |
| 5 | R000586 | Hon. James B. Renacci | 117 |  |
| 6 | S001180 | Hon. Kurt Schrader | 109 |  |
| 7 | F000459 | Hon. Charles J. "Chuck" Fleischmann | 93 |  |
| 8 | B001273 | Hon. Diane Black | 85 |  |
| 9 | R000582 | Hon. David P. Roe | 82 |  |
| 10 | M001158 | Hon. Kenny Marchant | 80 |  |
| 11 | L000564 | Hon. Doug Lamborn | 72 |  |
| 12 | P000598 | Hon. Jared Polis | 72 |  |
| 13 | F000372 | Hon. Rodney P. Frelinghuysen | 71 |  |
| 14 | U000031 | Hon. Fred Upton | 58 |  |
| 15 | R000607 | Hon. Francis Rooney | 48 |  |
| 16 | L000576 | Hon. Billy Long | 32 |  |
| 17 | C001092 | Hon. Chris Collins | 31 |  |
| 18 | K000379 | Hon. Joseph P. Kennedy III | 27 |  |
| 19 | H001074 | Hon. Trey Hollingsworth | 24 |  |
| 20 | C001102 | Hon. Curtis J. Clawson | 20 |  |
| 21 | B001257 | Hon. Gus M. Bilirakis | 17 |  |
| 22 | W000829 | Tony Wied | 16 |  |
| 23 | G000556 | Mr. Alan Grayson | 14 |  |
| 24 | P000591 | Hon. Tom Price | 12 |  |
| 25 | C001053 | Hon. Tom Cole | 11 |  |
| 26 | C000071 | Mr. Dave Camp | 11 |  |
| 27 | M000317 | Hon. Nicole Malliotakis | 10 |  |
| 28 | S000244 | Hon. F. James Sensenbrenner Jr. | 9 |  |
| 29 | P000594 | Mr. Erik Paulsen | 9 |  |
| 30 | T000468 | Hon. Dina Titus | 8 |  |
| 31 | S001187 | Hon. Steve Stivers | 8 |  |
| 32 | C000556 | Hon. Howard Coble | 7 |  |
| 33 | Y000065 | Hon. Ted S. Yoho | 7 |  |
| 34 | D000533 | Hon. John J. Duncan Jr. | 6 |  |
| 35 | C001047 | Mrs. Shelley Moore Capito | 6 |  |
| 36 | G000289 | Hon. Bob Goodlatte | 5 |  |
| 37 | D000604 | Hon. Charles W. Dent | 5 |  |
| 38 | S001193 | Hon. Eric Swalwell | 4 |  |
| 39 | name:garland barr | Hon. Garland "Andy" Barr | 4 |  |
| 40 | G000581 | Hon. Vicente Gonzalez | 4 |  |
| 41 | H001064 | Mr. Denny Heck | 4 |  |
| 42 | C001048 | Hon. John Abney Culberson | 3 |  |
| 43 | S001224 | Hon. Keith Alan Self | 3 |  |
| 44 | L000567 | Hon. Leonard Lance | 3 |  |
| 45 | C001045 | Hon. Ander Crenshaw | 2 |  |
| 46 | name:angela craig | Hon. Angela Dawn Craig | 2 |  |
| 47 | L000569 | Hon. Blaine Luetkemeyer | 2 |  |
| 48 | B001271 | Hon. Dan Benishek | 2 |  |
| 49 | J000296 | Hon. David W. Jolly | 2 |  |
| 50 | B001281 | Hon. Joyce Beatty | 2 |  |
| 51 | name:melvin watt | Hon. Melvin L. Watt | 2 |  |
| 52 | D000613 | Hon. Robert James Dold | 2 |  |
| 53 | T000470 | Hon. Scott R. Tipton | 2 |  |
| 54 | H001060 | Mr. Robert Hurt | 2 |  |
| 55 | P000265 | Mr. Thomas E. Petri | 2 |  |
| 56 | R000592 | Mr. Todd Rokita | 2 |  |
| 57 | R000596 | Mr. Trey Radel | 2 |  |
| 58 | M000309 | Mrs. Carolyn McCarthy | 2 |  |
| 59 | name:ada henriquez | Ada Norah Henriquez | 1 |  |
| 60 | S001165 | Hon. Albio Sires | 1 |  |
| 61 | H001058 | Hon. Bill Huizenga | 1 |  |
| 62 | G000558 | Hon. Brett Guthrie | 1 |  |
| 63 | R000588 | Hon. Cedric L. Richmond | 1 |  |
| 64 | B001316 | Hon. Eric Burlison | 1 |  |
| 65 | M001139 | Hon. Gary G. Miller | 1 |  |
| 66 | W000791 | Hon. Greg Walden | 1 |  |
| 67 | H001088 | Hon. James Hagedorn | 1 |  |
| 68 | S001168 | Hon. John P. Sarbanes | 1 |  |
| 69 | name:john graves | Hon. John Thomas Graves Jr. | 1 |  |
| 70 | T000473 | Hon. Kyle Mark Takai | 1 |  |
| 71 | S001204 | Hon. Michael Fq San Nicolas | 1 |  |
| 72 | D000191 | Hon. Peter A. DeFazio | 1 |  |
| 73 | A000374 | Hon. Ralph Lee Abraham | 1 |  |
| 74 | D000629 | Hon. Sharice Davids | 1 |  |
| 75 | name:thomas emmer | Hon. Thomas Earl Emmer Jr | 1 |  |
| 76 | C001049 | Hon. Wm. Lacy Clay | 1 |  |
| 77 | H001052 | Mr. Andy Harris | 1 |  |
| 78 | L000565 | Mr. David Loebsack | 1 |  |
| 79 | T000266 | Mr. John F. Tierney | 1 |  |
| 80 | S001188 | Mr. Marlin A. Stutzman | 1 |  |
| 81 | C001090 | Mr. Matt Cartwright | 1 |  |
| 82 | S001145 | Ms. Janice D. Schakowsky | 1 |  |
| 83 | name:richard reisdorf | Richard B. Reisdorf | 1 |  |
