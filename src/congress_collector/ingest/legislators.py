"""Sync `politicians` + `politician_terms` from congress-legislators (T13).

`politician_terms` is fully replaced on every run (delete-all then
re-insert): the YAML files are the single source of truth for term history
and nothing else writes to this table, so there's no reconciliation to do.
`politicians` is upserted by bioguide_id instead, since `filings.bioguide_id`
and `politician_overrides.bioguide_id` reference it by FK.

Writes use Core bulk `insert()`/`on_conflict_do_update()` in small chunks,
each committed immediately, rather than one ORM `session.add()` per row in
a single multi-thousand-row transaction: a first live run of the
naive per-row/single-transaction version was still running after 11+
minutes against Supabase's pooler (cancelled -- see the PR that added this
version for the writeup) even though local fetch+parse alone takes well
under a minute. Keeping each transaction short and each statement a plain
multi-row INSERT (no per-row RETURNING needed, since nothing here uses the
generated term_id afterwards) sidesteps that regardless of which side of
the pooler the slowdown actually came from.
"""

from collections.abc import Iterator, Sequence
from typing import Any

from sqlalchemy import delete, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from congress_collector.db.models import Politician, PoliticianTerm
from congress_collector.db.session import session_scope
from congress_collector.sources.legislators import LegislatorRecord, fetch_all_legislators

CHUNK_SIZE = 500


def sync_legislators() -> tuple[int, int]:
    """Upsert every current+historical legislator. Returns
    (politicians upserted, terms inserted)."""
    records = fetch_all_legislators()
    with session_scope() as session:
        pol_count = _upsert_politicians(session, records)
        term_count = _replace_terms(session, records)
    return pol_count, term_count


def _upsert_politicians(session: Session, records: list[LegislatorRecord]) -> int:
    rows = [
        {
            "bioguide_id": r.bioguide_id,
            "full_name": r.full_name,
            "chamber": r.terms[-1].chamber,
            "party": r.terms[-1].party,
            "state": r.terms[-1].state,
            "district": r.terms[-1].district,
        }
        for r in records
    ]
    for chunk in _chunked(rows, CHUNK_SIZE):
        stmt = pg_insert(Politician).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Politician.bioguide_id],
            set_={
                "full_name": stmt.excluded.full_name,
                "chamber": stmt.excluded.chamber,
                "party": stmt.excluded.party,
                "state": stmt.excluded.state,
                "district": stmt.excluded.district,
            },
        )
        session.execute(stmt)
        session.commit()
    return len(rows)


def _replace_terms(session: Session, records: list[LegislatorRecord]) -> int:
    session.execute(delete(PoliticianTerm))
    session.commit()

    rows = [
        {
            "bioguide_id": r.bioguide_id,
            "chamber": t.chamber,
            "state": t.state,
            "district": t.district,
            "party": t.party,
            "start_date": t.start,
            "end_date": t.end,
        }
        for r in records
        for t in r.terms
    ]
    for chunk in _chunked(rows, CHUNK_SIZE):
        session.execute(insert(PoliticianTerm), chunk)
        session.commit()
    return len(rows)


def _chunked(rows: Sequence[dict[str, Any]], size: int) -> Iterator[Sequence[dict[str, Any]]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def main() -> None:
    pol_count, term_count = sync_legislators()
    print(f"Legislators sync: {pol_count} politician(s), {term_count} term(s).")


if __name__ == "__main__":
    main()
