from pathlib import Path

import pytest

from heracles.ldap.config import ConfigError, load_settings

YAML = """\
directories:
  - id: main
    label: Main
    uri: ldap://ldap.test
    bind_dn: cn=admin,dc=heracles,dc=test
    bind_password: secret
    base_dn: dc=heracles,dc=test
    starttls: true
    timeout: 5
  - id: other-dir
    uri: ldaps://other.test
    base_dn: dc=other
"""

TOML = """\
[[directories]]
id = "main"
uri = "ldap://ldap.test"
base_dn = "dc=heracles,dc=test"
"""


def test_yaml_file(tmp_path: Path) -> None:
    f = tmp_path / "c.yaml"
    f.write_text(YAML)
    s = load_settings(f, {})
    main = s.get("main")
    assert main.starttls and main.timeout == 5
    assert main.bind_password.get_secret_value() == "secret"
    assert "secret" not in repr(main)
    assert s.get("other-dir").bind_dn == ""
    with pytest.raises(KeyError):
        s.get("nope")


def test_toml_via_env_path(tmp_path: Path) -> None:
    f = tmp_path / "c.toml"
    f.write_text(TOML)
    s = load_settings(environ={"HERACLES_CONFIG": str(f)})
    assert s.directories[0].uri == "ldap://ldap.test"


def test_env_overrides(tmp_path: Path) -> None:
    f = tmp_path / "c.yml"
    f.write_text(YAML)
    env = {
        "HERACLES_DIRECTORY_MAIN_BIND_PASSWORD": "from-env",
        "HERACLES_DIRECTORY_OTHER_DIR_STARTTLS": "true",
    }
    s = load_settings(f, env)
    assert s.get("main").bind_password.get_secret_value() == "from-env"
    assert s.get("other-dir").starttls is True


def test_env_only_single_directory() -> None:
    env = {
        "HERACLES_LDAP_URI": "ldap://x",
        "HERACLES_LDAP_BASE_DN": "dc=x",
        "HERACLES_LDAP_BIND_DN": "cn=a,dc=x",
    }
    s = load_settings(environ=env)
    assert [d.id for d in s.directories] == ["default"]
    assert s.get("default").bind_dn == "cn=a,dc=x"


def test_nothing_configured() -> None:
    assert load_settings(environ={}).directories == []


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("a.yaml", "directories: nope"),
        ("a.yaml", "- just\n- a list"),
        ("a.yaml", "directories:\n  - id: a\n    uri: x\n"),  # missing base_dn
        (
            "a.yaml",
            "directories:\n  - {id: a, uri: x, base_dn: y}\n  - {id: a, uri: x, base_dn: y}",
        ),
        ("a.toml", "not = [valid"),
        ("a.json", "{}"),
    ],
)
def test_invalid(tmp_path: Path, name: str, content: str) -> None:
    f = tmp_path / name
    f.write_text(content)
    with pytest.raises(ConfigError):
        load_settings(f, {})


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_settings(tmp_path / "absent.yaml", {})
