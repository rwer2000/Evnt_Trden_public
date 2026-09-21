# congress-collector

Collector for U.S. Congress STOCK Act trading disclosures — House of
Representatives (Clerk) and Senate (eFD). It scrapes, parses, normalizes and
archives periodic transaction reports (PTRs), and records the moment each
filing was first observed.

This repository is **public by design**: GitHub Actions on public repos get
unlimited free minutes, and the underlying disclosure data is public
information anyway. It intentionally contains **no trading or strategy
logic** — signal definitions, backtests, broker integration and execution
live in a separate private repository that consumes this collector's data.

## Why "first seen" matters

Filing dates and even notification dates in the disclosures are not the same
as the moment the data became available to the public. Once a filing has
been observed, that timestamp can never be reconstructed retroactively.
Every day the collector is not running is first-seen data that is lost for
good — so getting this collector live, even in a minimal form, takes
priority over analysis or trading work downstream.

## Scope

In scope:

- House Clerk (`disclosures-clerk.house.gov`) and Senate eFD
  (`efdsearch.senate.gov`) scraping, on a schedule.
- Raw artifact archival (PDF/HTML/ZIP) with content hashing, so parsing can
  always be redone from source.
- Parsing periodic transaction reports into normalized transactions
  (owner, asset, transaction type, dates, amount range).
- Linking filings to politicians (via the `unitedstates/congress-legislators`
  project) and transactions to tickers (via SEC `company_tickers.json`).
- Data quality checks, a small hand-verified golden test set, and a
  Telegram feed for new filings, errors and daily quality summaries.
- Historical backfill of both official archives and community datasets,
  with source attribution.

Out of scope (lives in the private strategy repository instead):

- Signal definitions, scoring, and backtesting.
- Portfolio construction, position sizing, and risk limits.
- Broker integration and order execution.
- Market/price data ingestion used for research (this repo does not need
  prices to do its job).

## Architecture

```
External cron (workflow_dispatch, every 5 min market hours)
        │
        ▼
GitHub Actions (US-based runners — required, Senate site blocks
                non-US traffic)
        │
        ├── House Clerk scraper  ──┐
        └── Senate eFD scraper   ──┤
                                   ▼
                    Supabase Storage (raw PDF/HTML/ZIP + SHA-256)
                                   │
                                   ▼
                    Supabase Postgres (normalized filings & transactions)
                                   │
                                   ▼
                          Telegram (new filings, errors, DQ summary)
```

Scheduling notes:

- GitHub's built-in `schedule` trigger is best-effort and can be delayed by
  tens of minutes to over an hour. An external free cron service calling
  the GitHub REST API `workflow_dispatch` endpoint on `collect.yml` is the
  primary trigger (every 5 min on weekday market hours, every 30 min
  otherwise); the `schedule` trigger in `collect.yml` (hourly, on an odd
  minute) is a fallback only, in case the external cron goes down.
- `concurrency: { group: collector, cancel-in-progress: false }` prevents
  overlapping runs — a trigger that arrives mid-run is queued, not dropped.
- Scheduled workflows on public repos are disabled after 60 days without
  repository activity. `.github/workflows/heartbeat.yml` commits an
  updated `HEARTBEAT.md` weekly to prevent this.
- `.github/workflows/silence-check.yml` runs daily and sends a Telegram
  alert if `collect.yml` hasn't completed successfully in the last 24h
  (checked via the GitHub Actions API, so it works even before T6-T11 give
  the collector anything real to do).
- Runners must be GitHub-hosted (not self-hosted): the Senate site is
  reported to block connections from outside the US, and GitHub-hosted
  runners run in the US.

### Setting up the external cron

