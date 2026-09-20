from congress_collector.parsers.politician_match import Candidate, best_match, normalize_name


def test_normalize_name_strips_titles_and_punctuation() -> None:
    assert normalize_name("Hon. Nancy Pelosi") == "nancy pelosi"
    assert normalize_name("Smith Jr., John") == "smith john"


def test_normalize_name_collapses_whitespace_and_case() -> None:
    assert normalize_name("  JANE   Doe  ") == "jane doe"


def test_best_match_exact_name() -> None:
    candidates = [
        Candidate(bioguide_id="P000197", full_name="Nancy Pelosi"),
        Candidate(bioguide_id="M000355", full_name="Mitch McConnell"),
    ]

    result = best_match("Hon. Nancy Pelosi", candidates)

    assert result.bioguide_id == "P000197"
    assert result.method == "fuzzy"
    assert result.score > 90


def test_best_match_no_candidates_is_unmatched() -> None:
    result = best_match("Nancy Pelosi", [])

    assert result.bioguide_id is None
    assert result.method == "unmatched"


def test_best_match_below_threshold_is_unmatched() -> None:
    candidates = [Candidate(bioguide_id="M000355", full_name="Mitch McConnell")]

    result = best_match("Zzyx Qwerty", candidates)

    assert result.bioguide_id is None
    assert result.method == "unmatched"


def test_best_match_close_tie_is_ambiguous() -> None:
    # Two similarly-scoring, distinct candidates for a name that isn't an
    # exact match to either -- shouldn't silently pick one.
    candidates = [
        Candidate(bioguide_id="A000001", full_name="John A Smith"),
        Candidate(bioguide_id="A000002", full_name="John B Smith"),
    ]

    result = best_match("John Smith", candidates)

    assert result.bioguide_id is None
    assert result.method == "ambiguous"


def test_best_match_prefers_unambiguous_high_confidence_over_tie() -> None:
    candidates = [
        Candidate(bioguide_id="P000197", full_name="Nancy Pelosi"),
        Candidate(bioguide_id="A000002", full_name="Nancy Peloso"),
    ]

    result = best_match("Nancy Pelosi", candidates)

    assert result.bioguide_id == "P000197"
    assert result.method == "fuzzy"
