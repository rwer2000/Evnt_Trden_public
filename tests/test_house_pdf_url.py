from congress_collector.ingest.house_pdfs import candidate_years
from congress_collector.sources.house import pdf_url_for


def test_ptr_filing_uses_ptr_pdfs_path() -> None:
    url = pdf_url_for("20034201", "P", 2026)
    assert url == "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/20034201.pdf"


def test_non_ptr_filing_uses_financial_pdfs_path() -> None:
    for filing_type in ["C", "O", "W", "X", "D"]:
        url = pdf_url_for("10078673", filing_type, 2026)
        assert (
            url
            == "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/2026/10078673.pdf"
        )


def test_candidate_years_try_the_index_year_before_and_after() -> None:
    # An annual report filed in March 2016 covers 2015 and sits in the
    # Clerk's 2015 folder.
    assert candidate_years(2016) == [2016, 2015, 2017]