1. Create a **fine-grained personal access token**
   (https://github.com/settings/personal-access-tokens/new): resource
   owner yourself, repository access limited to this repo only,
   permissions → Actions → **Read and write**. This token is a secret —
   handle it like the others (never paste it into chat); it's used only by
   the external cron service below, not as a GitHub secret in this repo.
2. Sign up for a free HTTP cron service (e.g. cron-job.org, or any
   equivalent) and create a job that sends:
   - `POST https://api.github.com/repos/rwer2000/Evnt_Trden_public/actions/workflows/collect.yml/dispatches`
   - Headers: `Authorization: Bearer <token>`,
     `Accept: application/vnd.github+json`,
     `Content-Type: application/json`
   - Body: `{"ref":"main"}`
   - Schedule: every 5 minutes, Mon-Fri 07:00-21:00 America/New_York; every
     30 minutes the rest of the time. Most cron services need two separate
     job entries to express that split (one narrow, always-on job would
     also work, just noisier outside market hours).
3. Trigger it once manually (or wait for the first fallback `schedule`
   run) and confirm a run shows up under this repo's **Actions** tab.

## Data model (core tables)

- `politicians` — bioguide_id, name, chamber, party, state, district.
- `politician_terms` — one row per term (chamber, state, district, party,
  start/end date), synced from congress-legislators.
- `politician_overrides` — manual (chamber, filer_name) → bioguide_id
  overrides for filer names the fuzzy matcher can't resolve.
- `filings` — filing_id, chamber, filer_name, bioguide_id, filing_type,
  filed_date, `first_seen_at`, `first_seen_precision_s`, format,
  parse_status, source, raw_object_key, raw_sha256, supersedes_filing_id.
- `transactions` — transaction_id, filing_id, row_index, owner,
  asset_description_raw, asset_type, ticker, cik, instrument_id,
  option_type, strike, expiry, underlying_ticker, tx_type, tx_date,
  notification_date, amount_min, amount_max, filing_delay_days, is_current,
  source_transaction_id (House's amendment-tracking ID, present only on
  rows involved in an amendment, used to link them; always NULL for
  Senate and for ordinary never-amended House rows).
- `instruments`, `ticker_map` (with a validity period, for point-in-time
  ticker resolution), `scrape_runs`, `dq_issues`.

Signals, orders, positions and prices are owned by the private strategy
repository and are not part of this repo's schema.

## Data sources

- House Clerk: https://disclosures-clerk.house.gov
- Senate eFD: https://efdsearch.senate.gov
- Members of Congress metadata:
  https://github.com/unitedstates/congress-legislators
- SEC ticker/CIK mapping: https://www.sec.gov/files/company_tickers.json
- Legislation tracker (Stop Insider Trading Act, H.R. 7008):
  https://www.congress.gov/bill/119th-congress/house-bill/7008

Reference projects consulted during design:

- https://github.com/kimballjh11/congressional-trading-tracker
- https://github.com/StrokeOfLuck/senate-ptr-scraper
- https://github.com/KasperSK-DK/senate-ptr-data

## Database & storage

`congress_collector.db.session.psycopg_url()` rewrites a bare
`postgresql://` `DATABASE_URL` to `postgresql+psycopg://` before handing
it to SQLAlchemy: without the explicit driver, SQLAlchemy defaults to the
(uninstalled) `psycopg2` package instead of the `psycopg` (3.x) one this
repo actually depends on, which fails at connection time. No secret needs
to change for this -- it's handled in code, both here and in
`alembic/env.py`.

`DATABASE_URL` must point at Supabase's connection pooler
(`aws-0-<region>.pooler.supabase.com`), not the direct `db.<ref>.supabase.co`
host: the direct host resolves IPv6-only, which GitHub-hosted runners can't
reach. The pooler username is `postgres.<project-ref>` (not just `postgres`).
Because the pooler's transaction mode can hand a pooled connection to a
different session between statements, `get_engine()` and `alembic/env.py`
both pass `connect_args={"prepare_threshold": None}` to disable psycopg's
server-side prepared-statement cache -- otherwise repeated inserts raise
`DuplicatePreparedStatement`.

Postgres and Storage live in a shared Supabase project (`Sportlogging`,
`eu-central-1`) rather than a dedicated one — the account's free tier
allows only 2 active free projects, both already in use. Isolation from
the unrelated Sportlogging app is done at the schema/bucket level, not the
project level:

- All tables from this repo live in the `congress` Postgres schema, never
  `public`.
- A dedicated `congress_app` Postgres role can only read/write the
  `congress` schema; it has no grants on `public` (Sportlogging's tables).
- Raw filings are archived in a private Storage bucket, `congress-raw`,
  separate from any Sportlogging bucket.

Migrating to a dedicated project later (a different Supabase account, or
once an existing free project's slot frees up) is a schema dump/restore
(`pg_dump --schema=congress` / restore) plus copying the Storage bucket's
objects — no application code changes needed beyond the connection string,
since nothing here references `public` or Sportlogging's tables. T19's
weekly backup (below) already produces a ready-made dump for this.

### Weekly database backup (T19)

`congress_collector.ops.db_backup` runs `pg_dump --schema=congress
--no-owner --no-privileges` (the same command the migration note above
describes), gzip-compresses it, and uploads it to a separate private
bucket, `congress-backups`, keyed by date
(`congress_YYYYMMDD.sql.gz`). Runs weekly via
`.github/workflows/db-backup.yml` (Sunday 03:00 UTC), with a Telegram
confirmation on success. `--no-owner --no-privileges` drops
role-specific `ALTER TABLE OWNER TO` / `GRANT` statements, since a
future restore target's role names (a different Supabase project,
someone's local Postgres) aren't guaranteed to match this project's
`congress_app` role — the schema and data restore cleanly either way.
`pg_dump` is a subprocess, not something unit-testable without a real
Postgres server, so this is verified live against production like every
other DB-touching module here; only the pure date-stamped object-key
logic is unit tested (`tests/test_db_backup.py`). No automatic pruning
of old backups yet -- a known gap, left for whenever storage cost or
count actually becomes worth managing.

Migrations are managed with Alembic (`alembic/`), targeting the tables
this repo owns (see the data model above). Because the schema is shared
with `congress-strategy`, each repo keeps its own Alembic version table
(`congress.alembic_version_collector` here) so the two migration
histories can't collide. The very first revision
(`202609190001_core_schema`) was applied directly via the Supabase
management API before this repo's CI had `DATABASE_URL` available; run
`alembic stamp head` once against the real database to sync Alembic's
bookkeeping, then use `alembic upgrade head` normally for everything
after.

Required environment variables are documented in `.env.example`.

## Notifications

`congress_collector.notify.telegram.send_message()` posts to a single
Telegram group chat over the Bot API directly (no bot framework — this
repo only ever sends, never receives). Messages are prefixed by category
(`filing`, `system`) rather than split across separate Telegram chats, to
keep the setup to one bot/one chat; that can be split later if it gets
noisy. Trigger the `Telegram smoke test` workflow (`workflow_dispatch`) to
confirm `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` are wired up correctly.

## House Clerk index sync (T6)

`congress_collector.ingest.house.sync_house_index()` fetches the yearly
index ZIP (`https://disclosures-clerk.house.gov/public_disc/financial-pdfs/
{year}FD.zip` — confirmed live from a GitHub Actions runner, since this
sandbox's own egress proxy blocks the domain), parses the `<Member>`
records in its XML, and inserts any `DocID` not already in `filings` with
`first_seen_at` set to the moment it was observed. Every run also records
a `scrape_runs` row, success or failure, which `silence-check.yml` reads.

Filing-type codes (`P`, `C`, `O`, `W`, `X`, `D`, ...) are stored as-is
without filtering — `format` is inserted as `'unknown'` since classifying
electronic vs. paper needs the PDF itself (T7/T8). Run it directly with
`uv run python -m congress_collector.ingest.house`.

## House PDF archive (T7)

`congress_collector.ingest.house_pdfs.archive_pending_house_pdfs()` picks
up to 50 House filings per run with `raw_object_key IS NULL`, downloads
the PDF, and uploads it to the `congress-raw` bucket at
`house/{year}/{doc_id}.pdf` via the official `supabase` client (used
instead of hand-rolling the Storage REST API, since its upsert/auth
semantics are easy to get subtly wrong). `raw_object_key` and
`raw_sha256` are then recorded on the `filings` row; `format` stays
`'unknown'` (classification needs T8).

Periodic transaction reports (`FilingType = 'P'`) are served from a
different path than every other filing type -- also confirmed live via a
GitHub Actions runner:

- PTRs: `public_disc/ptr-pdfs/{year}/{doc_id}.pdf`
- everything else: `public_disc/financial-pdfs/{year}/{doc_id}.pdf`

A filing whose PDF fetch fails (404, timeout, ...) is simply left pending
and retried on the next `collect` run. Run it directly with
`uv run python -m congress_collector.ingest.house_pdfs`.

## House PTR parser (T8)

`congress_collector.ingest.house_ptrs.parse_pending_house_ptrs()` reads
each archived-but-unclassified House PTR back from `congress-raw` (T7's
copy, not a re-fetch), and either marks it `format = 'scanned'` /
`parse_status = 'paper_deferred'` (no extractable text -- a paper filing)
or parses it into `transactions` rows and marks it `format = 'electronic'`
/ `parse_status = 'parsed'`.

The parser (`congress_collector.parsers.house_ptr`) works from
`extract_words()` positions rather than pdfplumber's `extract_tables()`,
which turned out to merge the form's garbled annotation lines
("Filing Status:", "Subholding Of:", "Description:", ...) into the
transaction cells -- confirmed against several real PTR PDFs fetched from
a GitHub Actions runner. The form uses a fixed column template (verified
stable across filings), which is what makes reconstructing wrapped rows
by x-position reliable. Known gap: the "Cap. Gains > $200?" column is a
checkbox rendered as vector graphics, not text, so it isn't captured
(`transactions` has no column for it either). A transaction row whose
type code isn't recognized is skipped and logged as a `dq_issues` row
rather than guessed at.

Run it directly with `uv run python -m congress_collector.ingest.house_ptrs`.

## House options parser (T15)

The House form itself never gives option_type/strike/expiry as columns --
that detail only shows up in a free-text "Description:" annotation, one of
the labels `house_ptr.py` otherwise treats as noise and discards (see T8
above). For a row whose ticker/type annotation says `[OP]`, that one label
is captured and parsed instead. Confirmed live against real filings that
filers write it in at least two styles:

- Structured: `"Call options; Strike price $320; Expires 06/18/2026"` --
  yields `option_type`, `strike`, and `expiry` all at once.
- Informal: `"10 puts at $11.80"` -- the dollar figure is the premium
  paid per contract, not a strike price, so only `option_type` is
  extracted from this style; guessing a strike from the premium would be
  wrong, so `strike`/`expiry` stay `NULL` rather than a fabricated value.

Both chambers already record the underlying stock's ticker in the same
`ticker` column used for plain stock rows (House's `(TICKER) [OP]`
annotation and Senate's dedicated Ticker column both refer to the
underlying, not a separate option symbol -- neither chamber uses OCC-style
option symbols), so there's no separate `underlying_ticker` to populate;
`transactions.underlying_ticker` stays unused, matching Senate's T10
behavior.

Because a filing only ever gets parsed once (`parse_pending_house_ptrs`
only looks at `format = 'unknown'`), this improvement doesn't reach
filings parsed before it shipped -- see `backfill_house_reparse` below,
which covers this alongside T16's `source_transaction_id`.

## Senate eFD index sync (T9)

`congress_collector.ingest.senate.sync_senate_ptr_index()` accepts
efdsearch.senate.gov's search-prohibition agreement (confirmed live from
a GitHub Actions runner: `GET /search/home/` for a CSRF cookie, `POST`
the same URL with `prohibition_agreement=1`, which sets a `sessionid`
cookie), then pages through `POST /search/report/data/` (a DataTables
server-side endpoint) for report type `11` -- confirmed to mean Periodic
Transaction Report by searching for it and getting back only PTR
results -- over the last 14 days (per the plan; backfill uses a
per-month window instead, added with T20).

Unlike House, the search result's link path already says whether a
filing is electronic (`/search/view/ptr/<uuid>/`, an HTML page) or paper
(`/search/view/paper/<uuid>/`), so `format`/`parse_status` are set
immediately here rather than needing a separate classification pass. The
report UUID in that path becomes the filing_id (`senate:<uuid>`).

Run it directly with `uv run python -m congress_collector.ingest.senate`.

## Senate PTR parser (T10)

`congress_collector.ingest.senate_ptrs.parse_pending_senate_ptrs()` fetches
each electronic Senate PTR still `parse_status = 'pending'`, archives the
raw HTML to `congress-raw` (`senate/{report_uuid}.html`, with a hash --
Senate doesn't have a separate archive task in the plan the way House's
T7 does, so this folds it into the same fetch since the content is
already in hand), and parses it into `transactions` rows.

The page is a plain, well-formed HTML `<table>` (confirmed live from a
GitHub Actions runner) -- much simpler than House's PDFs, no positional
reconstruction needed. Option transactions embed their details in the
Asset Name cell ("Option Type: Call Strike price:$75.00
Expires:2026-08-21"); `congress_collector.parsers.senate_ptr` pulls that
out into `option_type`/`strike`/`expiry` rather than leaving it
duplicated in the free-text description. Known gap: the site exposes no
per-transaction notification date (only the filing-level submitted date,
already on `filings`), so `notification_date` is always `NULL` here.

Run it directly with `uv run python -m congress_collector.ingest.senate_ptrs`.

## Politician linking (T13)

`congress_collector.ingest.legislators.sync_legislators()` fetches the
current + historical member lists from
[unitedstates/congress-legislators](https://github.com/unitedstates/congress-legislators)
and upserts `politicians` (one row per bioguide ID) and `politician_terms`
(one row per term; fully replaced on each sync, since the YAML files are
the sole source of truth for term history). Runs weekly via
`.github/workflows/legislators.yml`, separate from `collect.yml`'s 5-minute
cadence since congress membership barely changes and the historical file
alone is ~9MB.

`congress_collector.ingest.politician_links.link_pending_filings()` then
fills in `filings.bioguide_id` for filings that don't have one yet, as the
last step of every `collect.yml` run:

1. Check `politician_overrides` for an exact (chamber, normalized
   filer_name) match first.
2. Otherwise, fuzzy-match (`rapidfuzz`, `parsers/politician_match.py`)
   against politicians whose term for the filing's chamber was active on
   its filed date -- narrowing by chamber + term period first means the
   name match alone usually only has to disambiguate a handful of
   candidates, not the full ~13k-row history.
3. A clear top match (score ≥ 92, or ≥ 80 with no close runner-up) sets
   `bioguide_id`; anything else -- no match, or two similarly-scoring
   candidates -- gets a `dq_issues` row (`politician_match_unmatched` /
   `politician_match_ambiguous`) instead of a guess, for manual review or a
   new `politician_overrides` entry.

State/district aren't used as a matching signal: `filings` doesn't carry
them (House's index XML has `StateDst`, but it's discarded before
persistence today), so chamber + term-period overlap is the only
narrowing besides the name itself. In practice this is enough --
same-chamber, same-era name collisions are rare, and the override table
exists for exactly that residual case.

## Ticker linking (T14)

`congress_collector.ingest.tickers.link_pending_transactions()` fills in
`transactions.instrument_id` (and, when the parser didn't extract one,
`transactions.ticker`) as the last step of every `collect.yml` run:

1. Check `data/ticker_overrides.csv` (columns: `match_type` — `ticker` or
   `description` —, `match_value`, `ticker`, `cik`, `reason`) for an exact
   match first.
2. Otherwise, look up the parser-extracted `ticker` directly against SEC's
   ticker/CIK/company-name reference data.
3. Otherwise, fuzzy-match `asset_description_raw` against SEC company
   names (`parsers/ticker_match.py`, `rapidfuzz`) for transactions the
   parser couldn't extract a clean ticker from at all.

`instruments`/`ticker_map` rows are created on demand, one per distinct
CIK actually seen in a transaction — this isn't meant to mirror SEC's
full ~10k-company universe. Unmatched transactions get a `dq_issues` row
(`ticker_match_unmatched`), deduped the same way T13's `politician_links`
is, so a transaction that structurally can't match (a municipal bond, a
Treasury note, a private placement) doesn't get re-flagged every 5-minute
run forever.

**The SEC reference data is vendored, not fetched live.** SEC blocks
automated fetches of `company_tickers.json` from cloud/CI IP ranges
outright — confirmed via a throwaway diagnostic workflow on GitHub
Actions: five attempts (a plain fetch, a SEC-compliant "Name email"
User-Agent, a different SEC subdomain, a fetch after a 20s delay) all got
a 403, either "Request Rate Threshold Exceeded" or "Your Request
Originates from an Undeclared Automated Tool". This collector's own dev
sandbox gets the same block. So `data/sec_company_tickers.json` is a
snapshot, downloaded manually from
[www.sec.gov/files/company_tickers.json](https://www.sec.gov/files/company_tickers.json)
in a regular browser and committed to the repo, refreshed every few
months — tickers and CIKs change slowly enough that this is a reasonable
trade-off given the alternative is no automated access at all.

The fuzzy company-name fallback is deliberately conservative (high
threshold, `token_sort_ratio` rather than `token_set_ratio`) after an
earlier version confidently mismatched real filings against the vendored
data — e.g. "Invesco QQQ" scored a perfect 100 against "Invesco Ltd.", an
unrelated company that merely shares one word, because token_set_ratio
scores a subset match at 100 regardless of what else is in either string.
A transaction sitting in the review queue is a far better failure mode
than a silently wrong instrument link, so unresolved fuzzy matches stay
unresolved rather than taking the best available guess.

Point-in-time ticker changes aren't tracked: `company_tickers.json` is a
current-day snapshot with no history, so every `ticker_map` row this step
creates gets the same fixed `valid_from` (the plan's furthest-back
backfill period) and an open `valid_to`. A transaction whose ticker has
since changed (a rename, not merely a new listing) fails to match today's
snapshot and lands in the review queue rather than being mislinked to
whatever now holds that ticker.

## Amendment linking (T16)

`congress_collector.ingest.amendments.link_amendments()` keeps
`transactions.is_current` accurate when a filer corrects an earlier PTR,
as the last step of every `collect.yml` run.

House PTRs have a `source_transaction_id` (the form's leftmost "ID"
column, a 10-digit number) that stays the same across an original filing
and any later filing that amends that specific transaction — confirmed
live against a real "Filing Status: Amended" row during T16 (that label,
like `Description:`, is otherwise treated as noise; see T8/T15). It
isn't on every row: verified against a production backfill that it's
present only on rows actually involved in an amendment (~17 of ~3200
real House transactions) and absent on an ordinary, never-amended one,
so this step only ever has a small number of candidates to look at.
Whenever the same `source_transaction_id` appears on transactions from
more than one filing, only the one from the most-recently-filed filing
keeps `is_current = true`; the rest get `is_current = false` but stay in
the table for audit/history — the plan's own wording is "only the most
recent counts". The amending filing's `supersedes_filing_id` is set to
the earliest filing in the group too, best-effort.

Senate has no equivalent identifier, so `source_transaction_id` stays
`NULL` there and this step never touches Senate rows.

**Known gap**: this only finds an amendment's original when both filings
are already in `filings` — and today that's only ever the current
calendar year's House index (`sync_house_index()`, T6), since the
official backfill (T20/T21) hasn't run yet. An amendment whose original
was filed the prior year won't resolve until that backfill lands; nothing
breaks in the meantime; the amended transaction just stands alone as its
own `is_current = true` row (already the column's default) until a later
run discovers the match.

**Backfill**: `source_transaction_id` hits the same "a filing only ever
gets parsed once" gap as T15's option fields (see T15 above) --
`congress_collector.ingest.backfill_house_reparse` re-parses just the
PDFs behind transactions still missing either field and fills them in in
place. Not part of `collect.yml`'s regular cadence; run manually via the
`backfill-house-reparse` workflow (`workflow_dispatch` only) or `uv run
python -m congress_collector.ingest.backfill_house_reparse`. Safe to
re-run: a transaction that already has both fields is left untouched.

## Golden test set (T17)

`tests/golden/` is a CI regression gate for the House and Senate PTR
parsers, built from 52 real filings pulled from production (this
sandbox can't reach Supabase Storage's HTTP API directly, so the raw
bytes were fetched via a throwaway GitHub Actions workflow and pushed
to a data branch instead). The set spans every House `asset_type` seen
in real data -- including ones with no ticker, like government
securities and private holdings -- both option description styles
(T15), an amendment pair (T16), partial sales, exchanges, all owner
codes, and Senate stock/option/multi-transaction filings.

Since parsing is deterministic, `tests/test_golden_set.py` enforces
"score must not decrease" as an exact-match snapshot test against
`tests/golden/manifest.json` rather than a fuzzy score: any parser
change that alters the output for one of these real filings fails CI.
A deliberate improvement regenerates the manifest in the same PR (`uv
run python tests/golden/regenerate.py`, review the diff by hand before
committing).

Building this set surfaced a real parser bug: `asset_type` extraction
was coupled to a ticker being present in `(TICKER) [TYPE]` form, so
anything without a market ticker -- government securities, private
holdings, crypto, and any description with a stray extra paren from
the filer -- fell through to `asset_type = None` entirely, even though
the bracketed type code was right there in the text. Fixed by falling
back to a type-only match when the ticker+type regex doesn't match.

## Official backfill (T20)

`congress_collector.ingest.official_backfill.backfill_all()` backfills
both chambers' filing indices back to 2012 -- the STOCK Act's electronic
PTR era, matching T14's `DEFAULT_VALID_FROM` -- via
`ingest.house.backfill_house_year(year)` (looped per year, since the
Clerk index is one ZIP per year) and
`ingest.senate.backfill_senate_since(date(2012, 1, 1))` (one paginated
fetch, committed in chunks of 500). Run manually via the
`backfill-official` workflow (`workflow_dispatch` only) -- a one-time
(or rare) operation, not part of `collect.yml`'s regular cadence.

This only backfills the `filings` index rows themselves. The rest of the
pipeline (`house_pdfs`, `house_ptrs`, `senate_ptrs`, `politician_links`,
`tickers`, `amendments`) already works as a generic backlog over every
filing regardless of age -- each step selects on a status column
(`format`, `parse_status`, `instrument_id IS NULL`, ...), never a date
range -- so once the index rows land, the regular `collect.yml` cadence
picks up archiving/parsing/linking them over subsequent runs like any
other pending filing.

**The one thing this had to get right, and the live sync steps don't
have to think about**: `first_seen_at` is supposed to mean "the moment
the collector observed this filing" (see "Why first seen matters"
above) -- for a filing backfilled in 2026 that was actually filed in
2013, `first_seen_at = now()` would be a lie, and a damaging one, since
it would make a 13-year-late discovery look like a 5-minute one to any
downstream timing analysis. `ingest.house.backfill_first_seen` /
`ingest.senate.backfill_first_seen` derive `first_seen_at` from each
entry's own filed/submitted date instead (`first_seen_precision_s =
86400`, since that date is day-granularity) -- the live sync functions
(`sync_house_index`, `sync_senate_ptr_index`) are unchanged and still
record real `first_seen_at = now()` with the live precision. The one
edge case with no filed date at all still falls back to `now()`, but
flagged with a ~10-year `first_seen_precision_s` sentinel so it reads as
"meaningless for latency analysis" rather than silently understating
the real gap.

Idempotent and resumable like every other sync step here: new-ness is
decided by `filing_id`, so a failed or interrupted backfill run can just
be re-triggered and picks up where it left off.

## Data quality

`congress_collector.ops.dq_report` (T18) computes a health snapshot of the
whole dataset -- duplicate transactions, amendments correctly linked to the
original filing (`is_current`), late filings (> 45 days), per-chamber
parse-success rate, share of paper/scanned filings, ticker-linking rate, and
implausible values -- and sends it to Telegram once a day
(`.github/workflows/dq-report.yml`, 12:30 UTC, separately from `collect.yml`'s
5-minute cadence so routine variance doesn't spam the channel). The
DB-querying part (`compute_metrics`) is verified live against production
rather than unit tested (no database in CI); the message formatting
(`format_report`) is pure and covered by `tests/test_dq_report.py`.

"Late filing" uses each transaction's own `notification_date` where the
parser captured one (House) and falls back to the filing's `filed_date`
otherwise (Senate, which only exposes a filing-level submitted date -- see
T10). "Duplicate transaction" groups by filing + owner + description + type +
date + amount range, deliberately keying on the full `asset_description_raw`
rather than `ticker`/`asset_type` alone -- an earlier version of this check
keyed on ticker+type and flagged a member's 20 distinct US Treasury notes
(same day, same amount bracket, no ticker -- see T17) as one giant duplicate
group, since notes with different maturities share every other column.
"Implausible values" flags amount ranges with min > max, negative amounts, a
non-positive option strike, a transaction date in the future, and a
notification recorded *before* the transaction it discloses -- live
verification against production found 8 real rows tripping that last check
(mostly private-placement rows where notification_date is a few days ahead
of tx_date), which is the report doing its job, not a bug in the check.

A hand-verified set of 52 real filings (House, Senate, options, amendments,
unusual layouts) acts as a regression gate in CI (T17) -- parser changes may
not lower the score on this set.

## Legal note

This collector is built for personal research and trading use only.
Commercial use of congressional financial disclosure data is restricted by
the STOCK Act except for legitimate news reporting. Do not redistribute the
processed data commercially.

## Conventions

- Code, commit messages, and documentation are in English.
- Python 3.12, managed with [uv](https://docs.astral.sh/uv/).
- Linting/formatting: `ruff`. Type checking: `mypy --strict`. Tests:
  `pytest`. All three run in CI on every push and pull request.

## Development

```bash
uv sync --all-extras --dev
uv run ruff check .
uv run mypy
uv run pytest
```

## Roadmap

Tracked against the shared plan's task list (collector-relevant tasks only;
full plan, including analysis and trading, lives in the private strategy
repo):

- [x] T1 — Project foundation: repo, Python project, ruff/mypy/pytest, CI.
- [x] T2 — Supabase (Postgres + Storage), Alembic migrations.
- [x] T3 — Telegram bot + channels, basic message from CI.
- [x] T4 — External cron wired to `workflow_dispatch`, fallback schedule,
      concurrency guard. (`collect.yml` is ready; setting up the external
      cron account/token is a manual step, see above.)
- [x] T5 — Heartbeat commit + silence alert.
- [x] T6 — House: yearly index parsing, new-filing detection, `first_seen_at`.
- [x] T7 — House: PDF download + archival with hash.
- [x] T8 — House: electronic PTR parser + paper/scanned classification.
- [x] T9 — Senate: agreement acceptance, search, pagination.
- [x] T10 — Senate: electronic PTR parser.
- [x] T11 — Collector deployed and running continuously (priority
      milestone — first-seen timestamps start accumulating here).
- [ ] T12 — Telegram notifications for new filings and errors.
- [x] T13 — Politician linking (congress-legislators, fuzzy match, overrides).
- [x] T14 — Ticker linking (SEC file, point-in-time changes, overrides).
- [x] T15 — Options parser (call/put, strike, expiry, underlying).
- [x] T16 — Amendment linking and `is_current`.
- [x] T17 — Golden test set (50 filings) + CI regression gate.
- [x] T18 — Daily data-quality report via Telegram.
- [x] T19 — Weekly database backup to Storage.
- [x] T20 — Official backfill (House + Senate, both historical periods).
- [ ] T21 — Community archive import, validation, survivorship-bias
      measurement.
