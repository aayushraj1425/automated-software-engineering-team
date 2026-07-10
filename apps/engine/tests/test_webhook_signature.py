"""HMAC verification of GitHub webhook signatures — the endpoint's only auth."""

import hashlib
import hmac

from engine.github import verify_webhook_signature

_SECRET = "shhh-webhook-secret"
_BODY = b'{"action":"opened","number":7}'


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_a_correct_signature_verifies():
    assert verify_webhook_signature(_SECRET, _BODY, _sign(_SECRET, _BODY)) is True


def test_a_wrong_signature_is_rejected():
    assert verify_webhook_signature(_SECRET, _BODY, _sign("other-secret", _BODY)) is False


def test_a_tampered_body_is_rejected():
    good = _sign(_SECRET, _BODY)
    assert verify_webhook_signature(_SECRET, _BODY + b" ", good) is False


def test_a_missing_header_is_rejected():
    assert verify_webhook_signature(_SECRET, _BODY, None) is False


def test_an_unprefixed_header_is_rejected():
    bare = hmac.new(_SECRET.encode(), _BODY, hashlib.sha256).hexdigest()  # no "sha256=" prefix
    assert verify_webhook_signature(_SECRET, _BODY, bare) is False


def test_an_empty_secret_rejects_everything():
    # Fail closed: with no configured secret, even a technically-valid-looking
    # signature must not authenticate.
    assert verify_webhook_signature("", _BODY, _sign("", _BODY)) is False
