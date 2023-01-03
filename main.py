import json
from dataclasses import dataclass
from typing import Optional

import discord
from discord.ext.commands import Bot

from cogs.container_commands import setup


@dataclass(frozen=True, kw_only=True)
class Settings:
    token: str
    domain: str


class ServersContainerBot(Bot):
    def __init__(self, main_domain: Optional[str] = None, **kwargs):
        self._main_domain = main_domain
        super().__init__(**kwargs)

    async def on_ready(self):
        await setup(bot=self, main_domain=self._main_domain)


if __name__ == '__main__':
    with open('settings.json', 'r') as f:
        settings = Settings(**json.load(f))
    game_server_bot = ServersContainerBot(command_prefix=['!'], intents=discord.Intents.default(), main_domain=settings.domain)
    game_server_bot.run(token=settings.token)
