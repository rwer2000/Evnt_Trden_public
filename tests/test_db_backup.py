from datetime import UTC, datetime

from congress_collector.ops.db_backup import backup_object_key


def test_backup_object_key_is_date_stamped() -> None:
    when = datetime(2026, 9, 21, 3, 0, tzinfo=UTC)
    assert backup_object_key(when) == "congress_20260921.sql.gz"


def test_backup_object_key_pads_single_digit_month_and_day() -> None:
    when = datetime(2026, 1, 5, 3, 0, tzinfo=UTC)
    assert backup_object_key(when) == "congress_20260105.sql.gz"
