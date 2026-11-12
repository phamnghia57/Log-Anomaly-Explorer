"""Typed JWTs bound to persistent sessions; legacy stateless tokens are rejected."""

import secrets
from datetime import datetime, timedelta, timezone
import jwt
from . import config

JWT_ALGORITHM = "HS256"


class JWTConfigurationError(ValueError):
    """Safe configuration error, never containing a secret."""


def jwt_settings() -> tuple[str, int]:
    try:
        secret = config.require_jwt_secret()
    except ValueError:
        raise JWTConfigurationError("JWT_SECRET must be configured") from None
    if len(secret.encode("utf-8")) < 32:
        raise JWTConfigurationError("JWT_SECRET must contain at least 32 bytes")
    for name, value in (("JWT_EXPIRY_SECONDS", config.JWT_EXPIRY_SECONDS),
                        ("AUTH_REFRESH_TTL_SECONDS", config.AUTH_REFRESH_TTL_SECONDS)):
        if type(value) is not int or value <= 0:
            raise JWTConfigurationError(f"{name} must be a positive integer")
        try:
            datetime.now(timezone.utc) + timedelta(seconds=value)
        except OverflowError:
            raise JWTConfigurationError(f"{name} is out of range") from None
    return secret, config.JWT_EXPIRY_SECONDS


def create_access_token(username: str, *, sid: str, auth_version: str,
                        session_expires_at: datetime) -> dict:
    secret, lifetime = jwt_settings()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    expires_at = min(now + timedelta(seconds=lifetime), session_expires_at)
    token = jwt.encode({
        "sub": username, "role": "admin", "sid": sid, "ver": auth_version,
        "token_use": "access", "iat": int(now.timestamp()), "exp": int(expires_at.timestamp()),
    }, secret, algorithm=JWT_ALGORITHM)
    return {"token": token, "expires_at": expires_at.isoformat(), "session_id": sid}


def create_refresh_token(username: str, *, sid: str, auth_version: str,
                         session_expires_at: datetime) -> str:
    secret, _ = jwt_settings()
    return jwt.encode({
        "sub": username, "role": "admin", "sid": sid, "ver": auth_version,
        "token_use": "refresh", "jti": secrets.token_urlsafe(32),
        "iat": int(datetime.now(timezone.utc).timestamp()), "exp": int(session_expires_at.timestamp()),
    }, secret, algorithm=JWT_ALGORITHM)


def _decode(token: str, token_use: str) -> dict:
    secret, _ = jwt_settings()
    try:
        claims = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM], options={
            "require": ["sub", "role", "exp", "iat", "sid", "ver", "token_use"]
                       + (["jti"] if token_use == "refresh" else []),
        })
    except (TypeError, ValueError, OverflowError):
        raise jwt.InvalidTokenError("Invalid token claims") from None
    if (any(not isinstance(claims[key], str) or not claims[key].strip() for key in ("sub", "sid", "ver"))
            or claims["role"] != "admin" or claims["token_use"] != token_use
            or type(claims["exp"]) is not int or type(claims["iat"]) is not int
            or (token_use == "refresh" and
                (not isinstance(claims["jti"], str) or not claims["jti"].strip()))):
        raise jwt.InvalidTokenError("Invalid token claims")
    return claims


def decode_access_token(token: str) -> dict:
    return _decode(token, "access")


def decode_refresh_token(token: str) -> dict:
    return _decode(token, "refresh")
