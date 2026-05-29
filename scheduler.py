import asyncio
import logging
from datetime import datetime

import discord

import database as db
from event_message import start_event_now
from utils import event_time_from_iso, get_timezone

logger = logging.getLogger(__name__)

# Если предстоящих ивентов нет
_IDLE_INTERVAL = 60.0
# Минимальная пауза между циклами (сек)
_MIN_INTERVAL = 0.5
# Дальше этого — грубый опрос раз в N сек (ивент ещё не скоро)
_COARSE_INTERVAL = 30.0
# За сколько секунд до старта переходим на точное ожидание
_PRECISE_WINDOW = 120.0


async def check_events(bot: discord.Client) -> None:
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            sleep_for = await _process_pending(bot)
        except Exception:
            logger.exception("Ошибка планировщика ивентов")
            sleep_for = 5.0
        await asyncio.sleep(sleep_for)


async def _process_pending(bot: discord.Client) -> float:
    now = datetime.now(get_timezone())
    events = await db.get_pending_events()
    next_start: datetime | None = None

    for event in events:
        try:
            start = event_time_from_iso(event["event_time"])
        except ValueError:
            continue

        if start <= now:
            logger.info(
                "Автозапуск ивента #%s «%s» (время %s)",
                event["id"],
                event["title"],
                start.strftime("%H:%M:%S"),
            )
            await start_event_now(bot, event["id"], manual=False)
            continue

        if next_start is None or start < next_start:
            next_start = start

    if next_start is None:
        return _IDLE_INTERVAL

    seconds = (next_start - now).total_seconds()
    if seconds <= _MIN_INTERVAL:
        return _MIN_INTERVAL

    if seconds <= _PRECISE_WINDOW:
        return max(_MIN_INTERVAL, seconds)

    return min(seconds, _COARSE_INTERVAL)
