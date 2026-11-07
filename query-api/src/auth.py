"""Admin auth with persistent revocation and rotating refresh cookies."""

import secrets
from datetime import datetime, timezone
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, SecretStr, StrictStr
from ingestion.src.storage import StorageError
from . import config
from .passwords import hash_password, verify_password
from .sessions import SessionRepository, active_admin
from .tokens import JWTConfigurationError, decode_access_token, decode_refresh_token, jwt_settings
from .users import UserRepository

COOKIE_NAME = "lae_refresh"
COOKIE_PATH = "/api/auth"
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class SanitizedAuthRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request: Request):
            try:
                response = await original(request)
            except RequestValidationError:
                raise HTTPException(422, "Invalid login request", headers=NO_STORE) from None
            except HTTPException as exc:
                exc.headers = {**NO_STORE, **(exc.headers or {})}
                raise
            response.headers.update(NO_STORE)
            return response
        return handle


def protect_auth_post(request: Request) -> None:
    origin = request.headers.get("origin")
    if (request.headers.get("x-csrf-protection") != "1"
            or (origin is not None and (origin == "null" or origin not in config.AUTH_ALLOWED_ORIGINS))):
        raise HTTPException(403, "Invalid authentication origin")


router = APIRouter(prefix="/auth", tags=["auth"], route_class=SanitizedAuthRoute,
                   dependencies=[Depends(protect_auth_post)])
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))
_bearer = HTTPBearer(auto_error=False)


def get_user_repository(request: Request) -> UserRepository:
    repository = getattr(request.app.state, "user_repository", None)
    if repository is None:
        raise HTTPException(503, "User storage unavailable")
    return repository


def get_session_repository(request: Request) -> SessionRepository:
    repository = getattr(request.app.state, "session_repository", None)
    if repository is None:
        raise HTTPException(503, "Authentication unavailable")
    return repository


def unauthorized(*, expired=False) -> HTTPException:
    headers = {"WWW-Authenticate": "Bearer"}
    if expired:
        headers["X-Auth-Reason"] = "access_expired"
    return HTTPException(401, "Invalid or missing authentication token", headers=headers)


def require_admin(request: Request,
                  credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    if credentials is None:
        raise unauthorized()
    try:
        claims = decode_access_token(credentials.credentials)
        get_session_repository(request).validate(claims, get_user_repository(request))
        return claims
    except jwt.ExpiredSignatureError:
        raise unauthorized(expired=True) from None
    except jwt.InvalidTokenError:
        raise unauthorized() from None
    except (JWTConfigurationError, StorageError):
        raise HTTPException(503, "Authentication unavailable") from None


class LoginRequest(BaseModel):
    username: StrictStr
    password: SecretStr


def set_refresh_cookie(response: Response, token: str, expires: datetime) -> None:
    response.set_cookie(COOKIE_NAME, token, httponly=True, secure=config.AUTH_COOKIE_SECURE,
                        samesite="lax", path=COOKIE_PATH, expires=expires,
                        max_age=max(0, int(expires.timestamp()) - int(datetime.now(timezone.utc).timestamp())))


@router.post("/login")
def login(credentials: LoginRequest, response: Response,
          repository: UserRepository = Depends(get_user_repository),
          sessions: SessionRepository = Depends(get_session_repository)) -> dict:
    try:
        jwt_settings()
    except JWTConfigurationError:
        raise HTTPException(503, "Authentication unavailable") from None
    try:
        user = repository.get(credentials.username) if credentials.username.strip() else None
    except StorageError:
        raise HTTPException(503, "User storage unavailable") from None
    stored_hash = user.get("password_hash") if user else None
    valid_password = verify_password(credentials.password.get_secret_value(),
                                    stored_hash if isinstance(stored_hash, str) else _DUMMY_HASH)
    if not valid_password or not active_admin(user, credentials.username):
        raise HTTPException(401, "Invalid username or password")
    try:
        access, refresh, expires = sessions.start(user)
    except (JWTConfigurationError, StorageError, jwt.InvalidTokenError):
        raise HTTPException(503, "Authentication unavailable") from None
    set_refresh_cookie(response, refresh, expires)
    return access


@router.post("/refresh")
def refresh(request: Request, response: Response,
            repository: UserRepository = Depends(get_user_repository),
            sessions: SessionRepository = Depends(get_session_repository)) -> dict:
    try:
        token = request.cookies.get(COOKIE_NAME, "")
        claims = decode_refresh_token(token)
        access, replacement, expires = sessions.refresh(token, claims, repository)
    except jwt.InvalidTokenError:
        # A delayed error must not delete a newer login cookie.
        raise unauthorized() from None
    except (JWTConfigurationError, StorageError):
        raise HTTPException(503, "Authentication unavailable") from None
    set_refresh_cookie(response, replacement, expires)
    return access


@router.post("/logout", status_code=204)
def logout(request: Request, sessions: SessionRepository = Depends(get_session_repository)) -> Response:
    try:
        token = request.cookies.get(COOKIE_NAME)
        if token:
            try:
                claims = decode_refresh_token(token)
            except jwt.InvalidTokenError:
                claims = None
            if claims is not None:
                sessions.revoke(claims["sid"])
    except (JWTConfigurationError, StorageError):
        raise HTTPException(503, "Authentication unavailable") from None
    response = Response(status_code=204, headers=NO_STORE)
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH, httponly=True,
                           secure=config.AUTH_COOKIE_SECURE, samesite="lax")
    return response
