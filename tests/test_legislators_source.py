from congress_collector.sources.legislators import parse_legislators_yaml

SAMPLE_YAML = """
- id:
    bioguide: C000127
  name:
    first: Maria
    last: Cantwell
    official_full: Maria Cantwell
  terms:
    - type: rep
      start: '1993-01-05'
      end: '1995-01-03'
      state: WA
      district: 1
      party: Democrat
    - type: sen
      start: '2001-01-03'
      end: '2007-01-03'
      state: WA
      party: Democrat
    - type: sen
      start: '2019-01-03'
      state: WA
      party: Democrat

- id:
    bioguide: X000001
  name:
    first: At
    last: Large
  terms:
    - type: rep
      start: '2015-01-03'
      end: '2017-01-03'
      state: AK
      district: 0
      party: Republican

- id: {}
  name:
    first: No
    last: Bioguide
  terms:
    - type: rep
      start: '2015-01-03'
      state: TX
      district: 5

- id:
    bioguide: Z000001
  name:
    first: No
    last: Terms
  terms: []
"""


def test_parses_multiple_terms_and_picks_official_full_name() -> None:
    records = parse_legislators_yaml(SAMPLE_YAML)
    cantwell = next(r for r in records if r.bioguide_id == "C000127")

    assert cantwell.full_name == "Maria Cantwell"
    assert len(cantwell.terms) == 3


def test_terms_are_sorted_chronologically() -> None:
    records = parse_legislators_yaml(SAMPLE_YAML)
    cantwell = next(r for r in records if r.bioguide_id == "C000127")

    starts = [t.start.isoformat() for t in cantwell.terms]
    assert starts == sorted(starts)


def test_term_type_maps_to_chamber() -> None:
    records = parse_legislators_yaml(SAMPLE_YAML)
    cantwell = next(r for r in records if r.bioguide_id == "C000127")

    assert cantwell.terms[0].chamber == "house"
    assert cantwell.terms[1].chamber == "senate"


def test_open_ended_term_has_no_end_date() -> None:
    records = parse_legislators_yaml(SAMPLE_YAML)
    cantwell = next(r for r in records if r.bioguide_id == "C000127")

    assert cantwell.terms[-1].end is None


def test_at_large_district_zero_is_preserved() -> None:
    records = parse_legislators_yaml(SAMPLE_YAML)
    at_large = next(r for r in records if r.bioguide_id == "X000001")

    assert at_large.terms[0].district == "0"


def test_missing_official_full_falls_back_to_first_last() -> None:
    records = parse_legislators_yaml(SAMPLE_YAML)
    at_large = next(r for r in records if r.bioguide_id == "X000001")

    assert at_large.full_name == "At Large"


def test_entry_without_bioguide_id_is_skipped() -> None:
    records = parse_legislators_yaml(SAMPLE_YAML)

    assert all(r.bioguide_id for r in records)
    assert not any(r.full_name == "No Bioguide" for r in records)


def test_entry_without_terms_is_skipped() -> None:
    records = parse_legislators_yaml(SAMPLE_YAML)

    assert not any(r.bioguide_id == "Z000001" for r in records)


def test_empty_document_returns_no_records() -> None:
    assert parse_legislators_yaml("") == []
