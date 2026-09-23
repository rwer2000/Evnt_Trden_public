"""Throwaway diagnostic: dump raw extracted words for a handful of House
PTR filings that classified as electronic but parsed zero transactions,
to see what's actually different about their layout. Not part of the
regular pipeline -- delete after use."""

from congress_collector.parsers.house_ptr import (
    _group_lines,
    extract_pages_words,
    is_electronic,
    parse_ptr_transactions,
)
from congress_collector.storage.supabase_storage import download

SAMPLE_OBJECT_KEYS = [
    "house/2015/20002307.pdf",
    "house/2016/20004345.pdf",
    "house/2017/20006456.pdf",
    "house/2018/20008662.pdf",
    "house/2019/20010919.pdf",
    "house/2020/20012366.pdf",
    "house/2021/20017909.pdf",
    "house/2022/20020047.pdf",
    "house/2023/20022453.pdf",
    "house/2024/20024662.pdf",
    "house/2026/20034178.pdf",
]


def main() -> None:
    for key in SAMPLE_OBJECT_KEYS:
        print(f"\n===== {key} =====")
        content = download(key)
        pages_words = extract_pages_words(content)
        electronic = is_electronic(pages_words)
        results = parse_ptr_transactions(pages_words)
        all_text = [w.text for words in pages_words for w in words]
        has_200 = any("200?" in t for t in all_text)
        print(f"pages={len(pages_words)} electronic={electronic} has_200marker={has_200} "
              f"n_transactions={len(results)} total_words={len(all_text)}")

        if pages_words:
            lines = _group_lines(pages_words[0])
            print("--- first page, first 25 lines (x0-sorted words) ---")
            for line in lines[:25]:
                text = " ".join(w.text for w in line)
                print(f"  top={line[0].top:.1f} x0s={[round(w.x0,1) for w in line]} text={text!r}")


if __name__ == "__main__":
    main()
