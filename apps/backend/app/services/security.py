"""Password hashing helpers (PBKDF2)."""
import hashlib
import hmac
import secrets

PBKDF2_ALGO = "pbkdf2_sha256"
PBKDF2_ITERS = 150_000  # reasonable default, adjust per environment/hardware
SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Derive a PBKDF2-HMAC-SHA256 hash for the password with a random salt."""
    if not isinstance(password, str) or password == "":
        raise ValueError("Password required")
    salt = secrets.token_bytes(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERS)
    return f"{PBKDF2_ALGO}${PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Verify a password against a stored PBKDF2 record."""
    try:
        algo, iters_s, salt_hex, hash_hex = stored.split("$", 3)
        if algo != PBKDF2_ALGO:
            return False
        iters = int(iters_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False
