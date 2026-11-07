from heracles.ldap import dn


def test_normalize_and_descendant() -> None:
    assert dn.normalize("UID=John , OU=People,dc=Example") == "uid=john,ou=people,dc=example"
    assert dn.is_descendant("uid=a,ou=people,dc=x", "DC=X")
    assert not dn.is_descendant("dc=x", "dc=x", include_self=False)


def test_split_escaped_comma() -> None:
    assert dn.split(r"cn=Doe\, John,dc=x") == [r"cn=Doe\, John", "dc=x"]
    assert dn.parent("cn=a,dc=x") == "dc=x"
    assert dn.depth("cn=a,ou=b,dc=x") == 3


def test_join_keeps_escaped_trailing_space() -> None:
    assert dn.join("cn=a\\ ", "ou=people,", ",dc=x") == "cn=a\\ ,ou=people,dc=x"
    assert dn.join("cn=a\\,", "dc=x") == "cn=a\\,,dc=x"
    assert dn.join("", "ou=x ,", "dc=y") == "ou=x,dc=y"
