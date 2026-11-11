from heracles.schema import names as schema


def test_constants_match_expected_identifiers() -> None:
    assert schema.APP_OU == "ou=heracles"
    assert schema.OC.LOCK == "hrcLockEntry"
    assert schema.ATTR.SNAPSHOT_DATA == "hrcSnapshotData"
    assert schema.RDN.LOCKS == "ou=locks,ou=heracles"
    assert schema.OC.LOCK in schema.CORE_OBJECT_CLASSES


def test_locked_password_regex() -> None:
    assert schema.LOCKED_PASSWORD_RE.match("{SSHA}!abc")
    assert schema.LOCKED_PASSWORD_RE.match(schema.USER_LOCK_SENTINEL)
    assert not schema.LOCKED_PASSWORD_RE.match("{SSHA}abc")
    assert not schema.LOCKED_PASSWORD_RE.match("plain!")
