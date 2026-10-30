"""Phat/verify JWT admin voi algorithm allowlist co dinh."""

from datetime import datetime, timedelta, timezone

import jwt

from . import config

JWT_ALGORITHM = "HS256"


class JWTConfigurationError(ValueError):
    """Cau hinh JWT khong dung duoc; khong chua gia tri secret."""


def jwt_settings() -> tuple[str, int]:
    try:
        secret = config.require_jwt_secret()
    except ValueError:
        raise JWTConfigurationError("JWT_SECRET must be configured") from None
    if len(secret.encode("utf-8")) < 32:
        raise JWTConfigurationError("JWT_SECRET must contain at least 32 bytes")
    lifetime = config.JWT_EXPIRY_SECONDS
    if type(lifetime) is not int or lifetime <= 0:
        raise JWTConfigurationError("JWT_EXPIRY_SECONDS must be a positive integer")
    return secret, lifetime


def create_access_token(username: str) -> dict:
    secret, lifetime = jwt_settings()
    try:
        expires_at = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=lifetime)
    except OverflowError:
        raise JWTConfigurationError("JWT_EXPIRY_SECONDS is out of range") from None
    token = jwt.encode(
        {"sub": username, "role": "admin", "exp": int(expires_at.timestamp())},
        secret, algorithm=JWT_ALGORITHM,
    )
    return {"token": token, "expires_at": expires_at.isoformat()}


def decode_access_token(token: str) -> dict:
    secret, _ = jwt_settings()
    try:
        claims = jwt.decode(
            token, secret, algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "role", "exp"]},
        )
    except (TypeError, ValueError, OverflowError):
        raise jwt.InvalidTokenError("Invalid token claims") from None
    if (not isinstance(claims["sub"], str) or not claims["sub"].strip()
            or claims["role"] != "admin" or type(claims["exp"]) is not int):
        raise jwt.InvalidTokenError("Invalid admin token claims")
    return claims
