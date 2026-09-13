"""HMAC signing for webhook payloads."""

from __future__ import annotations

import hashlib
import hmac
import secrets

SIGNATURE_HEADER = "X-Hookflow-Signature"
SIGNATURE_PREFIX = "sha256="


def generate_secret() -> str:
    return secrets.token_hex(32)


def sign_payload(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def verify_signature(secret: str, body: bytes, signature: str) -> bool:
    expected = sign_payload(secret, body)
    return hmac.compare_digest(expected, signature)
