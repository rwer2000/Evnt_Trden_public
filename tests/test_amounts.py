import pytest

from congress_collector.parsers.amounts import parse_amount_range


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$1,001 - $15,000", (1001.0, 15000.0)),
        ("Over $50,000,000", (50_000_000.0, None)),
        ("", (None, None)),
        # Exact amounts (House form allows them instead of a band).
        ("$2,722.50", (2722.5, 2722.5)),
        ("$.01", (0.01, 0.01)),
        ("$60.00", (60.0, 60.0)),
        # A band's lower bound alone is a truncated band, not an exact value.
        ("$15,001", (None, None)),
        ("$15,001 -", (15001.0, None)),
        # Spouse/dependent-child band.
        ("Spouse/DC Over $1,000,000", (1_000_000.0, None)),
        ("Spouse/DC over $1,000,000", (1_000_000.0, None)),
        # Soft hyphen / en dash separators, trailing junk.
        ("$15,001 \xad $50,000 correct to the best", (15001.0, 50000.0)),
        ("$1,001 – $15,000", (1001.0, 15000.0)),
        ("ESOP", (None, None)),
        ("and correct to the", (None, None)),
    ],
)
def test_parse_amount_range(raw: str, expected: tuple[float | None, float | None]) -> None:
    assert parse_amount_range(raw) == expected
