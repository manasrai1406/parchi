"""Password hashing with Argon2id (D-043). Passwords are never logged or stored."""

from functools import lru_cache
from secrets import token_urlsafe

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_LENGTH = 10
MAX_LENGTH = 128

# argon2-cffi's defaults: Argon2id with RFC 9106's low-memory profile.
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the hash was made with older settings and should be redone at login."""
    return _hasher.check_needs_rehash(password_hash)


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return hash_password(token_urlsafe(16))


def waste_time(password: str) -> None:
    """Check a password against nothing, so an unknown username takes as long to refuse
    as a wrong password and the timing does not reveal which usernames exist."""
    verify_password(_dummy_hash(), password)
