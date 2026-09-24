from congress_collector.parsers.scan_classification import ScanTier, classify_scan_tier


def test_classifies_20_prefix_ids_as_clean() -> None:
    assert classify_scan_tier("house:20016829") == ScanTier.CLEAN
    assert classify_scan_tier("house:20004847") == ScanTier.CLEAN


def test_classifies_8_or_9_prefix_ids_as_risky() -> None:
    assert classify_scan_tier("house:9107579") == ScanTier.RISKY
    assert classify_scan_tier("house:8218645") == ScanTier.RISKY


def test_classifies_unrecognized_shapes_as_unknown() -> None:
    assert classify_scan_tier("house:123") == ScanTier.UNKNOWN
    assert classify_scan_tier("house:200168290") == ScanTier.UNKNOWN  # 9 digits, not 8
    assert classify_scan_tier("house:71234567") == ScanTier.UNKNOWN  # doesn't start 20/8/9


def test_strips_chamber_prefix() -> None:
    assert classify_scan_tier("20016829") == ScanTier.CLEAN
