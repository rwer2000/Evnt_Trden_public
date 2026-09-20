"""Fuzzy-match a filing's raw filer name against a set of candidate
politicians (T13). The caller narrows candidates to a filing's chamber and
the term active on its filed date -- this module only scores names.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from rapidfuzz import fuzz

# Titles/suffixes that appear in one source but not the other (House index
# entries carry a "Hon." prefix; congress-legislators names don't) and would
# otherwise drag the fuzzy score down for an otherwise exact match.
_NOISE_WORDS = {"hon", "honorable", "mr", "mrs", "ms", "dr", "jr", "sr", "ii", "iii", "iv"}

# A top score below this isn't a real match -- leave bioguide_id unset and
# flag the filing for manual review (or a politician_overrides entry).
REVIEW_THRESHOLD = 80.0

# Two candidates within this many points of each other are treated as a tie
# unless the top score also clears HIGH_CONFIDENCE -- an ambiguous name
# collision shouldn't auto-assign even if both candidates score reasonably.
HIGH_CONFIDENCE = 92.0
_TIE_MARGIN = 5.0


def normalize_name(raw: str) -> str:
    """Lowercase, drop punctuation and titles/suffixes, collapse whitespace."""
    cleaned = re.sub(r"[.,]", " ", raw.lower())
    words = [w for w in cleaned.split() if w not in _NOISE_WORDS]
    return " ".join(words)


@dataclass(frozen=True)
class Candidate:
    bioguide_id: str
    full_name: str


@dataclass(frozen=True)
class MatchResult:
    bioguide_id: str | None
    score: float
    method: str  # "fuzzy" | "unmatched" | "ambiguous"


def best_match(filer_name: str, candidates: Sequence[Candidate]) -> MatchResult:
    if not candidates:
        return MatchResult(None, 0.0, "unmatched")

    query = normalize_name(filer_name)
    scored = sorted(
        ((fuzz.token_sort_ratio(query, normalize_name(c.full_name)), c) for c in candidates),
        key=lambda pair: pair[0],
        reverse=True,
    )
    top_score, top_candidate = scored[0]

    if top_score < REVIEW_THRESHOLD:
        return MatchResult(None, top_score, "unmatched")

    runner_up_score = scored[1][0] if len(scored) > 1 else 0.0
    if top_score < HIGH_CONFIDENCE and (top_score - runner_up_score) < _TIE_MARGIN:
        return MatchResult(None, top_score, "ambiguous")

    return MatchResult(top_candidate.bioguide_id, top_score, "fuzzy")
