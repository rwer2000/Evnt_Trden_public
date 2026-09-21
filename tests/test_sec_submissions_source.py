import httpx

from congress_collector.sources.sec_submissions import fetch_sic, parse_submission

_SUBMISSION = {
    "cik": "0000320193",
    "sic": "3571",
    "sicDescription": "Electronic Computers",
    "name": "Apple Inc.",
}


def test_parse_submission_extracts_sic_and_description() -> None:
    record = parse_submission("0000320193", _SUBMISSION)

    assert record.cik == "0000320193"
    assert record.sic == "3571"
    assert record.sic_description == "Electronic Computers"


def test_parse_submission_treats_empty_sic_as_none() -> None:
    record = parse_submission("0000320193", {**_SUBMISSION, "sic": ""})

    assert record.sic is None


def test_parse_submission_treats_missing_sic_description_as_none() -> None:
    record = parse_submission("0000320193", {"cik": "0000320193", "sic": "3571"})

    assert record.sic_description is None


def test_fetch_sic_parses_a_successful_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/submissions/CIK0000320193.json"
        return httpx.Response(200, json=_SUBMISSION)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    record = fetch_sic("0000320193", client=client)

    assert record is not None
    assert record.sic == "3571"


def test_fetch_sic_returns_none_for_a_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    record = fetch_sic("0000000001", client=client)

    assert record is None
