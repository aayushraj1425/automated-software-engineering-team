"""The dev encryption-key fallback announces itself (audit finding 2).

With ENGINE_ENCRYPTION_KEY unset, secrets at rest are encrypted with a key
derived from ENGINE_SERVICE_SECRET — fine for dev, dangerous in production.
Both process startups (API lifespan, worker on_startup) call
warn_if_derived_key(); these tests pin the check itself.
"""

import base64

from engine.config import get_settings
from engine.security.crypto import warn_if_derived_key


def test_missing_dedicated_key_warns(monkeypatch):
    monkeypatch.setattr(get_settings(), "engine_encryption_key", "")
    assert warn_if_derived_key() is True


def test_a_dedicated_key_is_silent(monkeypatch):
    key = base64.urlsafe_b64encode(b"k" * 32).decode()
    monkeypatch.setattr(get_settings(), "engine_encryption_key", key)
    assert warn_if_derived_key() is False
