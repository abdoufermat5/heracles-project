"""ACL gates of the LDIF / CSV tools and the per-entry visibility filter of exports."""

from __future__ import annotations

from dataclasses import dataclass, field

from heracles.acl import AclEvaluator
from heracles.api.deps import CurrentUser
from heracles.api.domain import Domain, TypeAclPolicy
from heracles.api.errors import forbidden
from heracles.attributes import AnyAttribute
from heracles.ldap.client import Entry
from heracles.ldap.filter import Filter, matches, parse_filter
from heracles.objects import TypeInfo
from heracles.objects.model import Tab

#: ACL object of the LDIF import and export pages.
LDIF_OBJECT = "ldif/ldifManager"
#: ACL object of the CSV import page.
CSV_OBJECT = "csv/csvImport"
#: Attributes any reader of an entry may test in an export filter.
_OPEN_FILTER_ATTRS = frozenset({"objectclass"})


@dataclass(slots=True)
class Access:
    """What the connected user may do with the tools, plus the export visibility filter."""

    domain: Domain
    user: CurrentUser
    evaluator: AclEvaluator = field(init=False)
    _filters: dict[str, Filter] = field(init=False, default_factory=lambda: {})

    def __post_init__(self) -> None:
        self.evaluator = self.domain.evaluator(self.user)

    # -- gates ---------------------------------------------------------------------------------
    def can_export_ldif(self, dn: str) -> bool:
        return self.evaluator.permissions(dn, LDIF_OBJECT).read

    def can_import_ldif(self, dn: str) -> bool:
        return self.evaluator.permissions(dn, LDIF_OBJECT).write

    def can_import_csv(self, dn: str) -> bool:
        return self.evaluator.permissions(dn, CSV_OBJECT).write

    def require_export(self, dn: str) -> None:
        if not self.can_export_ldif(dn):
            raise forbidden("You are not allowed to export LDIF here")

    # -- entry visibility ----------------------------------------------------------------------
    def _types_of(self, entry: Entry) -> list[TypeInfo]:
        found: list[TypeInfo] = []
        for info in self.domain.registry.list():
            flt = self._filters.get(info.name)
            if flt is None:
                flt = self._filters[info.name] = parse_filter(info.type.filter)
            if matches(entry, flt):
                found.append(info)
        return found

    def visible(self, entry: Entry, *, types: list[TypeInfo] | None = None) -> Entry | None:
        """The part of ``entry`` the user may read, or ``None`` when nothing may be shown.

        Entries of a known type are shown when the main tab is readable, restricted to
        the attributes readable through the type's tabs (password-like attributes are
        never exported). Other entries need the LDIF read right at their own DN.
        """
        infos = self._types_of(entry) if types is None else types
        if not infos:
            return entry if self.can_export_ldif(entry.dn) else None
        policies = [(info, TypeAclPolicy(self.evaluator, info)) for info in infos]
        if not any(p.can_read(entry.dn, info.main_tab.name, "") for info, p in policies):
            return None
        shown: dict[str, list[bytes]] = {}
        for name, values in entry.attrs.items():
            decision = self._attribute_visible(entry.dn, name, policies)
            if decision:
                shown[name] = list(values)
        return Entry(entry.dn, shown)

    def filter_readable(self, entry: Entry, names: frozenset[str]) -> bool:
        """Whether every attribute a search filter tests is readable on ``entry``.

        A filter is an oracle on the attributes it names, evaluated before the export hides
        anything. Entries of a known type must expose each tested attribute through a
        readable tab; an attribute named by option (``attr;x``) is judged by its base name
        and one named by OID is refused. Other entries are shown whole or not at all.
        """
        infos = self._types_of(entry)
        if not infos:
            return True
        policies = [(info, TypeAclPolicy(self.evaluator, info)) for info in infos]
        for name in names - _OPEN_FILTER_ATTRS:
            base = name.partition(";")[0]
            if not base or base[0].isdigit():
                return False
            if not self._attribute_visible(entry.dn, base, policies):
                return False
        return True

    @staticmethod
    def _attribute_visible(
        dn: str, name: str, policies: list[tuple[TypeInfo, TypeAclPolicy]]
    ) -> bool:
        known = False
        wanted = name.lower()
        for info, policy in policies:
            for tab in info.tabs:
                attr = _find(tab, wanted)
                if attr is None:
                    continue
                known = True
                if attr.write_only:
                    continue
                if policy.can_read(dn, tab.name, attr.name):
                    return True
        # structural attributes (objectClass, RDN helpers...) described by no tab
        return not known


def _find(tab: type[Tab], lowered: str) -> AnyAttribute | None:
    for attr in tab.attributes():
        if attr.name.lower() == lowered:
            return attr
    return None
