"""In-memory demo directory (``heracles serve --demo``).

Builds a small but realistic tree with departments, users, groups, roles and
delegated administration so the console can be tried without an LDAP server.
"""

from __future__ import annotations

from heracles.acl import serialise_assignment, serialise_role_value
from heracles.acl.model import AclAssignment, AclScope, RoleTemplateValue
from heracles.acl.parser import parse_role_value
from heracles.ldap.client import Modification
from heracles.ldap.memory import MemoryDirectory
from heracles.schema.legacy import ATTR, OC, PLUGIN_OBJECT_CLASSES

BASE = "dc=heracles,dc=test"
ADMIN_DN = f"uid=admin,ou=people,{BASE}"
DEMO_PASSWORD = "heracles"  # noqa: S105 - documented demo credential

_DEPARTMENTS = {
    "paris": "Paris office",
    "lyon": "Lyon office",
}

_PEOPLE = [
    # uid, givenName, sn, department ("" = base)
    ("admin", "Ada", "Admin", ""),
    ("jdoe", "John", "Doe", ""),
    ("asmith", "Alice", "Smith", "paris"),
    ("bmartin", "Bruno", "Martin", "paris"),
    ("cdupont", "Chloé", "Dupont", "lyon"),
    ("dlefevre", "David", "Lefèvre", "lyon"),
    ("helpdesk", "Hélène", "Desk", ""),
]


def _dept_base(dept: str) -> str:
    return f"ou={dept},{BASE}" if dept else BASE


def build_demo_directory() -> MemoryDirectory:
    """Return a populated :class:`MemoryDirectory` (every password is ``heracles``)."""
    d = MemoryDirectory(BASE)
    d.add(
        BASE,
        {
            "objectClass": [b"top", b"dcObject", b"organization"],
            "dc": [b"heracles"],
            "o": [b"Heracles demo"],
        },
    )
    for dept, description in _DEPARTMENTS.items():
        d.add(
            _dept_base(dept),
            {
                "objectClass": [b"organizationalUnit", OC.DEPARTMENT.encode()],
                "ou": [dept.encode()],
                "description": [description.encode()],
            },
        )
    for dept in ["", *_DEPARTMENTS]:
        for container in ("people", "groups", "roles"):
            d.add(
                f"ou={container},{_dept_base(dept)}",
                {"objectClass": [b"organizationalUnit"], "ou": [container.encode()]},
            )

    for uid, given, sn, dept in _PEOPLE:
        dn = f"uid={uid},ou=people,{_dept_base(dept)}"
        d.add(
            dn,
            {
                "objectClass": [b"inetOrgPerson", b"organizationalPerson", b"person"],
                "uid": [uid.encode()],
                "givenName": [given.encode()],
                "sn": [sn.encode()],
                "cn": [f"{given} {sn}".encode()],
                "mail": [f"{uid}@heracles.test".encode()],
                "userPassword": [b"{CLEARTEXT}" + DEMO_PASSWORD.encode()],
            },
        )
        d.set_password(dn, DEMO_PASSWORD)

    def user_dn(uid: str) -> str:
        dept = next(p[3] for p in _PEOPLE if p[0] == uid)
        return f"uid={uid},ou=people,{_dept_base(dept)}"

    d.add(
        f"cn=admins,ou=groups,{BASE}",
        {
            "objectClass": [b"groupOfNames"],
            "cn": [b"admins"],
            "member": [user_dn("admin").encode()],
        },
    )
    d.add(
        f"cn=lyon-staff,ou=groups,{_dept_base('lyon')}",
        {
            "objectClass": [b"groupOfNames"],
            "cn": [b"lyon-staff"],
            "member": [user_dn("cdupont").encode(), user_dn("dlefevre").encode()],
        },
    )
    d.add(
        f"cn=lyon-managers,ou=roles,{_dept_base('lyon')}",
        {
            "objectClass": [b"organizationalRole"],
            "cn": [b"lyon-managers"],
            "roleOccupant": [user_dn("cdupont").encode()],
        },
    )

    # --- sudo roles ------------------------------------------------------
    sudoers = f"ou=sudoers,{BASE}"
    d.add(sudoers, {"objectClass": [b"organizationalUnit"], "ou": [b"sudoers"]})
    d.add(
        f"cn=defaults,{sudoers}",
        {
            "objectClass": [b"sudoRole"],
            "cn": [b"defaults"],
            "description": [b"Global sudo options"],
            "sudoOption": [b"env_reset", b"requiretty", b"!authenticate"],
        },
    )
    d.add(
        f"cn=admin-all,{sudoers}",
        {
            "objectClass": [b"sudoRole"],
            "cn": [b"admin-all"],
            "description": [b"Administrators may run anything"],
            "sudoUser": [b"%admins"],
            "sudoHost": [b"ALL"],
            "sudoCommand": [b"ALL"],
            "sudoRunAsUser": [b"ALL"],
        },
    )

    # --- ACL roles -------------------------------------------------------
    acl_roles = f"ou=aclroles,{BASE}"
    d.add(acl_roles, {"objectClass": [b"organizationalUnit"], "ou": [b"aclroles"]})
    roles = {
        "full-admin": "0:all;cmdrw",
        "user-manager": (
            "0:user/user;cmdrw#userLock;rw,ogroup/ogroup;cmdrw,"
            "role/roleGeneric;r,department/department;r"
        ),
        "helpdesk": "0:user/user;r#userPassword;rw#userLock;rw,department/department;r",
        "self-service": (
            "0:user/user;sr#telephoneNumber;srw#mobile;srw#jpegPhoto;srw#userPassword;srw"
        ),
    }
    for cn, value in roles.items():
        parsed = parse_role_value(value)
        assert isinstance(parsed, RoleTemplateValue)
        d.add(
            f"cn={cn},{acl_roles}",
            {
                "objectClass": [OC.ACL_ROLE.encode()],
                "cn": [cn.encode()],
                ATTR.ACL_TEMPLATE: [serialise_role_value(parsed).encode()],
            },
        )

    def assignment(index: int, scope: AclScope, role: str, members: list[str]) -> bytes:
        return serialise_assignment(
            AclAssignment(
                index=index,
                scope=scope,
                role_dn=f"cn={role},{acl_roles}",
                members=tuple(members),
            )
        ).encode()

    base_acl = [
        assignment(0, AclScope.SUBTREE, "full-admin", [f"cn=admins,ou=groups,{BASE}"]),
        assignment(1, AclScope.SUBTREE, "helpdesk", [user_dn("helpdesk")]),
        assignment(2, AclScope.SUBTREE, "self-service", ["*"]),
    ]
    _add_acl(d, BASE, base_acl)
    lyon_managers = f"cn=lyon-managers,ou=roles,{_dept_base('lyon')}"
    _add_acl(
        d,
        _dept_base("lyon"),
        [assignment(0, AclScope.SUBTREE, "user-manager", [lyon_managers])],
    )
    d.set_schema_object_classes([*d.schema_object_classes(), *PLUGIN_OBJECT_CLASSES])
    _add_network_samples(d)
    return d


