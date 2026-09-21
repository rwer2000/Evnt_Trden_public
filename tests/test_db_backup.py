import gzip
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from congress_collector.ops.db_backup import backup_object_key, create_backup


def test_backup_object_key_is_date_stamped() -> None:
    when = datetime(2026, 9, 21, 3, 0, tzinfo=UTC)
    assert backup_object_key(when) == "congress_20260921.sql.gz"


def test_backup_object_key_pads_single_digit_month_and_day() -> None:
    when = datetime(2026, 1, 5, 3, 0, tzinfo=UTC)
    assert backup_object_key(when) == "congress_20260105.sql.gz"


def _fake_pg_dump(tmp_path: Path, *, stdout: str, exit_code: int) -> str:
    script = tmp_path / "fake_pg_dump"
    script.write_text(
        f"#!{sys.executable}\nimport sys\nsys.stdout.write({stdout!r})\nsys.exit({exit_code})\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_create_backup_gzip_compresses_pg_dump_stdout(tmp_path: Path) -> None:
    pg_dump_bin = _fake_pg_dump(tmp_path, stdout="-- fake schema dump\n", exit_code=0)

    result = create_backup("postgresql://irrelevant", pg_dump_bin=pg_dump_bin)

    assert gzip.decompress(result) == b"-- fake schema dump\n"


def test_create_backup_raises_on_pg_dump_failure(tmp_path: Path) -> None:
    pg_dump_bin = _fake_pg_dump(tmp_path, stdout="", exit_code=1)

    with pytest.raises(subprocess.CalledProcessError):
        create_backup("postgresql://irrelevant", pg_dump_bin=pg_dump_bin)
