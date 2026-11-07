import pytest

from heracles.ldap.memory import MemoryDirectory

LDIF = """\
dn: dc=heracles,dc=test
objectClass: dcObject
objectClass: organization
dc: heracles
o: Heracles

dn: ou=people,dc=heracles,dc=test
objectClass: organizationalUnit
ou: people

dn: uid=alice,ou=people,dc=heracles,dc=test
objectClass: inetOrgPerson
uid: alice
cn: Alice
sn: A
displayName:: Q2Fmw6k=

dn: ou=sub,ou=people,dc=heracles,dc=test
objectClass: organizationalUnit
ou: sub

dn: uid=carol,ou=sub,ou=people,dc=heracles,dc=test
objectClass: inetOrgPerson
uid: carol
cn: Carol
sn: C
"""


@pytest.fixture
def directory() -> MemoryDirectory:
    return MemoryDirectory.from_ldif(LDIF)
