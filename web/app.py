from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import database as db
from config import GUILD_ID, WEB_HOST, WEB_PORT, WEB_SECRET
from event_status import (
    FINISHED_STATUSES,
    STATUS_ACTIVE,
    STATUS_CANCELLED,
    STATUS_ENDED,
    STATUS_PENDING,
)
from utils import (
    event_time_from_iso,
    event_time_to_iso,
    parse_event_time_input,
    validate_future_time,
)
from web import auth
from web.discord_sync import sync_event_to_discord
from web.guild_info import get_guild_display, resolve_guild_id
from web.services import get_event_full, get_organizers_summary, list_events_for_web

WEB_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

app = FastAPI(title="Foldy's Event Bot — панель")
app.add_middleware(SessionMiddleware, secret_key=WEB_SECRET, max_age=60 * 60 * 24 * 7)
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

AuthRequired = Annotated[None, Depends(auth.require_auth)]


def _guild_id() -> int | None:
    return resolve_guild_id()


async def _render(request: Request, name: str, **context):
    guild = await get_guild_display()
    return templates.TemplateResponse(
        request,
        name,
        {
            "guild": guild,
            "flash": _pop_flash(request),
            **context,
        },
    )


def _flash(request: Request, message: str, level: str = "info") -> None:
    request.session["flash"] = {"message": message, "level": level}


def _pop_flash(request: Request) -> dict | None:
    return request.session.pop("flash", None)


