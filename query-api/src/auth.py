"""JSON admin login va dependency bao ve cac route query bang JWT."""

import secrets

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, SecretStr, StrictStr

from ingestion.src.storage import StorageError

from .passwords import hash_password, verify_password
from .tokens import JWTConfigurationError, create_access_token, decode_access_token, jwt_settings
from .users import UserRepository


class SanitizedAuthRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request: Request):
            try:
                return await original(request)
            except RequestValidationError:
                # FastAPI mac dinh echo input trong 422, co the chua plaintext password.
                raise HTTPException(status_code=422, detail="Invalid login request") from None

        return handle


router = APIRouter(prefix="/auth", tags=["auth"], route_class=SanitizedAuthRoute)
# Username khong ton tai van verify mot hash that, tranh bo qua buoc hash ton thoi gian.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))
_bearer = HTTPBearer(auto_error=False)


def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """Verify JWT truoc khi query storage; missing/malformed token deu tra 401."""
    unauthorized = HTTPException(
        status_code=401, detail="Invalid or missing authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        return decode_access_token(credentials.credentials)
    except jwt.InvalidTokenError:
        raise unauthorized from None
    except JWTConfigurationError:
        raise HTTPException(status_code=503, detail="Authentication unavailable") from None


class LoginRequest(BaseModel):
    username: StrictStr
    password: SecretStr


def get_user_repository(request: Request) -> UserRepository:
    repository = request.app.state.user_repository
    if repository is None:
        raise HTTPException(status_code=503, detail="User storage unavailable")
    return repository


@router.post("/login")
def login(
    credentials: LoginRequest,
    response: Response,
    repository: UserRepository = Depends(get_user_repository),
) -> dict:
    try:
        jwt_settings()
    except JWTConfigurationError:
        raise HTTPException(status_code=503, detail="Authentication unavailable") from None

    try:
        user = repository.get(credentials.username) if credentials.username.strip() else None
    except StorageError:
        raise HTTPException(status_code=503, detail="User storage unavailable") from None

    stored_hash = user.get("password_hash") if user else None
    valid_password = verify_password(
        credentials.password.get_secret_value(),
        stored_hash if isinstance(stored_hash, str) else _DUMMY_HASH,
    )
    if (not valid_password or not user or user.get("role") != "admin"
            or user.get("username") != credentials.username):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    try:
        result = create_access_token(user["username"])
    except JWTConfigurationError:
        raise HTTPException(status_code=503, detail="Authentication unavailable") from None
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return result
