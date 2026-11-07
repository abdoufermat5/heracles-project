"""End-to-end API v2 tests for the DHCP plugin."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

import heracles_plugins.dhcp as dhcp
from heracles.api.settings import ApiSettings
from heracles.demo import BASE, build_demo_directory
from heracles.server import create_full_app

PARIS = f"ou=paris,{BASE}"


def q(dn: str) -> str:
    return quote(dn, safe="")


class Api:
    """Small helper around TestClient handling CSRF and login."""

    def __init__(self, client: TestClient) -> None:
        self.client = client
        token = client.get("/api/v2/auth/csrf").json()["token"]
        self.headers = {"X-CSRF-Token": token}

    def login(self, username: str, password: str = "heracles") -> Api:
        r = self.post(
            "/auth/login", {"directory": "main", "username": username, "password": password}
        )
        assert r.status_code == 200, r.text
        token = self.client.get("/api/v2/auth/csrf").json()["token"]
        self.headers = {"X-CSRF-Token": token}
        return self

    def get(self, path: str, **params: Any) -> Any:
        return self.client.get(f"/api/v2{path}", params=params)

    def post(self, path: str, body: Any = None) -> Any:
        return self.client.post(f"/api/v2{path}", json=body, headers=self.headers)

    def patch(self, path: str, body: Any) -> Any:
        return self.client.patch(f"/api/v2{path}", json=body, headers=self.headers)

    def delete(self, path: str) -> Any:
        return self.client.delete(f"/api/v2{path}", headers=self.headers)


@pytest.fixture
def app_client() -> Iterator[TestClient]:
    directory = build_demo_directory()
    directory.set_schema_object_classes([*directory.schema_object_classes(), "dhcpservice"])
    settings = ApiSettings(
        admin_dns=[],
        directory_labels={"main": "Demo directory"},
        enable_docs=True,
    )
    settings.session.cookie_secure = False
    app = create_full_app(settings, {"main": directory})
    app.include_router(dhcp.router, prefix="/api/v2")
    with TestClient(app) as client:
        yield client


def api(app_client: TestClient, user: str) -> Api:
    return Api(app_client).login(user)


# ---------------------------------------------------------------------------
# 1. Type registry and descriptors
# ---------------------------------------------------------------------------


def test_dhcp_types_listed(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    r = a.get("/types")
    assert r.status_code == 200
    names = [t["name"] for t in r.json()]
    for expected in (
        "dhcp_configuration",
        "dhcp_shared_network",
        "dhcp_subnet",
        "dhcp_pool",
        "dhcp_group",
        "dhcp_host",
        "dhcp_class",
        "dhcp_subclass",
        "dhcp_tsig_key",
        "dhcp_dns_zone",
        "dhcp_failover_peer",
    ):
        assert expected in names


def test_dhcp_descriptor(app_client: TestClient) -> None:
    a = api(app_client, "admin")
    r = a.get("/types/dhcp_configuration")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "dhcp_configuration"
    assert data["category"] == "network"
    assert len(data["tabs"]) == 1
    assert data["tabs"][0]["name"] == "main"

    host_r = a.get("/types/dhcp_host")
    assert host_r.status_code == 200
    host_data = host_r.json()
    attrs = [
        attr["name"]
        for section in host_data["tabs"][0]["sections"]
        for attr in section["attributes"]
    ]
    assert "fixed_address" in attrs
    assert "dhcpHWAddress" in attrs


# ---------------------------------------------------------------------------
# 2. Objects CRUD flow
# ---------------------------------------------------------------------------


def test_objects_flow_crud(app_client: TestClient) -> None:
    a = api(app_client, "admin")

    # 1. Create configuration under Paris
    r_cfg = a.post(
        "/objects/dhcp_configuration",
        {
            "base": PARIS,
            "tabs": {
                "main": {
                    "values": {
                        "cn": "paris-dhcp",
                        "dhcpComments": "Paris DHCP Service",
                        "dhcpOption": ["option routers 192.168.1.1", "domain-name paris.test"],
                    }
                }
            },
        },
    )
    assert r_cfg.status_code == 201, r_cfg.text
    cfg_dn = r_cfg.json()["dn"]
    assert cfg_dn == f"cn=paris-dhcp,ou=dhcp,{PARIS}"

    # Verify read
    r_get_cfg = a.get(f"/objects/dhcp_configuration/{q(cfg_dn)}")
    assert r_get_cfg.status_code == 200
    assert r_get_cfg.json()["tabs"]["main"]["values"]["cn"] == "paris-dhcp"
    assert r_get_cfg.json()["tabs"]["main"]["values"]["dhcpOption"] == [
        "routers 192.168.1.1",
        'domain-name "paris.test"',
    ]

    # 2. Create subnet under configuration
    r_sub = a.post(
        "/objects/dhcp_subnet",
        {
            "base": cfg_dn,
            "tabs": {
                "main": {
                    "values": {
                        "cn": "192.168.1.0",
                        "dhcpNetMask": 24,
                        "dhcpRange": ["192.168.1.50 192.168.1.100"],
                    }
                }
            },
        },
    )
    assert r_sub.status_code == 201, r_sub.text
    subnet_dn = r_sub.json()["dn"]
    assert subnet_dn == f"cn=192.168.1.0,{cfg_dn}"

    # 3. Create host under subnet
    r_host = a.post(
        "/objects/dhcp_host",
        {
            "base": subnet_dn,
            "tabs": {
                "main": {
                    "values": {
                        "cn": "host-laptop",
                        "dhcpHWAddress": {"type": "ethernet", "mac": "aa:bb:cc:11:22:33"},
                        "fixed_address": "192.168.1.55",
                    }
                }
            },
        },
    )
    assert r_host.status_code == 201, r_host.text
    host_dn = r_host.json()["dn"]

    # Verify host read
    r_get_host = a.get(f"/objects/dhcp_host/{q(host_dn)}")
    assert r_get_host.status_code == 200
    host_vals = r_get_host.json()["tabs"]["main"]["values"]
    assert host_vals["fixed_address"] == "192.168.1.55"
    assert host_vals["dhcpHWAddress"] == {"type": "ethernet", "mac": "aa:bb:cc:11:22:33"}

    # 4. Patch host fixed_address
    r_patch = a.patch(
        f"/objects/dhcp_host/{q(host_dn)}",
        {"tabs": {"main": {"values": {"fixed_address": "192.168.1.56"}}}},
    )
    assert r_patch.status_code == 200
    assert r_patch.json()["tabs"]["main"]["values"]["fixed_address"] == "192.168.1.56"

    # 5. Delete subnet -> triggers recursive delete of host
    r_del = a.delete(f"/objects/dhcp_subnet/{q(subnet_dn)}")
    assert r_del.status_code == 204

    # Host and subnet must be gone
    assert a.get(f"/objects/dhcp_host/{q(host_dn)}").status_code == 404
    assert a.get(f"/objects/dhcp_subnet/{q(subnet_dn)}").status_code == 404
    # Configuration still exists
    assert a.get(f"/objects/dhcp_configuration/{q(cfg_dn)}").status_code == 200


# ---------------------------------------------------------------------------
# 3. Validation errors via API
# ---------------------------------------------------------------------------


def test_api_validation_errors(app_client: TestClient) -> None:
    a = api(app_client, "admin")

    r_cfg = a.post(
        "/objects/dhcp_configuration",
        {"base": PARIS, "tabs": {"main": {"values": {"cn": "val-dhcp"}}}},
    )
    assert r_cfg.status_code == 201
    cfg_dn = r_cfg.json()["dn"]

    # Invalid subnet network
    r_bad_sub = a.post(
        "/objects/dhcp_subnet",
        {
            "base": cfg_dn,
            "tabs": {
                "main": {
                    "values": {
                        "cn": "192.168.1.5",
                        "dhcpNetMask": 24,
                    }
                }
            },
        },
    )
    assert r_bad_sub.status_code == 422
    assert "main.cn" in r_bad_sub.json()["error"]["fields"]

    # Disallowed child section (pool directly under configuration)
    r_disallowed = a.post(
        "/objects/dhcp_pool",
        {"base": cfg_dn, "tabs": {"main": {"values": {"cn": "pool-direct"}}}},
    )
    assert r_disallowed.status_code == 422
    assert "main.cn" in r_disallowed.json()["error"]["fields"]


# ---------------------------------------------------------------------------
# 4. Tree endpoint via API
# ---------------------------------------------------------------------------


def test_dhcp_tree_endpoint(app_client: TestClient) -> None:
    # Unauthenticated request (no session cookie)
    r_unauth = app_client.get("/api/v2/dhcp/tree?dn=cn=none")
    assert r_unauth.status_code == 401

    a = api(app_client, "admin")
    r_cfg = a.post(
        "/objects/dhcp_configuration",
        {"base": PARIS, "tabs": {"main": {"values": {"cn": "tree-dhcp"}}}},
    )
    cfg_dn = r_cfg.json()["dn"]

    r_net = a.post(
        "/objects/dhcp_shared_network",
        {"base": cfg_dn, "tabs": {"main": {"values": {"cn": "shared-1"}}}},
    )
    net_dn = r_net.json()["dn"]

    a.post(
        "/objects/dhcp_subnet",
        {"base": net_dn, "tabs": {"main": {"values": {"cn": "10.0.0.0", "dhcpNetMask": 24}}}},
    )

    # Valid tree query
    r_tree = a.get("/dhcp/tree", dn=cfg_dn)
    assert r_tree.status_code == 200
    raw_tree: object = r_tree.json()
    assert isinstance(raw_tree, list)
    tree_data = cast("list[dict[str, Any]]", raw_tree)
    assert len(tree_data) == 1
    root = tree_data[0]
    assert root["dn"] == cfg_dn
    assert root["type"] == "dhcp_configuration"
    assert root["label"] == "tree-dhcp"
    assert "dhcp_shared_network" in root["allowed_children"]
    root_children = cast("list[dict[str, Any]]", root["children"])
    assert len(root_children) == 1
    child = root_children[0]
    assert child["type"] == "dhcp_shared_network"
    child_children = cast("list[dict[str, Any]]", child["children"])
    assert len(child_children) == 1
    sub_child = child_children[0]
    assert sub_child["type"] == "dhcp_subnet"
    assert sub_child["label"] == "10.0.0.0"

    # Non-existent DN
    r_not_found = a.get("/dhcp/tree", dn=f"cn=missing,{PARIS}")
    assert r_not_found.status_code == 404
