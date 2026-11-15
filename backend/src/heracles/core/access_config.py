"""The ``access`` configuration section (access requests, approvals and reviews).

::

    access:
      approvers: ["cn=access-approvers,ou=groups,dc=example,dc=org"]  # approve any request
      requestable: "(owner=*)"     # groups and roles people may ask for (LDAP filter)
      max_days: 365                # longest end date a request or a grant may get (0: none)
      mail:                        # mail template names (``mail_template`` objects); empty:
        request_submitted: ""      #   the built-in wording
        request_decided: ""
        review_assigned: ""

Read by ``serve`` and ``worker``, like the ``audit`` section.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field

log = structlog.get_logger(__name__)


class AccessMail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_submitted: str = ""
    request_decided: str = ""
    review_assigned: str = ""


class AccessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Groups (DNs) whose members may approve any request.
    approvers: list[str] = Field(default_factory=lambda: [])
    #: Groups and roles that may be requested: those matching this filter.
    requestable: str = "(owner=*)"
    #: Longest end date, in days from now (0: no limit, permanent grants allowed).
    max_days: int = Field(default=365, ge=0)
    mail: AccessMail = AccessMail()


_config = AccessConfig()


def configure_access(raw: Mapping[str, Any] | None) -> AccessConfig:
    """Read the ``access`` section; an invalid one is logged and replaced by the defaults."""
    global _config
    try:
        _config = AccessConfig.model_validate(dict(raw or {}))
    except ValueError as exc:
        log.warning("access.config_invalid", error=str(exc))
        _config = AccessConfig()
    return _config


def access_config() -> AccessConfig:
    return _config


__all__ = ["AccessConfig", "AccessMail", "access_config", "configure_access"]