def _add_acl(d: MemoryDirectory, dn: str, values: list[bytes]) -> None:
    d.modify(
        dn,
        [
            Modification("add", "objectClass", [OC.ACL_ASSIGNMENT.encode()]),
            Modification("add", ATTR.ACL_ENTRY, values),
        ],
    )


def _add_network_samples(d: MemoryDirectory) -> None:
    """A DNS zone and a server with one interface (plugins: dns, systems)."""
    dns = f"ou=dns,{BASE}"
    d.add(dns, {"objectClass": [b"organizationalUnit"], "ou": [b"dns"]})
    zone = f"zoneName=heracles.test,{dns}"
    d.add(
        zone,
        {
            "objectClass": [b"dNSZone"],
            "zoneName": [b"heracles.test"],
            "relativeDomainName": [b"@"],
            "sOARecord": [
                b"ns1.heracles.test. hostmaster.heracles.test. 2026110701 3600 900 604800 86400"
            ],
            "nSRecord": [b"ns1.heracles.test."],
            "mXRecord": [b"10 mail.heracles.test."],
        },
    )
    for name, ip in (("ns1", "10.0.0.2"), ("www", "10.0.0.10"), ("mail", "10.0.0.20")):
        d.add(
            f"relativeDomainName={name},{zone}",
            {
                "objectClass": [b"dNSZone"],
                "zoneName": [b"heracles.test"],
                "relativeDomainName": [name.encode()],
                "aRecord": [ip.encode()],
            },
        )
    systems = f"ou=systems,{BASE}"
    servers = f"ou=servers,{systems}"
    d.add(systems, {"objectClass": [b"organizationalUnit"], "ou": [b"systems"]})
    d.add(servers, {"objectClass": [b"organizationalUnit"], "ou": [b"servers"]})
    server = f"cn=srv-web,{servers}"
    d.add(
        server,
        {
            "objectClass": [b"fdServer", b"ieee802Device", b"ipHost"],
            "cn": [b"srv-web"],
            "description": [b"Web server"],
            "fdMode": [b"unlocked"],
            "macAddress": [b"52:54:00:12:34:56"],
            "ipHostNumber": [b"10.0.0.10"],
        },
    )
    d.add(
        f"cn=eth0,{server}",
        {
            "objectClass": [b"fdNetworkInterface"],
            "cn": [b"eth0"],
            "macAddress": [b"52:54:00:12:34:56"],
            "ipHostNumber": [b"10.0.0.10"],
        },
    )