def _time_input_value(event: dict) -> str:
    try:
        return event_time_from_iso(event["event_time"]).strftime("%d.%m.%Y %H:%M")
    except (ValueError, KeyError):
        return str(event.get("event_time", ""))


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 401:
        return RedirectResponse("/login", status_code=302)
    if exc.status_code == 503:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"configured": False, "error": exc.detail},
            status_code=503,
        )
    raise exc


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if auth.is_authenticated(request):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "configured": auth.credentials_configured(),
            "error": request.query_params.get("error"),
        },
    )


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    if not auth.credentials_configured():
        return RedirectResponse(
            "/login?error=" + quote("Задайте WEB_USERNAME и WEB_PASSWORD в .env"),
            status_code=303,
        )
    if not auth.verify_login(username, password):
        return RedirectResponse(
            "/login?error=" + quote("Неверный логин или пароль"),
            status_code=303,
        )
    auth.login_user(request)
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
async def logout(request: Request):
    auth.logout_user(request)
    return RedirectResponse("/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, _: AuthRequired):
    guild_id = _guild_id()
    stats: dict[str, int] = {}
    archived_count = 0
    if guild_id:
        for status in (STATUS_PENDING, STATUS_ACTIVE, STATUS_CANCELLED, STATUS_ENDED):
            events = await db.list_events(guild_id, status=status, limit=500)
            stats[status] = len(events)
        archived_count = await db.count_events_by_statuses(
            guild_id, FINISHED_STATUSES
        )
    return await _render(
        request,
        "dashboard.html",
        stats=stats,
        archived_count=archived_count,
    )


@app.post("/maintenance/cleanup-finished", response_class=HTMLResponse)
async def cleanup_finished(
    request: Request,
    _: AuthRequired,
    confirm: str = Form(""),
):
    guild_id = _guild_id()
    if not guild_id:
        _flash(request, "Укажите GUILD_ID в .env.", "error")
        return RedirectResponse("/", status_code=303)

    if confirm != "yes":
        _flash(request, "Отметьте подтверждение удаления.", "error")
        return RedirectResponse("/", status_code=303)

    deleted = await db.delete_events_by_statuses(guild_id, FINISHED_STATUSES)
    if deleted:
        _flash(
            request,
            f"Удалено из базы: {deleted} ивент(ов) (завершённые и отменённые).",
            "info",
        )
    else:
        _flash(request, "Нечего удалять — архив пуст.", "warning")
    return RedirectResponse("/", status_code=303)


@app.get("/events", response_class=HTMLResponse)
async def events_list(
    request: Request,
    _: AuthRequired,
    status: str | None = None,
):
    guild_id = _guild_id()
    events: list[dict] = []
    if guild_id:
        events = await list_events_for_web(guild_id, status=status or None)
    return await _render(
        request,
        "events.html",
        events=events,
        status=status or "",
    )


@app.get("/events/{event_id}", response_class=HTMLResponse)
async def event_detail(request: Request, event_id: int, _: AuthRequired):
    event = await get_event_full(event_id)
    if not event:
        return RedirectResponse("/events", status_code=302)
    return await _render(request, "event_detail.html", event=event)


@app.get("/events/{event_id}/edit", response_class=HTMLResponse)
async def event_edit_page(request: Request, event_id: int, _: AuthRequired):
    event = await get_event_full(event_id)
    if not event:
        return RedirectResponse("/events", status_code=302)
    if event.get("status") in FINISHED_STATUSES:
        _flash(request, "Завершённые и отменённые ивенты нельзя редактировать.", "error")
        return RedirectResponse(f"/events/{event_id}", status_code=303)
    return await _render(
        request,
        "event_edit.html",
        event=event,
        time_value=_time_input_value(event),
    )


@app.post("/events/{event_id}/edit")
async def event_edit_submit(
    request: Request,
    event_id: int,
    _: AuthRequired,
    title: str = Form(...),
    description: str = Form(...),
    roblox_mode: str = Form(...),
    event_time: str = Form(...),
):
    event = await db.get_event(event_id)
    if not event:
        return RedirectResponse("/events", status_code=303)
    if event.get("status") in FINISHED_STATUSES:
        _flash(request, "Ивент уже завершён или отменён.", "error")
        return RedirectResponse(f"/events/{event_id}", status_code=303)

    title = title.strip()[:256]
    description = description.strip()[:2000]
    roblox_mode = roblox_mode.strip()[:128]

    try:
        event_dt = parse_event_time_input(event_time.strip())
        if event.get("status") == STATUS_PENDING:
            validate_future_time(event_dt)
        time_iso = event_time_to_iso(event_dt)
    except ValueError as e:
        _flash(request, str(e), "error")
        return RedirectResponse(f"/events/{event_id}/edit", status_code=303)

    await db.update_event(
        event_id,
        title=title,
        description=description,
        roblox_mode=roblox_mode,
        event_time=time_iso,
    )

    ok, msg = await sync_event_to_discord(event_id)
    level = "info" if ok else "warning"
    _flash(request, f"Сохранено. {msg}", level)
    return RedirectResponse(f"/events/{event_id}", status_code=303)


@app.post("/events/{event_id}/cancel")
async def event_cancel(request: Request, event_id: int, _: AuthRequired):
    event = await db.get_event(event_id)
    if not event:
        return RedirectResponse("/events", status_code=303)
    if event.get("status") in FINISHED_STATUSES:
        _flash(request, "Ивент уже завершён или отменён.", "error")
        return RedirectResponse(f"/events/{event_id}", status_code=303)

    await db.set_event_status(event_id, STATUS_CANCELLED)
    ok, msg = await sync_event_to_discord(event_id)
    _flash(
        request,
        f"Ивент отменён. {msg}",
        "info" if ok else "warning",
    )
    return RedirectResponse(f"/events/{event_id}", status_code=303)


@app.post("/events/{event_id}/end")
async def event_end(request: Request, event_id: int, _: AuthRequired):
    event = await db.get_event(event_id)
    if not event:
        return RedirectResponse("/events", status_code=303)
    if event.get("status") != STATUS_ACTIVE:
        _flash(request, "Завершить можно только активный ивент.", "error")
        return RedirectResponse(f"/events/{event_id}", status_code=303)

    await db.set_event_status(event_id, STATUS_ENDED)
    ok, msg = await sync_event_to_discord(event_id)
    _flash(
        request,
        f"Ивент завершён. {msg}",
        "info" if ok else "warning",
    )
    return RedirectResponse(f"/events/{event_id}", status_code=303)


@app.get("/organizers", response_class=HTMLResponse)
async def organizers_page(request: Request, _: AuthRequired):
    guild_id = _guild_id()
    summary = None
    if guild_id:
        summary = await get_organizers_summary(guild_id)
    return await _render(request, "organizers.html", summary=summary)


def run():
    from web.server import start_web_panel_in_background

    if not start_web_panel_in_background():
        raise SystemExit(
            "Веб-панель не запущена. Задайте WEB_PASSWORD в .env "
            "или отключите через WEB_ENABLED=false."
        )
    import time

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
