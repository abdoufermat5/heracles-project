"""A delegated administrator only grants rights they may grant themselves."""

from __future__ import annotations

from heracles.acl import admin
from tests.acl.world import BASE, World, b64

SALES = f"ou=sales,{BASE}"


def _assignment(role: str, scope: str = "subtree", index: int = 90) -> str:
    return f"{index}:{scope}:{b64(role)}:{b64('*')}"


def _caller(w: World, template: str, *, on: str = BASE, scope: str = "subtree") -> str:
    """A user holding a role with ``template`` assigned on ``on``."""
    me = w.user("delegate")
    w.assign(on, w.acl_role("caller-role", template), [me], scope=scope)
    return me


def _unheld(w: World, me: str, role: str, *, at: str, scope: str = "subtree") -> list[str]:
    ev = w.evaluator(me)
    return admin.unheld_grants(
        w.client, [], [_assignment(role, scope)], at=at, delegable=ev.delegable
    )


def test_one_attribute_does_not_cover_the_whole_object() -> None:
    w = World()
    w.ensure(SALES)
    me = _caller(w, "0:user/user#telephoneNumber;rw")
    whole = w.acl_role("whole", "0:user/user;rw")
    phone = w.acl_role("phone", "0:user/user#telephoneNumber;rw")
    assert _unheld(w, me, whole, at=SALES) == ["user/user:rw"]
    assert _unheld(w, me, phone, at=SALES) == []


def test_each_attribute_is_checked() -> None:
    w = World()
    w.ensure(SALES)
    me = _caller(w, "0:user/user#telephoneNumber;rw")
    role = w.acl_role("two", "0:user/user#telephoneNumber;rw#userPassword;w")
    assert _unheld(w, me, role, at=SALES) == ["user/user#userpassword:w"]


def test_object_rights_cover_its_attributes() -> None:
    w = World()
    w.ensure(SALES)
    me = _caller(w, "0:user/user;rw")
    role = w.acl_role("phone", "0:user/user#telephoneNumber;rw")
    assert _unheld(w, me, role, at=SALES) == []


def test_base_rights_do_not_grant_on_the_subtree() -> None:
    w = World()
    me = _caller(w, "0:user/user;rw", on=SALES, scope="base")
    role = w.acl_role("editor", "0:user/user;rw")
    assert _unheld(w, me, role, at=SALES, scope="base") == []
    assert _unheld(w, me, role, at=SALES, scope="subtree") == ["user/user:rw"]


def test_self_only_rights_are_not_delegable() -> None:
    w = World()
    me = _caller(w, "0:user/user;srw")
    role = w.acl_role("editor", "0:user/user;rw")
    # on the caller's own entry, where their self-only rights do apply
    assert w.evaluator(me).permissions(me, "user/user").write
    assert _unheld(w, me, role, at=me, scope="base") == ["user/user:rw"]


def test_template_change_checked_where_the_role_is_assigned() -> None:
    w = World()
    w.ensure(SALES)
    me = _caller(w, "0:user/user;rw", on=SALES)
    stored = ["0:user/user;r"]
    role = w.acl_role("readers", *stored)
    w.assign(SALES, role, ["*"])
    ev = w.evaluator(me)

    def unheld(*saved: str) -> list[str]:
        return admin.unheld_template_grants(
            w.client, role, stored, list(saved), delegable=ev.delegable
        )

    assert unheld("0:user/user;rw") == []
    assert unheld("0:all;rwcdm") == ["all:rwcdm"]
    # assigned at the base too: the caller holds nothing there
    w.assign(BASE, role, ["*"])
    assert unheld("0:user/user;rw") == ["user/user:rw"]


def test_template_change_keeps_rights_it_already_granted() -> None:
    w = World()
    w.ensure(SALES)
    me = _caller(w, "0:user/user;rw", on=SALES)
    stored = ["0:group/ogroup;rw"]
    role = w.acl_role("mixed", *stored)
    w.assign(SALES, role, ["*"])
    saved = ["0:group/ogroup;rw,user/user;r"]
    ev = w.evaluator(me)
    assert admin.unheld_template_grants(w.client, role, stored, saved, delegable=ev.delegable) == []


def test_unassigned_role_template_grants_nothing_yet() -> None:
    w = World()
    me = _caller(w, "0:user/user;r")
    role = w.acl_role("idle", "0:user/user;r")
    ev = w.evaluator(me)
    assert (
        admin.unheld_template_grants(
            w.client, role, ["0:user/user;r"], ["0:all;rwcdm"], delegable=ev.delegable
        )
        == []
    )
