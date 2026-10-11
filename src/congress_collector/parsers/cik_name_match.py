"""Exact-normalised company-name matching for the SIC backfill (A3):
turn a transaction's raw asset description into a company name, and
decide whether an EDGAR entity-search result is the same company.

Deliberately stricter than ``ticker_match.match_by_description``'s fuzzy
fallback: a name only matches when both sides are *identical* after
normalisation (case, punctuation, ``&``/``and``, EDGAR's ``/DE/``
state-of-incorporation tags, and a trailing legal-form suffix such as
``Inc.``/``Corp``/``L.P.``). Anything else -- no hit, or more than one
CIK carrying the same normalised name -- is left unmatched/ambiguous and
logged, because a wrong SIC is worse than a missing one.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from congress_collector.sources.sec_company_search import EdgarEntity

_BRACKET_RE = re.compile(r"\[[^\]]*\]")
_PAREN_RE = re.compile(r"\([^)]*\)")
_STATE_TAG_RE = re.compile(r"/[a-z]{2,3}(?:/|$)")
# Where a description stops naming the company and starts naming the
# security ("Pure Storage, Inc. Class A Common Stock").
_SECURITY_TAIL_RE = re.compile(
    r"\s(?:-\s|class\s+(?:[a-c]|[1-9])\b|cl\s+[a-c]\b|series\s+[a-c]\b|"
    r"common\b|ordinary\b|ords?\b|shs\b|sp\b|spon\b|spns\b|spn?/adr|s/adr\b|"
    r"american\s+depositary|unsponsored|sponsored|adrs?\b|ads\b|depositary|"
    r"units?\s+representing|shares?\s+of\s+beneficial|warrants?\b|preferred\b)",
    re.IGNORECASE,
)
# Legal-form suffixes stripped from the *end* of a name only (repeatedly:
# "Foo Holdings Co., Ltd." keeps "holdings"). "holdings"/"group"/"trust"
# are deliberately not here -- they often distinguish real entities.
_LEGAL_SUFFIXES = frozenset(
    {
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "co",
        "company",
        "ltd",
        "limited",
        "plc",
        "llc",
        "lp",
        "llp",
        "sa",
        "ag",
        "nv",
        "se",
        "the",
    }
)
_EQUITY_TICKER_RE = re.compile(r"^[A-Z]{1,5}(?:[.\-/][A-Z]{1,2})?$")


def is_equity_like_ticker(ticker: str) -> bool:
    """Does this look like an exchange ticker (rather than a CUSIP, a
    date, a SEDOL number or a parser artefact)?"""
    return bool(_EQUITY_TICKER_RE.match(ticker))


def normalize_entity_name(raw: str) -> str:
    s = raw.lower()
    s = _BRACKET_RE.sub(" ", s)
    s = _PAREN_RE.sub(" ", s)
    s = _STATE_TAG_RE.sub(" ", s)
    s = s.replace("&", " and ").replace("'", "").replace(".", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    tokens = s.split()
    while tokens and tokens[0] == "the":
        tokens.pop(0)
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def name_from_description(description: str, ticker: str | None = None) -> str | None:
    """The company-name part of a raw asset description, or None if
    nothing name-like is left. Not normalised (it's also the search query)."""
    s = _BRACKET_RE.sub(" ", description)
    s = _PAREN_RE.sub(" ", s)
    s = " ".join(s.split())
    if ticker:
        prefix = re.match(rf"^{re.escape(ticker)}\s*-\s*", s, re.IGNORECASE)
        if prefix:
            s = s[prefix.end() :]
    tail = _SECURITY_TAIL_RE.search(s)  # needs leading whitespace: never at index 0
    if tail:
        s = s[: tail.start()]
    s = s.strip(" ,;:-")
    if len(normalize_entity_name(s)) < 2:
        return None
    return s


@dataclass(frozen=True)
class NameMatch:
    status: str  # "matched" | "ambiguous" | "unmatched"
    cik: str | None
    name: str | None
    candidates: tuple[str, ...]  # every CIK whose normalised name matched


def match_cik_by_name(
    ticker: str, names: Sequence[str], hits_per_name: Iterable[Sequence[EdgarEntity]]
) -> NameMatch:
    """Pick the CIK whose EDGAR name equals (after normalisation) one of
    the company names this ticker's transactions describe.

    Exactly one matching CIK across all of the ticker's names -> matched.
    Several -> matched only if exactly one of them still lists `ticker`
    on EDGAR (name *and* ticker agree); otherwise ambiguous."""
    wanted = {normalize_entity_name(n) for n in names} - {""}
    found: dict[str, EdgarEntity] = {}
    for hits in hits_per_name:
        for entity in hits:
            if normalize_entity_name(entity.name) in wanted:
                found.setdefault(entity.cik, entity)

    if not found:
        return NameMatch("unmatched", None, None, ())
    candidates = tuple(sorted(found))
    if len(found) == 1:
        only = next(iter(found.values()))
        return NameMatch("matched", only.cik, only.name, candidates)

    with_ticker = [e for e in found.values() if ticker.upper() in e.tickers]
    if len(with_ticker) == 1:
        return NameMatch("matched", with_ticker[0].cik, with_ticker[0].name, candidates)
    return NameMatch("ambiguous", None, None, candidates)
