"""Link filings.bioguide_id via congress-legislators data (T13).

Manual `politician_overrides` entries are checked first (exact match on
chamber + normalized filer_name); everything else goes through fuzzy name
matching against politicians whose term for the filing's chamber was active
on its filed date. Filings that can't be resolved either way get a
`dq_issues` row instead of a silent skip, so they surface for review or a
new override.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from congress_collector.db.models import (
    DqIssue,
    Filing,
    Politician,
    PoliticianOverride,
    PoliticianTerm,
)
from congress_collector.db.session import session_scope
from congress_collector.parsers.politician_match import Candidate, best_match, normalize_name

BATCH_SIZE = 200


def link_pending_filings(*, batch_size: int = BATCH_SIZE) -> int:
    """Assign bioguide_id to up to `batch_size` filings that don't have one
    yet. Returns the number successfully linked."""
    linked = 0
    with session_scope() as session:
        overrides = _load_overrides(session)
        pending = session.scalars(
            select(Filing).where(Filing.bioguide_id.is_(None)).limit(batch_size)
        ).all()

        for filing in pending:
            override_bioguide_id = overrides.get(
                (filing.chamber, normalize_name(filing.filer_name))
            )
            if override_bioguide_id is not None:
                filing.bioguide_id = override_bioguide_id
                linked += 1
                continue

            as_of = filing.filed_date or filing.first_seen_at.date()
            candidates = _candidates_for(session, filing.chamber, as_of)
            result = best_match(filing.filer_name, candidates)

            if result.bioguide_id is not None:
                filing.bioguide_id = result.bioguide_id
                linked += 1
            else:
                session.add(
                    DqIssue(
                        filing_id=filing.filing_id,
                        issue_type=f"politician_match_{result.method}",
                        details=(
                            f"filer_name={filing.filer_name!r} chamber={filing.chamber} "
                            f"as_of={as_of} best_score={result.score:.1f}"
                        ),
                    )
                )
    return linked


def _load_overrides(session: Session) -> dict[tuple[str, str], str]:
    return {
        (o.chamber, normalize_name(o.filer_name)): o.bioguide_id
        for o in session.scalars(select(PoliticianOverride))
    }


def _candidates_for(session: Session, chamber: str, as_of: date) -> list[Candidate]:
    rows = session.execute(
        select(PoliticianTerm.bioguide_id, Politician.full_name)
        .join(Politician, Politician.bioguide_id == PoliticianTerm.bioguide_id)
        .where(
            PoliticianTerm.chamber == chamber,
            PoliticianTerm.start_date <= as_of,
            (PoliticianTerm.end_date.is_(None)) | (PoliticianTerm.end_date >= as_of),
        )
    ).all()
    by_bioguide: dict[str, Candidate] = {}
    for bioguide_id, full_name in rows:
        by_bioguide[bioguide_id] = Candidate(bioguide_id=bioguide_id, full_name=full_name)
    return list(by_bioguide.values())


def main() -> None:
    linked = link_pending_filings()
    print(f"Politician linking: {linked} filing(s) linked.")


if __name__ == "__main__":
    main()
