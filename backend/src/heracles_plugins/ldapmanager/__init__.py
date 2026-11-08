"""LDIF and CSV import / export tools.

ACL objects: ``ldif/ldifManager`` (LDIF export needs read, LDIF import needs write; the import
bypasses object-level validation) and ``csv/csvImport`` (CSV import needs write; entries are
created through the normal object path, so validation, ACLs and hooks apply).

Also serves the raw LDIF of one object: ``GET /api/v2/objects/{type}/{dn}/ldif``.
"""

from __future__ import annotations

from heracles.objects import Plugin
from heracles_plugins.ldapmanager.router import build_router

PLUGIN_NAME = "ldapmanager"


def plugin() -> Plugin:
    """Entry point of the ldapmanager plugin."""
    return Plugin(name=PLUGIN_NAME, version="0.1.0", api_routers=(build_router,))
