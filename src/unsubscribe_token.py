"""Stateless HMAC-signed unsubscribe tokens, same scheme as app/utils/unsubscribe.py.
Kept as a standalone copy (rather than importing across the app/ package
boundary) since facebook/ runs as its own process with its own env file."""

import hashlib
import hmac
import os


def generate_token(email_id: int) -> str:
    secret = os.environ.get("SECRET_KEY", "change-this").encode()
    return hmac.new(secret, str(email_id).encode(), hashlib.sha256).hexdigest()


def verify_token(email_id: int, token: str) -> bool:
    return hmac.compare_digest(generate_token(email_id), token or "")
