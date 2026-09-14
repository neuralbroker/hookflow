# HookFlow security

## What exists

- Per-endpoint HMAC-SHA256 secrets (`X-Hookflow-Signature: sha256=...` over raw
  JSON body). Receivers verify with `app.security.verify_signature`.
  Secrets are generated with `secrets.token_hex(32)` when not supplied.
- Input validation: endpoint URL must be http(s), max 2000 chars; payload must
  be JSON-serializable and ≤ `max_body_bytes` (default 256KB); idempotency keys
  ≤ 128 chars; pagination bounds enforced.
- No secrets in code: `Settings` reads `.env`; `.env.example` contains only
  non-secret defaults. `.gitignore` excludes `.env` and `*.db`.

## What does NOT exist (honest gaps)

- No multi-tenant auth: anyone with network access can register endpoints and
  ingest. Endpoint secrets authenticate *receivers*, not *producers*.
  Fix: per-tenant API keys (planned).
- No TLS in Compose: terminate TLS at a reverse proxy / LB in production.
- Rate limits are per-endpoint delivery fairness, not anti-abuse on ingest.
- Secrets are stored in plaintext in the DB. Acceptable for MVP; rotate via
  re-registration. A KMS envelope is overkill at this stage.

## Receiver verification (Python)

```python
import hmac, hashlib
expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
assert hmac.compare_digest(expected, request.headers["X-Hookflow-Signature"])
```
