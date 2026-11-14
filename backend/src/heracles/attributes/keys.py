"""Stable label keys of the ``TypeDescriptor``.

Every label, help text and option the API sends carries a key derived from the
declarations (type, tab, section, attribute, option value), never from the English
wording: renaming a label must not detach its translation. Keys are path-like, with
``/`` as the separator; every segment is percent-escaped so the key never contains
``.`` or ``:`` (both are separators in resource catalogues) and stays stable.

Shapes::

    type/<type>/tab/<tab>                              tab label
    type/<type>/tab/<tab>/help                         tab description
    type/<type>/tab/<tab>/section/<section>            section label
    type/<type>/attr/<attr>                            attribute label
    type/<type>/attr/<attr>/help                       attribute description
    type/<type>/attr/<attr>/option/<value>             option label
    type/<type>/attr/<attr>/item[/…]                   element of a list attribute
    type/<type>/attr/<attr>/field/<name>[/…]           field of a composite attribute
"""

from __future__ import annotations

_SAFE = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


def segment(value: str) -> str:
    """Escape one key segment: ASCII letters, digits, ``-`` and ``_`` are kept."""
    return "".join(chr(b) if chr(b) in _SAFE else f"%{b:02X}" for b in value.encode())


def help_key(key: str) -> str:
    """Key of the help text that belongs to the label keyed ``key``."""
    return f"{key}/help"


def option_key(key: str, value: str) -> str:
    """Key of the label of the option ``value`` of the attribute keyed ``key``."""
    return f"{key}/option/{segment(value)}"


def tab_key(type_name: str, tab_name: str) -> str:
    """Key of a tab label."""
    return f"type/{segment(type_name)}/tab/{segment(tab_name)}"


def section_key(type_name: str, tab_name: str, section_name: str) -> str:
    """Key of a section label."""
    return f"{tab_key(type_name, tab_name)}/section/{segment(section_name)}"


def attribute_key(type_name: str, attribute_name: str) -> str:
    """Key of an attribute label (also used for listing columns)."""
    return f"type/{segment(type_name)}/attr/{segment(attribute_name)}"


def item_key(key: str) -> str:
    """Key of the element descriptor of the list attribute keyed ``key``."""
    return f"{key}/item"


def field_key(key: str, field_name: str) -> str:
    """Key of a composite field descriptor of the attribute keyed ``key``."""
    return f"{key}/field/{segment(field_name)}"
