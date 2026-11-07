from heracles.core.snapshots import _parse_timestamp, _timestamp  # pyright: ignore[reportPrivateUsage]


def test_timestamp_uses_historical_format() -> None:
    assert _timestamp(1_700_000_000.123456, 0) == "1700000000-012345600"
    assert _timestamp(1_700_000_000.999999, 1) == "1700000001-000000000"


def test_parse_both_formats() -> None:
    assert _parse_timestamp("1700000000-012345600") == (1_700_000_000, 123_456)
    assert _parse_timestamp("1700000000-123456") == (1_700_000_000, 123_456)
    assert _parse_timestamp("1700000000") == (1_700_000_000, 0)
    assert _parse_timestamp("bogus") is None
