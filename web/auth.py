import re
import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

import database as db
from config import WEB_DEV_PASSWORD, WEB_DEV_USERNAME
from web.passwords import verify_password

ROLE_DEVELOPER = "developer"
ROLE_ADMIN = "admin"

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")


def credentials_configured() -> bool:
    return bool(WEB_DEV_PASSWORD.strip())


def developer_username() -> str:
    return WEB_DEV_USERNAME


def is_developer_username(username: str) -> bool:
    return secrets.compare_digest(
        username.strip().lower(),
        WEB_DEV_USERNAME.strip().lower(),
    )


def validate_panel_username(username: str) -> str | None:
    name = username.strip()
    if not _USERNAME_RE.fullmatch(name):
        return "Логин: 3–32 символа, латиница, цифры и _."
    if is_developer_username(name):
        return "Этот логин зарезервирован для разработчика."
    return None


def verify_developer_login(username: str, password: str) -> bool:
    if not credentials_configured():
        return False
    user_ok = secrets.compare_digest(
        username.strip().lower(),
        WEB_DEV_USERNAME.strip().lower(),
    )
    pass_ok = secrets.compare_digest(password, WEB_DEV_PASSWORD)
    return user_ok and pass_ok


async def authenticate(username: str, password: str) -> tuple[str, str] | None:
    """Возвращает (username, role) или None."""
    name = username.strip()
    if not name or not password:
        return None
    if verify_developer_login(name, password):
        return WEB_DEV_USERNAME, ROLE_DEVELOPER
    panel_user = await db.get_web_panel_user(name)
    if panel_user and verify_password(password, panel_user["password_hash"]):
        return panel_user["username"], ROLE_ADMIN
    return None


def login_user(request: Request, username: str, role: str) -> None:
    request.session["authenticated"] = True
    request.session["username"] = username
    request.session["role"] = role


def logout_user(request: Request) -> None:
    request.session.clear()


def is_authenticated(request: Request) -> bool:
    return bool(request.session.get("authenticated"))


async def validate_session(request: Request) -> bool:
    """Проверяет, что сессия ещё действительна (аккаунт не удалён)."""
    if not is_authenticated(request):
        return False
    role = request.session.get("role")
    username = request.session.get("username", "")
    if role == ROLE_DEVELOPER:
        if is_developer_username(username):
            return True
        logout_user(request)
        return False
    if role == ROLE_ADMIN:
        if await db.get_web_panel_user(username):
            return True
        request.session.clear()
        request.session["login_notice"] = "deleted"
        return False
    logout_user(request)
    return False


def session_user(request: Request) -> dict | None:
    if not is_authenticated(request):
        return None
    return {
        "username": request.session.get("username", ""),
        "role": request.session.get("role", ""),
        "is_developer": request.session.get("role") == ROLE_DEVELOPER,
    }


async def require_auth(request: Request) -> None:
    if not credentials_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Веб-панель не настроена: укажите WEB_DEV_PASSWORD (или WEB_PASSWORD) в .env",
        )
    if not await validate_session(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )


async def require_developer(request: Request) -> None:
    await require_auth(request)
    if request.session.get("role") != ROLE_DEVELOPER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Только разработчик может управлять учётными записями.",
        )


AuthRequired = Annotated[None, Depends(require_auth)]
DevRequired = Annotated[None, Depends(require_developer)]
