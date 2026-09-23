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


def test_normalize_name_strips_professional_credentials() -> None:
    assert normalize_name("Neal Patrick MD, Facs Dunn") == "neal patrick dunn"


def test_best_match_resolves_extra_middle_name_via_first_and_last_trim() -> None:
    # An extra middle name in the filer's own PTR can drag the full-name
    # score below REVIEW_THRESHOLD even though first+last already match
    # exactly and unambiguously -- e.g. Rep. Michael Guest signs PTRs as
    # "Michael Patrick Guest".
    candidates = [
        Candidate(bioguide_id="G000591", full_name="Michael Guest"),
        Candidate(bioguide_id="M000355", full_name="Mitch McConnell"),
    ]

    result = best_match("Hon. Michael Patrick Guest", candidates)

    assert result.bioguide_id == "G000591"
    assert result.method == "fuzzy"


def test_best_match_middle_name_trim_does_not_resolve_a_genuine_collision() -> None:
    # Two distinct candidates sharing a first and last name, differing
    # only by middle initial -- trimming the query's middle name makes
    # them score an exact tie, which must still come back ambiguous
    # rather than silently picking one. Uses middle initials that share no
    # letters with the query's own middle name ("Patrick"), since
    # token_sort_ratio isn't purely token-structural -- a coincidentally
    # shared letter (e.g. "Patrick" vs "R") can otherwise separate two
    # candidates by a few points for reasons that have nothing to do with
    # genuine identity, which would mask the exact tie this test means to
    # exercise.
    candidates = [
        Candidate(bioguide_id="A000001", full_name="Michael X Guest"),
        Candidate(bioguide_id="A000002", full_name="Michael Z Guest"),
    ]

    result = best_match("Michael Patrick Guest", candidates)

    assert result.bioguide_id is None
    assert result.method in ("ambiguous", "unmatched")
