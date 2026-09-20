"""Match a transaction's raw ticker or asset description against the SEC
company reference data (T14). Exact ticker lookup first; fuzzy company-name
matching as a fallback for descriptions the parser couldn't extract a clean
ticker from.

The fuzzy fallback is intentionally conservative. An early version used
rapidfuzz's token_set_ratio, which scores a perfect *subset* match at 100
regardless of what else is in either string -- verified against the real
vendored data that this produces confident, wrong matches for messy
descriptions ("Invesco QQQ" -> "Invesco Ltd.", a real asset manager but not
the ETF's actual registrant; "DIA - State Street SPDR..." -> "STATE STREET
CORP", the ETF's sponsor, not the trust itself which *is* in the data under
its own name). A mislinked instrument is a worse outcome than an unmatched
transaction sitting in the review queue, so this uses token_sort_ratio
(no subset leniency) with a high threshold instead, after stripping the
description's own noise (asset-type brackets, a leading ticker/dash
prefix, "EXCHANGE: TICKER" mentions) that isn't part of the company name.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from congress_collector.sources.sec_tickers import SecCompany

_BRACKET_RE = re.compile(r"\[[^\]]*\]")
_TICKER_PREFIX_RE = re.compile(r"^[A-Z]{1,5}\s*-\s*")
_EXCHANGE_TICKER_RE = re.compile(
    r"\b(NYSEARCA|NASDAQ|NYSE|CBOE|OTC)\s*:\s*[A-Z]{1,5}\b", re.IGNORECASE
)
_NAME_NOISE_RE = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|ltd|plc|llc|lp|"
    r"class\s+[a-c]|common\s+stock|ordinary\s+shares)\b\.?",
    re.IGNORECASE,
)

# High and fuzzy-matching only, since exact ticker matches always score
# 100 -- see the module docstring on why this errs conservative.
REVIEW_THRESHOLD = 90.0


def normalize_ticker(raw: str) -> str:
    return raw.strip().upper()


def normalize_company_name(raw: str) -> str:
    cleaned = _BRACKET_RE.sub(" ", raw)
    cleaned = _TICKER_PREFIX_RE.sub(" ", cleaned)
    cleaned = _EXCHANGE_TICKER_RE.sub(" ", cleaned)
    cleaned = _NAME_NOISE_RE.sub(" ", cleaned)
    cleaned = re.sub(r"[.,:()]", " ", cleaned)
    return " ".join(cleaned.split()).lower()


@dataclass(frozen=True)
class MatchResult:
    company: SecCompany | None
    score: float
    method: str  # "ticker_exact" | "fuzzy" | "unmatched"


def match_by_ticker(ticker_raw: str, by_ticker: dict[str, SecCompany]) -> SecCompany | None:
    return by_ticker.get(normalize_ticker(ticker_raw))


def match_by_description(description: str, candidates: Sequence[SecCompany]) -> MatchResult:
    if not candidates:
        return MatchResult(None, 0.0, "unmatched")

    query = normalize_company_name(description)
    choices = {c: normalize_company_name(c.title) for c in candidates}
    result = process.extractOne(query, choices, scorer=fuzz.token_sort_ratio)
    if result is None:
        return MatchResult(None, 0.0, "unmatched")

    _, score, company = result
    if score < REVIEW_THRESHOLD:
        return MatchResult(None, score, "unmatched")
    return MatchResult(company, score, "fuzzy")
