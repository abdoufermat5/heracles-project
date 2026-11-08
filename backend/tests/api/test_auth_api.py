def test_branding_is_public_and_configurable() -> None:
    from fastapi.testclient import TestClient

    from heracles.api.app import create_app
    from heracles.api.settings import ApiSettings, BrandingSettings
    from tests.auth.fakes import FakeDirectory

    default = TestClient(create_app(ApiSettings(), {"main": FakeDirectory()}))
    assert default.get("/api/v2/branding").json() == {
        "organization": "",
        "logo_url": None,
        "tagline": "",
    }
    branded = ApiSettings(
        branding=BrandingSettings(organization="Example Corp", logo_url="/logo.svg", tagline="IT")
    )
    client = TestClient(create_app(branded, {"main": FakeDirectory()}))
    assert client.get("/api/v2/branding").json() == {
        "organization": "Example Corp",
        "logo_url": "/logo.svg",
        "tagline": "IT",
    }
