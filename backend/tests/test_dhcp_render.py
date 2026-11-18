"""The development DHCP renderer: base64 values and unsafe values reaching the daemon."""

from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _render_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "render_dhcpd", ROOT / "deploy" / "dev" / "dhcp" / "render.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["render_dhcpd"] = module
    spec.loader.exec_module(module)
    return module


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def test_renderer_decodes_base64_and_drops_unsafe_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _render_module()
    ldif = (
        "dn: cn=svc,ou=dhcp,dc=test\nobjectClass: dhcpService\ncn: svc\n"
        f"dhcpStatements:: {_b64('default-lease-time 600')}\n"
        f"dhcpStatements:: {_b64('on commit { execute("/bin/id"); }')}\n"
        'dhcpStatements: include "/etc/shadow"\n'
        f"dhcpOption:: {_b64('routers 10.0.0.1')}\n"
        f"dhcpOption:: {_b64('domain-name "a"' + chr(10) + 'b')}\n"
    )
    config, _ = module.render(module.parse_ldif(ldif))
    assert "default-lease-time 600;" in config
    assert "option routers 10.0.0.1;" in config
    for bad in ("execute", "include", "commit", "domain-name"):
        assert bad not in config
    assert "unsafe" in capsys.readouterr().err
