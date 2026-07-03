import time

import jwt

from tests.conftest import auth_headers


async def test_chat_requires_token(client):
    resp = await client.post("/v1/chat", json={"message": "hello"})
    assert resp.status_code == 401


async def test_chat_rejects_garbage_token(client):
    resp = await client.post(
        "/v1/chat",
        json={"message": "hello"},
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert resp.status_code == 401


async def test_chat_rejects_wrong_secret(client):
    now = int(time.time())
    token = jwt.encode(
        {"sub": "user_test", "iat": now, "exp": now + 60}, "wrong-secret", algorithm="HS256"
    )
    resp = await client.post(
        "/v1/chat", json={"message": "hello"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


async def test_chat_rejects_expired_token(client):
    now = int(time.time())
    token = jwt.encode(
        {"sub": "user_test", "iat": now - 120, "exp": now - 60},
        "test-service-secret",
        algorithm="HS256",
    )
    resp = await client.post(
        "/v1/chat", json={"message": "hello"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


async def test_conversations_require_token(client):
    resp = await client.get("/v1/conversations")
    assert resp.status_code == 401


async def test_valid_token_accepted(client):
    resp = await client.get("/v1/conversations", headers=auth_headers())
    assert resp.status_code == 200
