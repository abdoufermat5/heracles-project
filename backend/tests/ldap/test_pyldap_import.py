import importlib.util

import pytest

from heracles.ldap.config import DirectoryConfig
from heracles.ldap.pyldap import LdapUnavailableError, PyLdapDirectory


@pytest.mark.skipif(importlib.util.find_spec("ldap") is not None, reason="python-ldap installed")
def test_clear_error_without_python_ldap() -> None:
    cfg = DirectoryConfig.model_validate({"id": "a", "uri": "ldap://x", "base_dn": "dc=x"})
    with pytest.raises(LdapUnavailableError, match="'ldap' extra"):
        PyLdapDirectory(cfg)
