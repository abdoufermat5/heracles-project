from __future__ import annotations

from pathlib import Path

import pytest

from heracles.core import config_store
from heracles.ldap.client import Modification
from heracles.ldap.memory import MemoryDirectory
from heracles.objects.errors import ObjectValidationError
from heracles.objects.policy import EventContext
from heracles.objects.state import ObjectState, TabState
from heracles.triggers import (
    TabHook,
    TriggerEvents,
    TriggerSettings,
    apply_changes,
    mask_attrs,
    parse_hook,
    run_hook,
)

BASE = "dc=example,dc=test"
CALLER = f"uid=boss,ou=people,{BASE}"
USER = f"uid=jdoe,ou=people,{BASE}"


def test_parse_and_serialise_roundtrip() -> None:
    hook = parse_hook("posixAccount|postcreate|echo a | cat")
    assert hook == TabHook("posixAccount", "postcreate", "echo a | cat", True)
    assert hook is not None
    assert hook.serialise() == "posixAccount|postcreate|echo a | cat"
    off = parse_hook("user|check|#/bin/true")
    assert off is not None and not off.enabled and off.command == "/bin/true"
    assert off.serialise() == "user|check|#/bin/true"


@pytest.mark.parametrize("value", ["", "user|check", "user|nomode|ls", "|check|ls", "user|check|#"])
def test_parse_rejects_malformed(value: str) -> None:
    assert parse_hook(value) is None


