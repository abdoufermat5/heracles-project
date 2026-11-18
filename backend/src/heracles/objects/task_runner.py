"""Scheduled task runners a plugin contributes (see :class:`heracles.objects.registry.Plugin`)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from heracles.auth.mail import Mailer
from heracles.ldap.client import DirectoryClient

if TYPE_CHECKING:
    from heracles.objects.registry import TypeRegistry


@dataclass(frozen=True, slots=True)
class TaskRunContext:
    """What a runner receives for one pass over one directory."""

    directory: DirectoryClient
    now: datetime
    #: The plugin's settings object (``registry.settings[plugin.name]``).
    settings: Any
    #: ``None`` when no mail server is configured (runners with ``needs_mailer`` are skipped).
    mailer: Mailer | None
    registry: TypeRegistry
    #: Public address of the console, for links in e-mails.
    base_url: str = ""
    #: The application database (lease and run reports live there too); runners keep their
    #: own state in it (``None`` in unit tests that do not need one).
    database: Any = None
    #: Id of the directory being processed (``directories`` key of the configuration).
    directory_id: str = ""
    #: Normalised DNs of the administrators (their rights are not read from the ACLs).
    admin_dns: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class TaskRunner:
    """A callable examining the tasks of one kind and processing the due ones.

    ``run`` returns the plugin's ``TaskReport`` (integer fields are the run's counters).
    """

    name: str
    run: Callable[[TaskRunContext], Any]
    #: Name of the task object type the runner serves (links runs to the task list).
    kind: str = ""
    needs_mailer: bool = False
