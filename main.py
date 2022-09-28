import json
import discord
from discord.ext.commands import Bot

from cogs.server_loader import setup


class MCBot(Bot):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    async def on_ready(self):
        await setup(bot=self)


if __name__ == '__main__':
    mcbot = MCBot(command_prefix=['!'], intents=discord.Intents.default())
    with open('key.json', 'r') as f:
        keys = json.load(f)
    token = keys['token']
    mcbot.run(token=token)