def _script(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(0o755)
    return path


@pytest.mark.parametrize(
    "value",
    [
        "x'\"); touch /tmp/heracles-pwned-$$; echo (`id`)$(id) \\",
        '"${VAR:-"a\'b"}" ; touch /tmp/heracles-pwned-$$ #\'',
        "`touch /tmp/heracles-pwned-$$`",
    ],
)
def test_attribute_values_reach_the_script_only_as_environment(tmp_path: Path, value: str) -> None:
    _script(tmp_path, "show.sh", 'printf %s "$HRC_ATTR_SN"')
    result = run_hook(TabHook("user", "check", "show.sh"), {"sn": [value]}, scripts_dir=tmp_path)
    assert result.ok and result.output == value
    assert not list(Path("/tmp").glob("heracles-pwned-*"))


def test_multiple_values_are_joined_with_a_line_feed(tmp_path: Path) -> None:
    _script(tmp_path, "show.sh", 'printf %s "$HRC_ATTR_MAIL"')
    hook = TabHook("user", "check", "show.sh")
    result = run_hook(hook, {"mail": ["a@x", "b@x"]}, scripts_dir=tmp_path)
    assert result.output == "a@x\nb@x"


@pytest.mark.parametrize(
    "command",
    ["echo hi", "/bin/true", "../outside.sh", "sub/inner.sh", "link.sh", "plain.txt", "missing.sh"],
)
def test_only_bare_names_of_approved_executables_run(tmp_path: Path, command: str) -> None:
    approved = tmp_path / "approved"
    marker = tmp_path / "ran"
    _script(tmp_path, "outside.sh", f"touch {marker}")
    _script(approved, "inner.sh", f"touch {marker}")
    (approved / "sub").mkdir()
    _script(approved / "sub", "inner.sh", f"touch {marker}")
    (approved / "link.sh").symlink_to(tmp_path / "outside.sh")
    (approved / "plain.txt").write_text(f"touch {marker}")
    result = run_hook(TabHook("user", "check", command), {}, scripts_dir=approved)
    assert result.refused and not result.ok and not marker.exists()


def test_triggers_are_disabled_without_a_scripts_directory() -> None:
    result = run_hook(TabHook("user", "check", "true"), {}, scripts_dir=None)
    assert result.refused


def test_run_hook_does_not_leak_the_server_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HERACLES_SECRET_TEST", "hunter2")
    _script(tmp_path, "env.sh", "env")
    result = run_hook(TabHook("user", "check", "env.sh"), {}, scripts_dir=tmp_path)
    assert result.ok
    assert "hunter2" not in result.output and "HERACLES_SECRET_TEST" not in result.output


def test_timeout_kills_grandchildren_promptly(tmp_path: Path) -> None:
    import time

    _script(tmp_path, "slow.sh", "sleep 30 & sleep 30")
    started = time.monotonic()
    result = run_hook(TabHook("user", "check", "slow.sh"), {}, scripts_dir=tmp_path, timeout=0.3)
    assert result.timed_out
    assert time.monotonic() - started < 5


def test_mask_attrs_hides_passwords() -> None:
    masked = mask_attrs({"userPassword": ["{SSHA}x"], "uid": ["a"], "hrcToken": ["t"]})
    assert masked["userPassword"] == ["********"]
    assert masked["hrcToken"] == ["********"]
    assert masked["uid"] == ["a"]


def test_run_hook_success_failure_timeout(tmp_path: Path) -> None:
    _script(tmp_path, "ok.sh", 'echo hello "$HRC_ATTR_UID"')
    _script(tmp_path, "bad.sh", "echo nope >&2; exit 3")
    _script(tmp_path, "slow.sh", "sleep 5")
    ok = run_hook(TabHook("user", "check", "ok.sh"), {"uid": ["bob"]}, scripts_dir=tmp_path)
    assert ok.ok and ok.output == "hello bob"
    bad = run_hook(TabHook("user", "check", "bad.sh"), {}, scripts_dir=tmp_path)
    assert not bad.ok and bad.exit_code == 3 and bad.output == "nope"
    slow = run_hook(TabHook("user", "check", "slow.sh"), {}, scripts_dir=tmp_path, timeout=0.2)
    assert slow.timed_out and not slow.ok


def test_apply_changes() -> None:
    raw = {"sn": [b"Doe"], "mail": [b"a@x", b"b@x"]}
    out = apply_changes(
        raw,
        [
            Modification("replace", "SN", [b"Smith"]),
            Modification("delete", "mail", [b"a@x"]),
            Modification("add", "uid", [b"jdoe"]),
        ],
    )
    assert out == {"sn": [b"Smith"], "mail": [b"b@x"], "uid": [b"jdoe"]}


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"top", b"dcObject", b"organization"], "dc": [b"example"]})
    d.add(f"ou=people,{BASE}", {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    d.add(
        CALLER,
        {
            "objectClass": [b"inetOrgPerson"],
            "uid": [b"boss"],
            "cn": [b"Big Boss"],
            "sn": [b"Boss"],
            "mail": [b"boss@example.test"],
        },
    )
    return d


def _state(raw: dict[str, list[bytes]]) -> ObjectState:
    tabs = {"main": TabState(True, {}), "posix": TabState(True, {})}
    return ObjectState.build(USER, "user", tabs, raw, ["inetOrgPerson"])


class _FakeTab:
    def __init__(self, name: str, key: str) -> None:
        self.name, self.acl_key = name, key


class _FakeInfo:
    def __init__(self) -> None:
        self.tabs = [_FakeTab("main", "user"), _FakeTab("posix", "posixAccount")]


class _Registry:
    def get(self, name: str) -> _FakeInfo:
        return _FakeInfo()


def _events(directory: MemoryDirectory, scripts: Path) -> TriggerEvents:
    settings = TriggerSettings(registry=_Registry(), scripts_dir=scripts)
    return TriggerEvents(directory, CALLER, settings)


def test_events_run_hooks_and_abort_on_pre_failure(
    directory: MemoryDirectory, tmp_path: Path
) -> None:
    out = tmp_path / "out.txt"
    scripts = tmp_path / "scripts"
    _script(
        scripts,
        "log.sh",
        f'echo "$HRC_ATTR_UID $HRC_ATTR_CALLERUID $HRC_ATTR_CALLERCN $HRC_ATTR_DN" > {out}',
    )
    _script(scripts, "refuse.sh", "echo refused; exit 2")
    config_store.save_config(
        directory,
        {
            "tab_hooks": [
                "posixAccount|postcreate|log.sh",
                "user|precreate|#refuse.sh",
                "user|premodify|refuse.sh",
            ],
            "display_hook_output": True,
        },
    )
    events = _events(directory, scripts)
    state = _state({"uid": [b"jdoe"]})
    events.pre_create(EventContext("user", USER, None, state))  # disabled hook: no abort
    events.post_create(EventContext("user", USER, None, state))
    assert out.read_text().strip() == f"jdoe boss Big Boss {USER}"
    with pytest.raises(ObjectValidationError) as exc:
        events.pre_modify(EventContext("user", USER, state, state, [Modification("delete", "x")]))
    assert exc.value.fields == {"_": "refused"}


def test_secrets_of_the_object_are_not_handed_to_the_script(
    directory: MemoryDirectory, tmp_path: Path
) -> None:
    out = tmp_path / "env.txt"
    scripts = tmp_path / "scripts"
    _script(scripts, "dump.sh", f"env > {out}")
    config_store.save_config(directory, {"tab_hooks": ["user|postcreate|dump.sh"]})
    state = _state({"uid": [b"jdoe"], "userPassword": [b"{SSHA}hash-of-bob"]})
    _events(directory, scripts).post_create(EventContext("user", USER, None, state))
    text = out.read_text()
    assert "HRC_ATTR_UID=jdoe" in text and "hash-of-bob" not in text


def test_a_stored_hook_that_is_not_an_approved_script_is_skipped(
    directory: MemoryDirectory, tmp_path: Path
) -> None:
    marker = tmp_path / "m"
    config_store.save_config(
        directory,
        {"tab_hooks": [f"user|precreate|touch {marker}", "user|postcreate|echo x >&2; exit 1"]},
    )
    events = _events(directory, tmp_path)
    state = _state({"uid": [b"jdoe"]})
    events.pre_create(EventContext("user", USER, None, state))  # no abort, nothing ran
    events.post_create(EventContext("user", USER, None, state))
    assert not marker.exists() and events.warnings == []


def test_inactive_tab_does_not_fire(directory: MemoryDirectory, tmp_path: Path) -> None:
    marker = tmp_path / "m"
    scripts = tmp_path / "scripts"
    _script(scripts, "touch.sh", f"touch {marker}")
    config_store.save_config(directory, {"tab_hooks": ["posixAccount|postcreate|touch.sh"]})
    state = _state({"uid": [b"jdoe"]})
    state.tabs["posix"].active = False
    _events(directory, scripts).post_create(EventContext("user", USER, None, state))
    assert not marker.exists()


def test_output_that_is_not_utf8_does_not_break_the_hook(tmp_path: Path) -> None:
    _script(tmp_path, "latin.sh", "printf 'caf\\351'; exit 1")
    result = run_hook(TabHook("user", "check", "latin.sh"), {}, scripts_dir=tmp_path)
    assert not result.ok and result.exit_code == 1
    assert result.output.startswith("caf")


def test_the_attribute_values_are_not_logged(tmp_path: Path) -> None:
    from structlog.testing import capture_logs

    _script(tmp_path, "ok.sh", "true")
    _script(tmp_path, "bad.sh", "exit 2")
    hook = TabHook("user", "check", "ok.sh")
    with capture_logs() as logs:
        assert run_hook(hook, {"uid": ["bob"]}, scripts_dir=tmp_path).ok
        run_hook(TabHook("user", "check", "bad.sh"), {"uid": ["bob"]}, scripts_dir=tmp_path)
    assert logs
    assert "bob" not in repr(logs)
