"""Sync `committees` + `committee_memberships` from congress-legislators (T23).

Same source and replace-on-sync pattern as T13's legislators.py:
`committee_memberships` is fully replaced on every run (delete-all then
re-insert), since the YAML file is the single source of truth and nothing
else writes to this table; `committees` is upserted by thomas_id.

Membership rows are additionally filtered to bioguide_ids already present
in `politicians` before insert, even though this sync runs as a step
right after T13's legislators sync in the same workflow (so ordering
should already guarantee it): defends against the rare case of the two
YAML files disagreeing on current membership (e.g. a very recent
appointment), which would otherwise violate committee_memberships'
bioguide_id foreign key and fail the whole sync over one row.
"""

from collections.abc import Iterator, Sequence
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from congress_collector.db.models import Committee, CommitteeMembership, Politician
from congress_collector.db.session import session_scope
from congress_collector.sources.committees import (
    CommitteeRecord,
    MembershipRecord,
    fetch_committees_and_memberships,
)

CHUNK_SIZE = 500


def sync_committees() -> tuple[int, int]:
    """Upsert every current committee and replace all memberships.
    Returns (committees upserted, memberships inserted)."""
    committees, memberships = fetch_committees_and_memberships()
    with session_scope() as session:
        committee_count = _upsert_committees(session, committees)
        known_bioguides = set(session.scalars(select(Politician.bioguide_id)))
        memberships = [m for m in memberships if m.bioguide_id in known_bioguides]
        membership_count = _replace_memberships(session, memberships)
    return committee_count, membership_count


def _upsert_committees(session: Session, records: list[CommitteeRecord]) -> int:
    rows = [{"thomas_id": r.thomas_id, "chamber": r.chamber, "name": r.name} for r in records]
    for chunk in _chunked(rows, CHUNK_SIZE):
        stmt = pg_insert(Committee).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Committee.thomas_id],
            set_={"chamber": stmt.excluded.chamber, "name": stmt.excluded.name},
        )
        session.execute(stmt)
        session.commit()
    return len(rows)


def _replace_memberships(session: Session, records: list[MembershipRecord]) -> int:
    session.execute(delete(CommitteeMembership))
    session.commit()

    rows = [
        {
            "thomas_id": r.thomas_id,
            "bioguide_id": r.bioguide_id,
            "party": r.party,
            "rank": r.rank,
            "title": r.title,
        }
        for r in records
    ]
    for chunk in _chunked(rows, CHUNK_SIZE):
        session.execute(insert(CommitteeMembership), chunk)
        session.commit()
    return len(rows)


def _chunked(rows: Sequence[dict[str, Any]], size: int) -> Iterator[Sequence[dict[str, Any]]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def main() -> None:
    committee_count, membership_count = sync_committees()
    print(f"Committees sync: {committee_count} committee(s), {membership_count} membership(s).")


if __name__ == "__main__":
    main()
