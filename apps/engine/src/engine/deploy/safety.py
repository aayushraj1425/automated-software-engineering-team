"""Shared error type and secret scrubbing for the preview adapter."""

import re

MAX_ERROR_CHARS = 500


class PreviewError(Exception):
    """A preview step failed. The message is safe to show: it never carries
    credential text, only field names and short reasons."""


# Long runs of base64-ish characters are certificates, keys, or tokens.
_LONG_TOKEN = re.compile(r"[A-Za-z0-9+/=_\-]{64,}")
_PEM = re.compile(r"-----BEGIN [A-Z ]+-----.*?(-----END [A-Z ]+-----|$)", re.DOTALL)
_BEARER = re.compile(r"(?i)(bearer\s+)\S+")


def scrub(text: str, secrets: tuple[str, ...] = (), limit: int = MAX_ERROR_CHARS) -> str:
    """Remove known secret values and anything that looks like key material,
    then truncate. Used on every byte of CLI output before it can be shown."""
    cleaned = text
    for secret in sorted((s for s in secrets if s and len(s) >= 6), key=len, reverse=True):
        cleaned = cleaned.replace(secret, "[redacted]")
    cleaned = _PEM.sub("[redacted]", cleaned)
    cleaned = _BEARER.sub(r"\1[redacted]", cleaned)
    cleaned = _LONG_TOKEN.sub("[redacted]", cleaned)
    cleaned = cleaned.strip()
    if len(cleaned) > limit:
        cleaned = cleaned[:limit] + "..."
    return cleaned
