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
    domain_cert_path: Optional[str] = None
    domain_key_path: Optional[str] = None


class ServersContainerBot(Bot):
    def __init__(self, domain: Optional[str] = None, domain_cert_path: Optional[str] = None, domain_key_path: Optional[str] = None, **kwargs):
        self._domain = domain
        self._domain_key_path = domain_key_path
        self._domain_cert_path = domain_cert_path
        super().__init__(**kwargs)

    async def on_ready(self):
        await setup(bot=self, domain=self._domain, cert_path=self._domain_cert_path, key_path=self._domain_key_path)


if __name__ == '__main__':
    with open('settings.json', 'r') as f:
        settings = Settings(**json.load(f))
    game_server_bot = ServersContainerBot(command_prefix=['!'], intents=discord.Intents.default(),
                                          domain=settings.domain,
                                          domain_cert_path=settings.domain_cert_path,
                                          domain_key_path=settings.domain_key_path)
    game_server_bot.run(token=settings.token)
