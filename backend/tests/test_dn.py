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


def test_escaped_trailing_space_is_part_of_the_value() -> None:
    value = "cn=x\\ ,ou=a,dc=b"
    assert dn.split(value) == ["cn=x\\ ", "ou=a", "dc=b"]
    assert dn.rdn(value) == "cn=x\\ "
    assert dn.parent(value) == "ou=a,dc=b"
    # must not collapse into the single-RDN DN whose value is "x,ou=a"
    assert dn.normalize(value) != dn.normalize("cn=x\\,ou=a,dc=b")
    assert dn.depth(dn.normalize(value)) == 3


def test_unescaped_trailing_space_is_still_trimmed() -> None:
    assert dn.split("cn=x ,ou=a ") == ["cn=x", "ou=a"]
    assert dn.split("cn=x\\\\ ,ou=a") == ["cn=x\\\\", "ou=a"]  # escaped backslash, then space


def test_normalize_treats_equivalent_escapes_as_equal() -> None:
    reference = dn.normalize("cn=a\\,b,dc=x")
    assert dn.normalize("cn=a\\2cb,dc=x") == reference
    assert dn.normalize("CN=A\\2Cb , DC=X") == reference
    assert dn.normalize("cn=\\C3\\A9,dc=x") == dn.normalize("cn=é,dc=x")
    assert dn.normalize("cn=a\\=b,dc=x") == dn.normalize("cn=a=b,dc=x")
    assert dn.normalize("cn=a\\;b,dc=x") == dn.normalize("cn=a;b,dc=x")


def test_normalize_keeps_structure_of_special_values() -> None:
    assert dn.depth(dn.normalize("cn=a\\,b,dc=x")) == 2
    assert dn.normalize("cn=a\\\\,dc=x") == "cn=a\\\\,dc=x"
    assert dn.is_descendant("cn=a\\,b,ou=p,dc=x", "OU=P,DC=X")


def test_unescape_rdn_value() -> None:
    assert dn.unescape_rdn_value("a\\,b") == "a,b"
    assert dn.unescape_rdn_value("\\C3\\A9") == "é"
    assert dn.unescape_rdn_value("x\\ ") == "x "
    assert dn.unescape_rdn_value("plain") == "plain"
    assert dn.unescape_rdn_value("trailing\\") == "trailing\\"


def test_normalize_survives_lone_surrogates() -> None:
    assert dn.normalize("cn=\ud800\\,x,dc=y").endswith(",dc=y")
