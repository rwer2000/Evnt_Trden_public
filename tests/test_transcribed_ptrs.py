from pathlib import Path

from congress_collector.ingest.transcribed_ptrs import read_csv

_DATA = Path(__file__).parent.parent / "data" / "transcribed_house_ptrs_2026-10-09.csv"


def test_csv_maps_bands_tickers_and_letters(tmp_path: Path) -> None:
    csv_path = tmp_path / "t.csv"
    csv_path.write_text(
        "doc_id,page,row,owner,asset_name,ticker,tx_type,tx_date,notification_date,"
        "amount_band,k_flag,confidence,review,note\n"
        '9107955,1,1,self,"PFIZER, INC. PFE COMMON STOCK",PFE,sale_full,2015-11-23,2015-11-23,A,,'
        "high,both readings agree,\n"
        "8220682,23,1,self,Intuitive Surgical Inc New (ISRG),,purchase,2021-01-05,2024-04-24,J,,"
        "medium,both readings agree,\n"
        "9106434,1,10,self,CORE MARK HOLDING,,,2014-03-25,,A,,low,resolved,no type marked\n"
        "9114448,,,,,,,,,,,,both readings agree,no transactions; letter\n"
    )
    rows, empty = read_csv(csv_path)
    assert empty == {"house:9114448"}
    pfe = rows["house:9107955"][0]
    assert (pfe.ticker, pfe.tx_type, pfe.amount_min, pfe.amount_max) == (
        "PFE",
        "sale_full",
        1001.0,
        15000.0,
    )
    isrg = rows["house:8220682"][0]
    assert isrg.ticker == "ISRG"  # from "(ISRG)" in the name
    assert (isrg.amount_min, isrg.amount_max) == (50000000.0, None)
    assert rows["house:9106434"][0].tx_type is None


def test_committed_csv_is_well_formed() -> None:
    rows, empty = read_csv(_DATA)
    assert len(rows) + len(empty) == 89
    flat = [r for rs in rows.values() for r in rs]
    assert len(flat) == 686
    assert all(r.amount_min is not None or r.amount_max is None for r in flat)
    assert {r.confidence for r in flat} <= {"high", "medium", "low"}
