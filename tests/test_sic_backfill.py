import httpx

from congress_collector.ingest.sic_backfill import TickerCandidate, select_candidate_tickers
from congress_collector.parsers.cik_name_match import (
    is_equity_like_ticker,
    match_cik_by_name,
    name_from_description,
    normalize_entity_name,
)
from congress_collector.sources.sec_company_search import (
    EdgarEntity,
    parse_search_index,
    search_entities,
)

# --- company-name extraction and normalisation --------------------------------


def test_name_from_description_strips_security_tail_ticker_and_brackets() -> None:
    assert (
        name_from_description("Pure Storage, Inc. Class A Common Stock (PSTG) [ST]", "PSTG")
        == "Pure Storage, Inc."
    )
    assert name_from_description("Inotek Pharmaceuticals Corporation (ITEK) [sT]") == (
        "Inotek Pharmaceuticals Corporation"
    )


def test_name_from_description_drops_leading_ticker_prefix() -> None:
    assert name_from_description("BRCM - Broadcom Corporation", "BRCM") == "Broadcom Corporation"


def test_name_from_description_cuts_adr_and_unit_wording() -> None:
    assert (
        name_from_description("Hennes & Mauritz ab Unsponsored adR (HNNMY)")
        == "Hennes & Mauritz ab"
    )
    assert name_from_description(
        "Energy Transfer Partners, l.P. Common units representing limited partner interest"
    ) == ("Energy Transfer Partners, l.P.")
    assert name_from_description("SONIC HEALTHCARE SP/ADR (SKHHY) [ST]") == "SONIC HEALTHCARE"


def test_name_from_description_keeps_names_starting_with_cut_words() -> None:
    # The security-tail cut needs preceding whitespace, so a name that
    # *starts* with such a word survives.
    assert name_from_description("Common Ground Holdings Inc") == "Common Ground Holdings Inc"


def test_name_from_description_returns_none_when_nothing_is_left() -> None:
    assert name_from_description("(VMW) [ST]") is None


def test_normalize_entity_name_matches_sec_and_filer_spellings() -> None:
    assert normalize_entity_name("BROADCOM CORP") == normalize_entity_name("Broadcom Corporation")
    assert normalize_entity_name("VMWARE, INC.") == normalize_entity_name("Vmware, Inc.")
    assert normalize_entity_name("INTEL CORP /DE/") == "intel"
    assert normalize_entity_name("ENERGY TRANSFER PARTNERS, L.P.") == "energy transfer partners"
    assert normalize_entity_name("Procter & Gamble Co") == "procter and gamble"
    assert normalize_entity_name("The Walt Disney Company") == "walt disney"
    assert normalize_entity_name("Macy's, Inc.") == "macys"


def test_normalize_entity_name_keeps_distinguishing_words() -> None:
    # Only a *trailing* legal form is stripped; "holdings"/"group" stay.
    assert normalize_entity_name("Validus Holdings, Ltd.") == "validus holdings"
    assert normalize_entity_name("Validus Holdings, Ltd.") != normalize_entity_name("Validus Ltd")


def test_is_equity_like_ticker() -> None:
    for ticker in ("VMW", "BRK.B", "BF-B", "QABSY", "A"):
        assert is_equity_like_ticker(ticker)
    for ticker in ("912796QV4", "07/01/28", "6-MONTH", "3305779", "--  AM", "0QZI.IL", "TOOLONG"):
        assert not is_equity_like_ticker(ticker)


# --- conservative CIK matching ------------------------------------------------

_BROADCOM_OLD = EdgarEntity(cik="0001054374", name="BROADCOM CORP", tickers=())
_BROADCOM_NEW = EdgarEntity(cik="0001730168", name="Broadcom Inc.", tickers=("AVGO",))
_BROADCOM_LTD = EdgarEntity(cik="0001649338", name="Broadcom Ltd", tickers=())
_BROADCOM_FUND = EdgarEntity(cik="0000000042", name="Broadcom Employee Fund LLC", tickers=())


def test_match_requires_an_exact_normalised_name() -> None:
    result = match_cik_by_name("BRCM", ["Broadcom Corporation"], [[_BROADCOM_FUND]])

    assert result.status == "unmatched"
    assert result.cik is None


def test_match_single_exact_hit() -> None:
    result = match_cik_by_name(
        "VMW",
        ["Vmware, Inc."],
        [[EdgarEntity(cik="0001124610", name="VMWARE, INC.", tickers=())]],
    )

    assert result.status == "matched"
    assert result.cik == "0001124610"
    assert result.name == "VMWARE, INC."


def test_match_several_ciks_with_same_normalised_name_is_ambiguous() -> None:
    result = match_cik_by_name(
        "BRCM", ["Broadcom Corporation"], [[_BROADCOM_OLD, _BROADCOM_NEW, _BROADCOM_LTD]]
    )

    assert result.status == "ambiguous"
    assert result.cik is None
    assert result.candidates == ("0001054374", "0001649338", "0001730168")


