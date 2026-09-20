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

- `politicians` — bioguide_id, name, chamber, party, state, district, terms.
- `filings` — filing_id, chamber, filer_name, bioguide_id, filing_type,
  filed_date, `first_seen_at`, `first_seen_precision_s`, format,
  parse_status, source, raw_object_key, raw_sha256, supersedes_filing_id.
- `transactions` — transaction_id, filing_id, row_index, owner,
  asset_description_raw, asset_type, ticker, cik, instrument_id,
  option_type, strike, expiry, underlying_ticker, tx_type, tx_date,
  notification_date, amount_min, amount_max, filing_delay_days, is_current.
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
since nothing here references `public` or Sportlogging's tables.

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

## Data quality

Every run checks for: duplicate transactions, amendments correctly linked to
the original filing (`is_current`), late filings (> 45 days), per-chamber
parse-success rate, share of paper/scanned filings, ticker-linking rate, and
implausible values. A hand-verified set of ~50 filings (House, Senate,
options, amendments, unusual layouts) acts as a regression gate in CI —
parser changes may not lower the score on this set.

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
- [ ] T8 — House: electronic PTR parser + paper/scanned classification.
- [ ] T9 — Senate: agreement acceptance, search, pagination.
- [ ] T10 — Senate: electronic PTR parser.
- [ ] T11 — Collector deployed and running continuously (priority
      milestone — first-seen timestamps start accumulating here).
- [ ] T12 — Telegram notifications for new filings and errors.
- [ ] T13 — Politician linking (congress-legislators, fuzzy match, overrides).
- [ ] T14 — Ticker linking (SEC file, point-in-time changes, overrides).
- [ ] T15 — Options parser (call/put, strike, expiry, underlying).
- [ ] T16 — Amendment linking and `is_current`.
- [ ] T17 — Golden test set (50 filings) + CI regression gate.
- [ ] T18 — Daily data-quality report via Telegram.
- [ ] T19 — Weekly database backup to Storage.
- [ ] T20 — Official backfill (House + Senate, both historical periods).
- [ ] T21 — Community archive import, validation, survivorship-bias
      measurement.
