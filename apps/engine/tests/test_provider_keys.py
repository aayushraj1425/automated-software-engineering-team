"""Bring-your-own provider keys: encryption at rest, the API, and resolution.

The resolution test monkeypatches litellm's completion call and proves the
router hands it the caller's key — and falls back to None (the .env keys)
when the caller has none. Design note: docs/architecture/PROVIDER_KEYS.md.
"""

import uuid

import pytest
from sqlalchemy import select

from engine.config import get_settings
from engine.db.models import ProviderKey
from engine.db.session import session_scope
from engine.llm.keys import api_key_for_model, provider_keys_var
from engine.llm.router import model_router
from engine.security.crypto import DecryptionError, decrypt, encrypt
from tests.conftest import auth_headers


def _headers() -> dict[str, str]:
    return auth_headers(f"user_{uuid.uuid4().hex[:8]}")


# ── Encryption at rest ───────────────────────────────────────────────────────


def test_encrypt_roundtrip_and_uniqueness():
    token = encrypt("sk-ant-verysecret")
    assert decrypt(token) == "sk-ant-verysecret"
    assert "verysecret" not in token
    assert encrypt("sk-ant-verysecret") != token  # a fresh nonce every time


def test_tampered_ciphertext_is_rejected():
    token = encrypt("sk-ant-verysecret")
    tampered = token[:-6] + ("AAAAAA" if not token.endswith("AAAAAA") else "BBBBBB")
    with pytest.raises(DecryptionError):
        decrypt(tampered)


# ── The API ──────────────────────────────────────────────────────────────────


async def test_set_list_delete_a_key(client):
    headers = _headers()
    resp = await client.put(
        "/v1/provider-keys/anthropic", json={"key": "sk-ant-verysecret-1234"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "provider": "anthropic",
        "last4": "1234",
        "updated_at": resp.json()["updated_at"],
    }

    listed = (await client.get("/v1/provider-keys", headers=headers)).json()
    assert [(k["provider"], k["last4"]) for k in listed] == [("anthropic", "1234")]
    assert "key" not in listed[0]  # the key never leaves the engine, masked or not

    deleted = await client.delete("/v1/provider-keys/anthropic", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get("/v1/provider-keys", headers=headers)).json() == []


async def test_setting_again_replaces_the_key(client):
    headers = _headers()
    await client.put("/v1/provider-keys/gemini", json={"key": "old-key-0000-aaaa"}, headers=headers)
    await client.put("/v1/provider-keys/gemini", json={"key": "new-key-0000-bbbb"}, headers=headers)
    listed = (await client.get("/v1/provider-keys", headers=headers)).json()
    assert [(k["provider"], k["last4"]) for k in listed] == [("gemini", "bbbb")]


async def test_key_is_stored_encrypted(client):
    headers = _headers()
    await client.put(
        "/v1/provider-keys/openai", json={"key": "sk-proj-verysecret-zzzz"}, headers=headers
    )
    async with session_scope() as session:
        row = (
            (await session.execute(select(ProviderKey).where(ProviderKey.provider == "openai")))
            .scalars()
            .first()
        )
        assert row is not None
        assert "verysecret" not in row.encrypted_key
        assert decrypt(row.encrypted_key) == "sk-proj-verysecret-zzzz"


async def test_unknown_provider_is_rejected(client):
    resp = await client.put(
        "/v1/provider-keys/skynet", json={"key": "whatever-key-123"}, headers=_headers()
    )
    assert resp.status_code == 400


async def test_keys_are_owner_scoped(client):
    owner = _headers()
    await client.put(
        "/v1/provider-keys/anthropic", json={"key": "sk-ant-owners-key-1"}, headers=owner
    )
    stranger = _headers()
    assert (await client.get("/v1/provider-keys", headers=stranger)).json() == []


# ── Resolution: the caller's key reaches the model call ─────────────────────


def test_api_key_for_model_prefers_the_callers_key():
    token = provider_keys_var.set({"anthropic": "sk-ant-mine"})
    try:
        assert api_key_for_model("anthropic/claude-opus-4-8") == "sk-ant-mine"
        assert api_key_for_model("gemini/text-embedding-004") is None  # .env fallback
    finally:
        provider_keys_var.reset(token)


async def test_router_hands_litellm_the_callers_key(monkeypatch):
    import litellm

    captured: dict = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)

        class _Message:
            content = "ok"

        class _Choice:
            message = _Message()

        class _Response:
            choices = [_Choice()]
            usage = None

        return _Response()

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(get_settings(), "llm_fake", False)

    # Whatever model the planner tier maps to, bring a key for its provider.
    planner_provider = get_settings().model_planner.split("/", 1)[0]
    token = provider_keys_var.set({planner_provider: "sk-mine-1234"})
    try:
        await model_router.complete("planner", [{"role": "user", "content": "hi"}])
    finally:
        provider_keys_var.reset(token)
    assert captured["model"] == get_settings().model_planner
    assert captured["api_key"] == "sk-mine-1234"

    captured.clear()
    await model_router.complete("planner", [{"role": "user", "content": "hi"}])
    assert captured["api_key"] is None  # no user key: litellm reads the .env
