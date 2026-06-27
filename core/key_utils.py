"""
API key generation, parsing, and verification.

API keys are formatted as `qfk_<8-char-prefix>_<32-char-secret>`. The
prefix is used for indexed DB lookup (fast); the full key is verified
against a bcrypt hash (slow but only after lookup hits one row).

This is the Stripe-style prefixed-key pattern. The visible prefix lets
ops see which key a request used in logs without exposing the secret,
and makes leaked keys grep-able against the codebase.
"""
import re
import secrets

import bcrypt

# qfk_ literal + 8-char prefix + _ + remaining secret (URL-safe base64 chars)
_KEY_PATTERN = re.compile(r"^qfk_([A-Za-z0-9_-]{8})_([A-Za-z0-9_-]+)$")

# bcrypt work factor. 12 = 200ms/verify on modern hardware; high enough to 
# defend against offline cracking, low enough to not bottleneck auth.
_BCRYPT_ROUNDS = 12

def generate_api_key() -> tuple[str, str, str]:
    """
    Generate a new API key.
    
    Returns (full_key, prefix, key_hash):
    - full_key: shown to the user ONCE at creation, never retrievable.
    - prefix: stored in DB for O(1) indexed lookup.
    - key_hash: bcrypt hash of full_key, stored in DB for verification.
    """
    # 6 url-safe bytes -> 8 chars after b64 encoding
    prefix = secrets.token_urlsafe(6)[:8]
    # 24 url-safe bytes -> 32 chars after b64 encoding (~192 bits of entropy)
    secret = secrets.token_urlsafe(24)
    full_key = f"qfk_{prefix}_{secret}"

    key_hash = bcrypt.hashpw(
        full_key.encode("utf-8"),
        bcrypt.gensalt(rounds = _BCRYPT_ROUNDS),
    ).decode("utf-8")

    return full_key, prefix, key_hash

def parse_api_key(full_key: str) -> tuple[str, str] | None:
    """
    Parse a key into (prefix, secret_part). Returns None if malformed.

    The secret_part is returned for callers that want to inspect it; auth
    verification uses the full key against the bcrypt hash, not the parts.
    """
    if not isinstance(full_key, str):
        return None
    match = _KEY_PATTERN.match(full_key)
    if not match:
        return None
    return match.group(1), match.group(2)

def verify_api_key(full_key: str, key_hash: str) -> bool:
    """
    Constant-time verify of a key against its stored bcrypt hash.
    
    Returns False (not raises) for malformed input, so callers can use the
    same error path for 'wrong key' and 'malformed key' - prevents an 
    attacker from distinguishing 'this prefix doesn't exist' from 'this
    prefix exists but the secret is wrong' via timing or error messages.
    """
    if not isinstance(full_key, str) or not isinstance(key_hash, str):
        return False
    try:
        return bcrypt.checkpw(full_key.encode("utf-8"), key_hash.encode("utf-8"))
    except (ValueError, TypeError):
        # bcrypt raises ValueError on malformed hash (e.g. wrong format).
        # Treat as "doesn't match" rather than propagating.
        return False
    