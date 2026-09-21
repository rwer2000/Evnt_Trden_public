from congress_collector.sources.committees import parse_committees_yaml, parse_membership_yaml

COMMITTEES_YAML = """
- type: house
  name: Committee on Agriculture
  thomas_id: HSAG
  subcommittees:
    - name: Subcommittee on Livestock
      thomas_id: HSAG14
- type: senate
  name: Committee on Banking, Housing, and Urban Affairs
  thomas_id: SSBK
- type: joint
  name: Joint Economic Committee
  thomas_id: JSEC
- type: house
  name: Missing thomas_id
- name: Missing type
  thomas_id: HSXX
"""

MEMBERSHIP_YAML = """
HSAG:
  - name: David Rouzer
    party: majority
    rank: 1
    title: Chairman
    bioguide: R000603
  - name: Jane Doe
    party: minority
    rank: 1
    bioguide: D000001
HSAG14:
  - name: Subcommittee Member
    party: majority
    rank: 1
    bioguide: S000001
SSBK:
  - name: No Bioguide
    party: majority
    rank: 1
UNKNOWN:
  - name: Not A Real Committee
    party: majority
    rank: 1
    bioguide: X000001
"""


def test_parse_committees_yaml_keeps_only_valid_top_level_committees() -> None:
    records = parse_committees_yaml(COMMITTEES_YAML)

    assert [r.thomas_id for r in records] == ["HSAG", "SSBK", "JSEC"]


def test_parse_committees_yaml_preserves_chamber_and_name() -> None:
    records = parse_committees_yaml(COMMITTEES_YAML)
    ag = next(r for r in records if r.thomas_id == "HSAG")

    assert ag.chamber == "house"
    assert ag.name == "Committee on Agriculture"


def test_parse_membership_yaml_keeps_only_known_top_level_committees() -> None:
    known = {r.thomas_id for r in parse_committees_yaml(COMMITTEES_YAML)}

    records = parse_membership_yaml(MEMBERSHIP_YAML, known_thomas_ids=known)

    assert {r.thomas_id for r in records} == {"HSAG"}


def test_parse_membership_yaml_drops_rows_without_a_bioguide_id() -> None:
    known = {"SSBK"}

    records = parse_membership_yaml(MEMBERSHIP_YAML, known_thomas_ids=known)

    assert records == []


def test_parse_membership_yaml_preserves_party_rank_and_optional_title() -> None:
    known = {"HSAG"}

    records = parse_membership_yaml(MEMBERSHIP_YAML, known_thomas_ids=known)
    chair = next(r for r in records if r.bioguide_id == "R000603")
    member = next(r for r in records if r.bioguide_id == "D000001")

    assert chair.party == "majority"
    assert chair.rank == 1
    assert chair.title == "Chairman"
    assert member.title is None


def test_parse_committees_yaml_empty_document_returns_no_records() -> None:
    assert parse_committees_yaml("") == []


def test_parse_membership_yaml_empty_document_returns_no_records() -> None:
    assert parse_membership_yaml("", known_thomas_ids={"HSAG"}) == []
