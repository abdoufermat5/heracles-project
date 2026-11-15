"""SCIM 2.0 provisioning (RFC 7643 schema, RFC 7644 protocol) at ``/scim/v2``.

Implemented from the RFC text only. Layers, each owned by one module:

* :mod:`heracles.scim.errors`, :mod:`heracles.scim.schemas`: error type and URNs (shared).
* :mod:`heracles.scim.filter`: filter grammar -> AST -> LDAP filter (pure).
* :mod:`heracles.scim.patch`: PatchOp parsing and application to a resource dict (pure).
* :mod:`heracles.scim.projection`: ``attributes`` / ``excludedAttributes`` (pure).
* :mod:`heracles.scim.settings`: deployment settings (``api.scim``).
* :mod:`heracles.scim.service`: SCIM resources <-> Heracles ``user`` / ``group`` objects,
  through the object service of the request (ACL, validation, hooks, audit: no bypass).
* :mod:`heracles.scim.router`: the HTTP surface (API tokens only, SCIM error bodies).

Resources are plain ``dict[str, Any]`` in SCIM JSON shape, attribute names in their
canonical case (``userName``, ``name.familyName``, ``emails``...).

Decisions of this version:

* ``id`` is the value of the directory's ``entryUUID`` (setting ``id_attribute``); it
  survives renames and moves.
* ``externalId`` is not supported (accepted on input and ignored, never returned).
* A group needs at least one member (``groupOfNames``): creating one without members, or
  removing its last member, is a 400 ``invalidValue``.
* Group members are users only.
* Filters are compiled to LDAP and run through the object listing (with its read checks);
  a path that maps to no LDAP attribute is a 400 ``invalidFilter`` (no in-memory filtering).
"""
