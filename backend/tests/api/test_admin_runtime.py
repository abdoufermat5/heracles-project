"""The configuration stored in the directory takes effect without a restart."""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from heracles import demo
from heracles.api.domain import Domain
from heracles.api.settings import ApiSettings
from heracles.api.state import AppState
from heracles.api.v2 import admin
from heracles.auth.sessions import InMemorySessionStore
from heracles.core import config_store
from heracles.server import create_full_app


def _settings() -> ApiSettings:
    settings = ApiSettings(admin_dns=[], directory_labels={"main": "Demo directory"})
    settings.session.cookie_secure = False
    return settings


@pytest.fixture
def app() -> Iterator[FastAPI]:
    directory = demo.build_demo_directory()
    config_store.save_config(
        directory,
        {
            "password_min_length": 12,
            "session_lifetime": 99,
            "login_attribute": "mail",
            "user_rdn": "ou=staff",
            "acl_target_filter_limit": 7,
        },
    )
    built = create_full_app(_settings(), {"main": directory})
    yield built
    # the type classes are process-wide: put the defaults back
    domain = cast("Domain", built.state.domain)
    for type_name, rdn in admin._ORIGINAL_RDN.items():  # pyright: ignore[reportPrivateUsage]
        domain.registry.get(type_name).type.rdn = rdn


def test_startup_applies_the_stored_configuration(app: FastAPI) -> None:
    with TestClient(app, base_url="http://testserver"):
        state = cast("AppState", app.state.heracles)
        domain = cast("Domain", app.state.domain)
        assert state.policy.min_length == 12
        assert state.login_config.login_attribute == "mail"
        assert state.recovery.login_config.login_attribute == "mail"
        assert isinstance(state.sessions, InMemorySessionStore)
        assert state.sessions.idle_timeout == 99
        assert domain.acl_target_limit == 7
        assert domain.registry.get("user").type.rdn == "ou=staff"


def test_refresh_follows_changes_made_elsewhere(app: FastAPI) -> None:
    state = cast("AppState", app.state.heracles)
    domain = cast("Domain", app.state.domain)
    directory = state.directories["main"]
    admin.refresh_runtime(app)
    assert state.policy.min_length == 12
    config_store.save_config(directory, {"password_min_length": 20, "user_rdn": ""})
    admin.refresh_runtime(app)
    assert state.policy.min_length == 20
    # an emptied knob falls back to the type default
    assert domain.registry.get("user").type.rdn == "ou=people"
