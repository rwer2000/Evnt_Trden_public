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
# otherwise drag the fuzzy score down for an otherwise exact match. Includes
# professional credentials some filers append to their own name on the PTR
# (e.g. "Neal Patrick MD, Facs Dunn" for Rep. Neal Dunn, an M.D. and Fellow
# of the American College of Surgeons) -- confirmed live these push an
# otherwise-clean match's score from the low 60s to well below
# REVIEW_THRESHOLD across 26 filings for that one member alone.
_NOISE_WORDS = {
    "hon",
    "honorable",
    "mr",
    "mrs",
    "ms",
    "dr",
    "jr",
    "sr",
    "ii",
    "iii",
    "iv",
    "md",
    "facs",
    "phd",
    "esq",
    "dds",
    "dvm",
    "cpa",
}

# A top score below this isn't a real match -- leave bioguide_id unset and
# flag the filing for manual review (or a politician_overrides entry).
REVIEW_THRESHOLD = 80.0

# Two candidates within this many points of each other are treated as a
# tie and never auto-assigned, regardless of how high the top score is --
# confirmed live via the first+last trim fallback below: "Michael Patrick
# Guest" trimmed to "Michael Guest" scored an exact 92.857 tie against two
# *different* synthetic candidates "Michael Q Guest"/"Michael R Guest",
# which an earlier version of this check (skipping the tie test whenever
# top_score >= a "high confidence" cutoff) let through as an unambiguous
# match to whichever one happened to sort first -- a real
# wrong-person-gets-the-filing risk once middle names can get trimmed
# away. A high top score with a real gap to the runner-up (e.g. 100 vs 92,
# an 8-point gap) still clears this check fine; only an actual near-tie
# doesn't.
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
    result = _score(query, candidates)
    if result.method == "fuzzy":
        return result

    # A middle name/initial the filer's own PTR includes, but the
    # congress-legislators name doesn't (or vice-versa), can drag
    # token_sort_ratio below REVIEW_THRESHOLD even though first+last
    # already match exactly -- confirmed live for members like "Michael
    # Patrick Guest" (76.5 full name vs "Michael Guest") who otherwise
    # match cleanly. Retried on first+last words only, since that's
    # exactly the shape of this failure mode; still goes through the same
    # ambiguity check, so a genuine collision (two candidates sharing a
    # first and last name) still won't auto-assign.
    trimmed = _first_and_last(query)
    if trimmed != query:
        trimmed_result = _score(trimmed, candidates)
        if trimmed_result.method == "fuzzy":
            return trimmed_result

    return result


def _score(query: str, candidates: Sequence[Candidate]) -> MatchResult:
    scored = sorted(
        ((fuzz.token_sort_ratio(query, normalize_name(c.full_name)), c) for c in candidates),
        key=lambda pair: pair[0],
        reverse=True,
    )
    top_score, top_candidate = scored[0]

    if top_score < REVIEW_THRESHOLD:
        return MatchResult(None, top_score, "unmatched")

    runner_up_score = scored[1][0] if len(scored) > 1 else 0.0
    if (top_score - runner_up_score) < _TIE_MARGIN:
        return MatchResult(None, top_score, "ambiguous")

    return MatchResult(top_candidate.bioguide_id, top_score, "fuzzy")


def _first_and_last(query: str) -> str:
    words = query.split()
    if len(words) <= 2:
        return query
    return f"{words[0]} {words[-1]}"
