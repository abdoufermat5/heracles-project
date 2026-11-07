from heracles.schema import legacy


def test_constants_match_spec() -> None:
    assert legacy.APP_OU == "ou=fusiondirectory"
    assert legacy.OC.LOCK == "fdLockEntry"
    assert legacy.ATTR.SNAPSHOT_DATA == "gosaSnapshotData"
    assert legacy.RDN.LOCKS == "ou=locks,ou=fusiondirectory"
    assert legacy.OC.LOCK in legacy.COMPAT_OBJECT_CLASSES


def test_locked_password_regex() -> None:
    assert legacy.LOCKED_PASSWORD_RE.match("{SSHA}!abc")
    assert legacy.LOCKED_PASSWORD_RE.match(legacy.USER_LOCK_SENTINEL)
    assert not legacy.LOCKED_PASSWORD_RE.match("{SSHA}abc")
    assert not legacy.LOCKED_PASSWORD_RE.match("plain!")
