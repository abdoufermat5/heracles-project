from datetime import UTC, datetime, timedelta, timezone

import pytest

from heracles.core.generalized_time import format_generalized_time, parse_generalized_time


def test_format() -> None:
    assert format_generalized_time(datetime(2024, 3, 5, 7, 8, 9, tzinfo=UTC)) == "20240305070809Z"
    naive = datetime(2024, 3, 5, 7, 8, 9)
    assert format_generalized_time(naive) == "20240305070809Z"
    paris = datetime(2024, 3, 5, 8, 8, 9, tzinfo=timezone(timedelta(hours=1)))
    assert format_generalized_time(paris) == "20240305070809Z"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("20240305070809Z", datetime(2024, 3, 5, 7, 8, 9, tzinfo=UTC)),
        ("20240305070809", datetime(2024, 3, 5, 7, 8, 9, tzinfo=UTC)),
        ("202403050708Z", datetime(2024, 3, 5, 7, 8, tzinfo=UTC)),
        ("2024030507Z", datetime(2024, 3, 5, 7, tzinfo=UTC)),
        ("20240305070809.5Z", datetime(2024, 3, 5, 7, 8, 9, 500000, tzinfo=UTC)),
        ("20240305070809,25Z", datetime(2024, 3, 5, 7, 8, 9, 250000, tzinfo=UTC)),
        ("20240305080809+0100", datetime(2024, 3, 5, 7, 8, 9, tzinfo=UTC)),
        ("20240305020809-05", datetime(2024, 3, 5, 7, 8, 9, tzinfo=UTC)),
    ],
)
def test_parse(text: str, expected: datetime) -> None:
    assert parse_generalized_time(text) == expected


@pytest.mark.parametrize(
    "bad", ["", "abc", "2024", "20241305070809Z", "20240305070809Zx", "20240305"]
)
def test_parse_invalid(bad: str) -> None:
    with pytest.raises(ValueError, match="GeneralizedTime"):
        parse_generalized_time(bad)


def test_round_trip() -> None:
    now = datetime(2030, 12, 31, 23, 59, 59, tzinfo=UTC)
    assert parse_generalized_time(format_generalized_time(now)) == now
