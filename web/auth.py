import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from config import WEB_PASSWORD, WEB_USERNAME


def credentials_configured() -> bool:
    return bool(WEB_PASSWORD.strip())


def verify_login(username: str, password: str) -> bool:
    if not credentials_configured():
        return False
    user_ok = secrets.compare_digest(username, WEB_USERNAME)
    pass_ok = secrets.compare_digest(password, WEB_PASSWORD)
    return user_ok and pass_ok


def login_user(request: Request) -> None:
    request.session["authenticated"] = True


def logout_user(request: Request) -> None:
    request.session.clear()


def is_authenticated(request: Request) -> bool:
    return bool(request.session.get("authenticated"))


async def require_auth(request: Request) -> None:
    if not credentials_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Веб-панель не настроена: укажите WEB_USERNAME и WEB_PASSWORD в .env",
        )
    if not is_authenticated(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )


AuthRequired = Annotated[None, Depends(require_auth)]
