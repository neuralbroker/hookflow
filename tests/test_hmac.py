"""HMAC sign/verify contract."""

from app.security import SIGNATURE_HEADER, sign_payload, verify_signature


def test_sign_verify_roundtrip():
    sig = sign_payload("secret-123", b'{"a":1}')
    assert sig.startswith("sha256=")
    assert verify_signature("secret-123", b'{"a":1}', sig) is True


def test_wrong_secret_or_body_fails():
    sig = sign_payload("secret-123", b'{"a":1}')
    assert verify_signature("other", b'{"a":1}', sig) is False
    assert verify_signature("secret-123", b'{"a":2}', sig) is False


def test_header_name():
    assert SIGNATURE_HEADER == "X-Hookflow-Signature"
