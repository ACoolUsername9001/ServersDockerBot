import logging
import os
from typing import Optional
import discord
import docker
from discord import app_commands, Interaction
from discord.app_commands import Choice
from discord.ext import commands

SERVERS_LIMIT = 5
GAMES_REPOSITORY = 'games'


class MinecraftCommands(commands.Cog):

    def __init__(self, bot: commands.Bot, docker_client: docker.client.DockerClient = None, **kwargs):
        if not docker_client:
            docker_client = docker.from_env()
        self.docker = docker_client
        self.bot = bot
        super().__init__(**kwargs)

    @staticmethod
    def format_container_name(userid, game=None) -> str:
        if not game:
            return f'{GAMES_REPOSITORY}-{userid}'
        return f'{GAMES_REPOSITORY}-{userid}-{game}'

    @app_commands.command(name='create', description='This will create a new minecraft server')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(699402987776245873, 1013092707494809700)
    @app_commands.describe(game='Game Server', server_port='The port the server is listening on')
    async def create(self, interaction: Interaction, game: str, server_port: str):
        userid = interaction.user.id
        if len(self.docker.containers.list(all=True, filters={'name': self.format_container_name(userid)})) > SERVERS_LIMIT:
            await interaction.response.send_message(f'You have already created a server, each user is limited to {SERVERS_LIMIT} servers', ephemeral=True)
            return
        if len(self.docker.containers.list(all=True, filters={'name': self.format_container_name(userid, game)})) > 0:
            await interaction.response.send_message(f'You have already created a server of that version, limited to 1 per user', ephemeral=True)
            return
        try:
            self.docker.containers.create(image=f'{GAMES_REPOSITORY}:{game}', name=self.format_container_name(userid, game), stdin_open=True, ports={server_port: None}, tty=True)
            await interaction.response.send_message(f'Created server {game.replace("-", " ").title()}', ephemeral=True)
        except Exception as e:
            logging.error(f'Failed to create container: {e}', exc_info=True)
            await interaction.response.send_message(f'Failed to create server please try again later.', ephemeral=True)

    @app_commands.command(name='delete', description='This will create a new minecraft server')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(699402987776245873, 1013092707494809700)
    @app_commands.describe(game='Game Server')
    async def delete(self, interaction: Interaction, game: str):
        userid = interaction.user.id
        containers = self.docker.containers.list(all=True, filters={'name': self.format_container_name(userid, game)})
        if len(containers) == 0:
            await interaction.response.send_message(f'You do not have a server of game {await self.get_display_name_from_container_name(self.format_container_name(userid, game), with_username=False)}', ephemeral=True)
            return
        try:
            for container in containers:
                container.remove(force=True)
            await interaction.response.send_message(f'Deleted game {await self.get_display_name_from_container_name(self.format_container_name(userid, game), with_username=False)}', ephemeral=True)
        except Exception as e:
            logging.error(f'Failed to delete container: {e}', exc_info=True)
            await interaction.response.send_message(f'Failed to delete server please try again later.', ephemeral=True)

    @app_commands.command(name='run_command', description='runs a command within your docker container')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(699402987776245873, 1013092707494809700)
    @app_commands.describe(command='command to run')
    async def run_command(self, interaction: Interaction, game: str, command: str):
        containers = self.docker.containers.list(filters={'name': self.format_container_name(game)})
        if not len(containers) == 1:
            await interaction.response.send_message(f'{await self.get_display_name_from_container_name(game)} is not running')
            return

        container = containers[0]
        sin = container.attach_socket(params={'stdin': True, 'stream': True, 'stdout': True, 'stderr': True})

        os.write(sin.fileno(), f'{command}\n'.encode('utf-8'))
        r = os.read(sin.fileno(), 10000)
        if command.encode('utf-8') in r.replace(b'\r', b'').replace(b'\n', b''):
            r = os.read(sin.fileno(), 10000)
        sin.close()
        logging.info(f'{r=}')
        await interaction.response.send_message(r.decode('utf-8')[:2000])

    @commands.command(name='sync')
    async def sync(self, ctx: commands.Context, guild: Optional[discord.Guild] = None):
        await self.bot.tree.sync(guild=guild)

    @app_commands.command(name='start')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(699402987776245873, 1013092707494809700)
    @app_commands.describe(game='What kind of server to start')
    async def start_container(self, interaction: discord.Interaction, game: str):
        containers = self.docker.containers.list(all=True, filters={'name': self.format_container_name(game)})
        if not containers:
            return
        container = containers[0]
        container.start()
        container = self.docker.containers.get(container_id=container.id)
        available_ports = []
        for key, value in container.ports.items():
            protocol = key.split('/')[-1]
            if value:
                host_ports = [v['HostPort'] for v in value]
                available_ports.extend(f'{port}/{protocol}' for port in host_ports)
        await interaction.response.send_message(f'Starting {await self.get_display_name_from_container_name(container.name)} on port(s): {",".join(available_ports)}')

    @create.autocomplete('game')
    async def auto_complete_all_images(self, interaction: Interaction, current: str):
        games = self.docker.images.list(all=True, name=GAMES_REPOSITORY)
        choices = []
        for game in games:
            choices.extend([Choice(name=tag.split(':')[1].replace('-', ' ').title(), value=tag.split(':')[1]) for tag in game.tags if tag.startswith(current)])
        return choices

    async def get_display_name_from_container_name(self, container_name, with_username=True):
        container_parts = container_name.split('-')[1:]
        user_id = container_parts[0]
        user = await self.bot.fetch_user(int(user_id))

        new_container_name = ' '.join(container_parts[1:]).title()
        if with_username:
            return f'{user.name}#{user.discriminator}\'s {new_container_name}'
        else:
            return new_container_name

    @start_container.autocomplete('game')
    async def autocomplete_all_containers(self, interaction: Interaction, current: str):
        games = self.docker.containers.list(all=True, filters={'name': self.format_container_name(current)})
        return [Choice(name=await self.get_display_name_from_container_name(game.name), value='-'.join(game.name.split('-')[1:])) for game in games]

    @delete.autocomplete('game')
    async def autocomplete_user_containers(self, interaction: Interaction, current: str):
        userid = interaction.user.id
        games = self.docker.containers.list(all=True, filters={'name': self.format_container_name(userid, current)})
        return [Choice(name=await self.get_display_name_from_container_name(game.name, with_username=False), value='-'.join(game.name.split('-')[2:])) for game in games]

    @run_command.autocomplete('game')
    async def autocomplete_user_active_containers(self, interaction: Interaction, current: str):
        games = self.docker.containers.list(filters={'name': self.format_container_name(current)})
        return [Choice(name=await self.get_display_name_from_container_name(game.name), value='-'.join(game.name.split('-')[1:])) for game in games]


async def setup(bot: commands.Bot):
    await bot.add_cog(MinecraftCommands(bot=bot))
