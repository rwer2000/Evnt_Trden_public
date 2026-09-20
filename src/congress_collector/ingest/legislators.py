"""Sync `politicians` + `politician_terms` from congress-legislators (T13).

`politician_terms` is fully replaced on every run (delete-all then
re-insert): the YAML files are the single source of truth for term history
and nothing else writes to this table, so there's no reconciliation to do.
`politicians` is upserted by bioguide_id instead, since `filings.bioguide_id`
and `politician_overrides.bioguide_id` reference it by FK.
"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from congress_collector.db.models import Politician, PoliticianTerm
from congress_collector.db.session import session_scope
from congress_collector.sources.legislators import LegislatorRecord, fetch_all_legislators


def sync_legislators() -> tuple[int, int]:
    """Upsert every current+historical legislator. Returns
    (politicians upserted, terms inserted)."""
    records = fetch_all_legislators()
    with session_scope() as session:
        pol_count = _upsert_politicians(session, records)
        term_count = _replace_terms(session, records)
    return pol_count, term_count


def _upsert_politicians(session: Session, records: list[LegislatorRecord]) -> int:
    existing = {p.bioguide_id: p for p in session.scalars(select(Politician))}
    count = 0
    for record in records:
        latest_term = record.terms[-1]
        politician = existing.get(record.bioguide_id)
        if politician is None:
            politician = Politician(bioguide_id=record.bioguide_id, full_name=record.full_name)
            session.add(politician)
        politician.full_name = record.full_name
        politician.chamber = latest_term.chamber
        politician.party = latest_term.party
        politician.state = latest_term.state
        politician.district = latest_term.district
        count += 1
    return count


def _replace_terms(session: Session, records: list[LegislatorRecord]) -> int:
    session.execute(delete(PoliticianTerm))
    count = 0
    for record in records:
        for term in record.terms:
            session.add(
                PoliticianTerm(
                    bioguide_id=record.bioguide_id,
                    chamber=term.chamber,
                    state=term.state,
                    district=term.district,
                    party=term.party,
                    start_date=term.start,
                    end_date=term.end,
                )
            )
            count += 1
    return count


def main() -> None:
    pol_count, term_count = sync_legislators()
    print(f"Legislators sync: {pol_count} politician(s), {term_count} term(s).")


if __name__ == "__main__":
    main()
