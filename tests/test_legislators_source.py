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
      start: '2009-01-03'
      end: '2011-01-03'
      state: WA
      district: 1
      party: Democrat
    - type: sen
      start: '2013-01-03'
      end: '2019-01-03'
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

- id:
    bioguide: Y000001
  name:
    first: Old
    last: AndNew
  terms:
    - type: sen
      start: '1999-01-03'
      end: '2005-01-03'
      state: TX
      party: Republican
    - type: sen
      start: '2015-01-03'
      state: TX
      party: Republican

- id:
    bioguide: W000001
  name:
    first: Long
    last: Retired
  terms:
    - type: rep
      start: '1990-01-03'
      end: '1992-01-03'
      state: NY
      district: 5
      party: Democrat

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


def test_terms_ending_before_the_cutoff_are_dropped() -> None:
    records = parse_legislators_yaml(SAMPLE_YAML)
    old_and_new = next(r for r in records if r.bioguide_id == "Y000001")

    # Only the 2015-onward term survives; the 1999-2005 one predates the
    # 2011 cutoff (legislators-historical.yaml goes back to 1789 and this
    # collector has no use for terms that old).
    assert len(old_and_new.terms) == 1
    assert old_and_new.terms[0].start.isoformat() == "2015-01-03"


def test_legislator_with_only_pre_cutoff_terms_is_dropped_entirely() -> None:
    records = parse_legislators_yaml(SAMPLE_YAML)

    assert not any(r.bioguide_id == "W000001" for r in records)


def test_empty_document_returns_no_records() -> None:
    assert parse_legislators_yaml("") == []