def test_ambiguity_is_broken_only_when_exactly_one_candidate_lists_the_ticker() -> None:
    result = match_cik_by_name("AVGO", ["Broadcom Inc."], [[_BROADCOM_OLD, _BROADCOM_NEW]])

    assert result.status == "matched"
    assert result.cik == "0001730168"


def test_different_names_for_one_ticker_resolving_to_different_ciks_is_ambiguous() -> None:
    a = EdgarEntity(cik="0000000001", name="Alpha Corp", tickers=())
    b = EdgarEntity(cik="0000000002", name="Beta Inc", tickers=())

    result = match_cik_by_name("XYZ", ["Alpha Corporation", "Beta, Inc."], [[a], [b]])

    assert result.status == "ambiguous"


def test_same_cik_reached_via_two_names_is_still_one_match() -> None:
    e = EdgarEntity(cik="0000000001", name="Alpha Corp", tickers=())

    result = match_cik_by_name("XYZ", ["Alpha Corporation", "ALPHA CORP"], [[e], [e]])

    assert result.status == "matched"


# --- ticker-set selection -----------------------------------------------------


def test_selects_only_uncovered_ticker_shaped_tickers() -> None:
    rows = [
        ("AAPL", "Apple Inc. (AAPL) [ST]", True),  # linked -> covered
        ("aapl", "Apple Inc. Common Stock", False),  # same ticker, still covered
        ("FB", "Facebook, Inc. Class A (FB) [ST]", False),  # in ticker_map -> covered
        ("VMW", "Vmware, Inc. Common stock, Class A (VMW) [ST]", False),
        ("VMW", "Vmware, Inc. Common stock, Class A (VMW) [ST]", False),
        ("vmw", "VMware Inc", False),
        ("912796QV4", "US T BILL DUE 08/15/19 (912796QV4) [GS]", False),  # CUSIP
        (None, "Some private fund", False),
        ("  ", "blank ticker", False),
        ("CBI", "Chicago Bridge & Iron Company N.V. (CBI)", False),
    ]

    candidates = select_candidate_tickers(rows, covered_tickers={"fb"})

    assert [c.ticker for c in candidates] == ["CBI", "VMW"]
    assert candidates[1] == TickerCandidate("VMW", ("Vmware, Inc.", "VMware Inc"))


def test_selection_caps_names_per_ticker_most_common_first() -> None:
    rows = [
        ("XYZ", "Rare Name Inc", False),
        ("XYZ", "Common Name Inc (XYZ)", False),
        ("XYZ", "Common Name Inc (XYZ) [ST]", False),
        ("XYZ", "Third Name Inc", False),
    ]

    candidates = select_candidate_tickers(rows, covered_tickers=set(), max_names=2)

    assert candidates[0].names[0] == "Common Name Inc"
    assert len(candidates[0].names) == 2


def test_selection_keeps_ticker_without_usable_name() -> None:
    candidates = select_candidate_tickers([("ZZZ", "(ZZZ) [ST]", False)], covered_tickers=set())

    assert candidates == [TickerCandidate("ZZZ", ())]


# --- EDGAR entity-search response parsing --------------------------------------

_SEARCH_RESPONSE = {
    "hits": {
        "hits": [
            {"_id": "1124610", "_source": {"entity": "VMWARE, INC.", "tickers": "VMW"}},
            {"_id": "0001730168", "_source": {"entity": "Broadcom Inc.", "tickers": "AVGO, AVGOP"}},
            {"_id": "not-a-cik", "_source": {"entity": "Junk"}},
            {"_id": "0000000001", "_source": {}},
            {"_id": "0000000002"},
        ]
    }
}


def test_parse_search_index_extracts_entities_defensively() -> None:
    entities = parse_search_index(_SEARCH_RESPONSE)

    assert entities == [
        EdgarEntity(cik="0001124610", name="VMWARE, INC.", tickers=("VMW",)),
        EdgarEntity(cik="0001730168", name="Broadcom Inc.", tickers=("AVGO", "AVGOP")),
    ]


def test_parse_search_index_tolerates_unexpected_shapes() -> None:
    assert parse_search_index([]) == []
    assert parse_search_index({"hits": []}) == []
    assert parse_search_index({}) == []


def test_search_entities_sends_name_as_query_and_raises_on_block() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["keysTyped"] == "blocked":
            return httpx.Response(403)
        assert request.url.path == "/LATEST/search-index"
        return httpx.Response(200, json=_SEARCH_RESPONSE)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    assert len(search_entities("Vmware, Inc.", client=client)) == 2
    try:
        search_entities("blocked", client=client)
    except httpx.HTTPStatusError as exc:
        assert exc.response.status_code == 403
    else:
        raise AssertionError("expected HTTPStatusError")
