import json
import uuid

import pytest

from engine.db.models import PreviewCredential
from engine.db.session import session_scope
from engine.security.crypto import decrypt
from engine.security.preview_credentials import load_preview_credentials, validate_kubeconfig
from tests.conftest import auth_headers


def kubeconfig(**user_overrides):
    return json.dumps(
        {
            "apiVersion": "v1",
            "kind": "Config",
            "current-context": "development-preview",
            "clusters": [{"name": "preview", "cluster": {"server": "https://preview.example.com"}}],
            "contexts": [
                {
                    "name": "development-preview",
                    "context": {"cluster": "preview", "user": "release"},
                }
            ],
            "users": [
                {
                    "name": "release",
                    "user": {"token": "test-sensitive-cloud-token", **user_overrides},
                }
            ],
        }
    )


async def test_preview_credentials_are_encrypted_and_org_scoped(client):
    org_id = "org_preview_" + uuid.uuid4().hex[:10]
    admin = auth_headers("release_admin", org_id=org_id, org_role="admin")
    member = auth_headers("release_member", org_id=org_id, org_role="member")
    other = auth_headers("release_other", org_id="other_org", org_role="admin")
    raw = kubeconfig()
    response = await client.put("/v1/preview-credentials", headers=admin, json={"kubeconfig": raw})
    assert response.status_code == 200, response.text
    assert response.json()["configured"] is True
    assert "test-sensitive-cloud-token" not in response.text
    assert (await client.get("/v1/preview-credentials", headers=member)).json()["configured"]
    assert not (await client.get("/v1/preview-credentials", headers=other)).json()["configured"]
    async with session_scope() as db:
        row = await db.get(PreviewCredential, org_id)
        assert row is not None
        assert "test-sensitive-cloud-token" not in row.encrypted_credentials
        assert json.loads(decrypt(row.encrypted_credentials))["kubeconfig"] == raw
        assert (await load_preview_credentials(db, org_id))["kubeconfig"] == raw
    async with session_scope(user_id="stranger") as db:
        assert await db.get(PreviewCredential, org_id) is None
    assert (await client.delete("/v1/preview-credentials", headers=member)).status_code == 403
    assert (await client.delete("/v1/preview-credentials", headers=admin)).status_code == 204


async def test_preview_credential_writes_require_org_admin(client):
    assert (await client.get("/v1/preview-credentials")).status_code == 401
    assert (await client.get("/v1/preview-credentials", headers=auth_headers())).status_code == 400
    response = await client.put(
        "/v1/preview-credentials",
        headers=auth_headers("member", org_id="member_org", org_role="member"),
        json={"kubeconfig": kubeconfig()},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("field", ["exec", "auth-provider", "client-key", "tokenFile"])
async def test_preview_credential_rejects_plugins_without_echoing_secret(client, field):
    response = await client.put(
        "/v1/preview-credentials",
        headers=auth_headers("admin", org_id="invalid_org", org_role="admin"),
        json={"kubeconfig": kubeconfig(**{field: {"command": "test-sensitive-cloud-token"}})},
    )
    assert response.status_code == 422
    assert "test-sensitive-cloud-token" not in response.text


async def test_oversized_preview_credential_is_never_echoed(client):
    secret = "test-sensitive-cloud-token" * 12000
    response = await client.put(
        "/v1/preview-credentials",
        headers=auth_headers("admin", org_id="oversize_org", org_role="admin"),
        json={"kubeconfig": secret},
    )
    assert response.status_code == 422
    assert "test-sensitive-cloud-token" not in response.text


def test_production_context_cannot_be_stored():
    data = json.loads(kubeconfig())
    data["current-context"] = "production"
    data["contexts"][0]["name"] = "production"
    with pytest.raises(ValueError, match="Production"):
        validate_kubeconfig(json.dumps(data))
