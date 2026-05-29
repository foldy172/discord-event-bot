import asyncio
import logging

import discord
from discord.ext import commands

import database as db
from config import DISCORD_TOKEN, GUILD_ID
from scheduler import check_events
from views import make_event_view
from web.server import start_web_panel_in_background

logging.basicConfig(level=logging.INFO)


async def _no_prefix(_bot: commands.Bot, _message: discord.Message) -> list[str]:
    return []


class EventBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        super().__init__(command_prefix=_no_prefix, intents=intents)

    async def setup_hook(self):
        await db.init_db()
        await self.load_extension("cogs.events")

        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

        asyncio.create_task(check_events(self))


bot = EventBot()


async def restore_event_views():
    events = await db.get_pending_events()
    for event in events:
        bot.add_view(make_event_view(event["id"]))


@bot.event
async def on_ready():
    await restore_event_views()
    print(f"Бот запущен: {bot.user}")


def main():
    if not DISCORD_TOKEN:
        raise SystemExit("Укажите DISCORD_TOKEN в файле .env")
    start_web_panel_in_background()
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
