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
  the GitHub REST API `workflow_dispatch` endpoint is the primary trigger;
  GitHub `schedule` is a fallback only.
- `concurrency: { group: collector, cancel-in-progress: false }` prevents
  overlapping runs.
- Scheduled workflows on public repos are disabled after 60 days without
  repository activity. A weekly heartbeat commit prevents this, with a
  Telegram alert if the heartbeat itself goes silent.
- Runners must be GitHub-hosted (not self-hosted): the Senate site is
  reported to block connections from outside the US, and GitHub-hosted
  runners run in the US.

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
- [ ] T2 — Supabase project (Postgres + Storage), Alembic migrations.
- [ ] T3 — Telegram bot + channels, basic message from CI.
- [ ] T4 — External cron wired to `workflow_dispatch`, fallback schedule,
      concurrency guard.
- [ ] T5 — Heartbeat commit + silence alert.
- [ ] T6 — House: yearly index parsing, new-filing detection, `first_seen_at`.
- [ ] T7 — House: PDF download + archival with hash.
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
