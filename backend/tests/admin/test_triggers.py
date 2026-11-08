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
    render_command,
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


def test_render_quotes_values() -> None:
    attrs = {"uid": ["jdoe; rm -rf /"], "cn": ["John Doe"]}
    assert (
        render_command("echo %uid% %CN% %missing%", attrs) == "echo 'jdoe; rm -rf /' 'John Doe' ''"
    )


def test_mask_attrs_hides_passwords() -> None:
    masked = mask_attrs({"userPassword": ["{SSHA}x"], "uid": ["a"]})
    assert masked["userPassword"] == ["********"]
    assert masked["uid"] == ["a"]


def test_run_hook_success_failure_timeout() -> None:
    ok = run_hook(TabHook("user", "check", "echo hello %uid%"), {"uid": ["bob"]})
    assert ok.ok and ok.output == "hello bob"
    bad = run_hook(TabHook("user", "check", "echo nope >&2; exit 3"), {})
    assert not bad.ok and bad.exit_code == 3 and bad.output == "nope"
    slow = run_hook(TabHook("user", "check", "sleep 5"), {}, timeout=0.2)
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


def test_events_run_hooks_and_abort_on_pre_failure(
    directory: MemoryDirectory, tmp_path: Path
) -> None:
    out = tmp_path / "out.txt"
    config_store.save_config(
        directory,
        {
            "tab_hooks": [
                f"posixAccount|postcreate|echo %uid% %callerUID% %callerCN% %dn% > {out}",
                "user|precreate|#exit 1",
                "user|premodify|echo refused; exit 2",
            ],
            "display_hook_output": True,
        },
    )
    events = TriggerEvents(directory, CALLER, TriggerSettings(registry=_Registry()))
    state = _state({"uid": [b"jdoe"]})
    events.pre_create(EventContext("user", USER, None, state))  # disabled hook: no abort
    events.post_create(EventContext("user", USER, None, state))
    assert out.read_text().strip() == f"jdoe boss Big Boss {USER}"
    with pytest.raises(ObjectValidationError) as exc:
        events.pre_modify(EventContext("user", USER, state, state, [Modification("delete", "x")]))
    assert exc.value.fields == {"_": "refused"}


def test_post_failures_are_warnings(directory: MemoryDirectory) -> None:
    config_store.save_config(directory, {"tab_hooks": ["user|postremove|echo broken >&2; exit 1"]})
    events = TriggerEvents(directory, CALLER, TriggerSettings(registry=_Registry()))
    state = _state({"uid": [b"jdoe"]})
    events.post_delete(EventContext("user", USER, state, None))
    assert events.warnings == ["broken"]


def test_inactive_tab_does_not_fire(directory: MemoryDirectory, tmp_path: Path) -> None:
    marker = tmp_path / "m"
    config_store.save_config(directory, {"tab_hooks": [f"posixAccount|postcreate|touch {marker}"]})
    events = TriggerEvents(directory, CALLER, TriggerSettings(registry=_Registry()))
    state = _state({"uid": [b"jdoe"]})
    state.tabs["posix"].active = False
    events.post_create(EventContext("user", USER, None, state))
    assert not marker.exists()
