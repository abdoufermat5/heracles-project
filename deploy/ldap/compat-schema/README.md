# Compatibility schema (not distributed)

Heracles manages directories that already carry the "compatibility schema"
expected by Heracles. Those schema files belong to
the existing installation and are **not distributed** with Heracles.

To run the integration tests against objects that use those classes, the
operator copies the `.ldif` schema files from an existing installation into
this directory before the first start of the test server:

```
deploy/ldap/compat-schema/*.ldif
```

The directory is mounted read-only at `/schemas` in the test container
(`LDAP_CUSTOM_SCHEMA_DIR`). Its contents are git-ignored; only this README is
tracked. Without the files the test server still works, but compatibility
objectClasses will be rejected by the server.
