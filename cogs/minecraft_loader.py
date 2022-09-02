import logging
import os
import re
from typing import Optional
import discord
import docker
from docker.errors import NotFound
from docker.types import Mount
from discord import app_commands, Interaction
from discord.app_commands import Choice
from discord.ext import commands

SERVERS_LIMIT = 5
GAMES_REPOSITORY = 'games'
FILE_BROWSER_PREFIX = 'filebrowser'
FILE_BROWSER_IMAGE = 'filebrowser/filebrowser'
ansi_escape = re.compile(br'(?:\x1B[@-Z\\-_]|[\x80-\x9A\x9C-\x9F]|(?:\x1B\[|\x9B)[0-?]*[ -/]*[@-~])')


class MinecraftCommands(commands.Cog):

    def __init__(self, bot: commands.Bot, docker_client: docker.client.DockerClient = None, **kwargs):
        if not docker_client:
            docker_client = docker.from_env()
        self.docker = docker_client
        self.bot = bot
        super().__init__(**kwargs)

    @staticmethod
    def format_game_container_name(userid, game=None) -> str:
        if not game:
            return f'{GAMES_REPOSITORY}-{userid}'
        return f'{GAMES_REPOSITORY}-{userid}-{game}'

    @staticmethod
    def format_file_browser_container_name(userid) -> str:
        return f'{FILE_BROWSER_PREFIX}-{userid}'

    @app_commands.command(name='create', description='This will create a new minecraft server')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(1013092707494809700)
    @app_commands.describe(game='Game Server',
                           server_ports='Space seperated list of ports the server is listening on',
                           command_parameters='Optional parameters to pass to the server')
    async def create(self, interaction: Interaction, game: str, server_ports: str, command_parameters: Optional[str] = None):
        userid = interaction.user.id
        if len(self.docker.containers.list(all=True, filters={'name': self.format_game_container_name(userid)})) > SERVERS_LIMIT:
            await interaction.response.send_message(f'You have already created a server, each user is limited to {SERVERS_LIMIT} servers', ephemeral=True)
            return
        container_name = self.format_game_container_name(userid, game)
        if len(self.docker.containers.list(all=True, filters={'name': container_name})) > 0:
            await interaction.response.send_message(f'You have already created a server of that version, limited to 1 per user', ephemeral=True)
            return
        try:
            image_name = f'{GAMES_REPOSITORY}:{game}'
            image = self.docker.images.get(image_name)
            working_dir = image.attrs.get('Config', {}).get('WorkingDir')

            if working_dir:
                mounts = [Mount(source=container_name, target=working_dir, type='volume')]
            else:
                mounts = None

            self.docker.containers.create(image=image_name,
                                          name=container_name,
                                          stdin_open=True,
                                          ports={server_port: None for server_port in server_ports.split()},
                                          tty=True,
                                          command=command_parameters,
                                          mounts=mounts)

            await interaction.response.send_message(f'Created server {game.replace("-", " ").title()}', ephemeral=True)
        except Exception as e:
            logging.error(f'Failed to create container: {e}', exc_info=True)
            await interaction.response.send_message(f'Failed to create server please try again later.', ephemeral=True)

    @app_commands.command(name='browse-files', description='Opens a file browser server, please close it after use')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(1013092707494809700)
    @app_commands.describe(game='The game server to browse it\'s files')
    async def start_browsing(self, interaction: Interaction, game: str):
        user_id = interaction.user.id
        container_name = self.format_game_container_name(userid=user_id, game=game)
        mounts = [Mount(source=container_name, target='/tmp/data', type='volume')]
        file_browser_name = self.format_file_browser_container_name(userid=user_id)
        if self.docker.containers.list(filters=dict(name=file_browser_name)):
            await interaction.response.send_message(f'You already have a file browser open', ephemeral=True)
            return
        container = self.docker.containers.create(image=FILE_BROWSER_IMAGE, name=file_browser_name, auto_remove=True, command='-r /tmp/data', mounts=mounts, ports={'80/tcp': None})
        container.start()
        container = self.docker.containers.get(container_id=container.id)
        available_ports = self.get_ports_from_container(container)
        await interaction.response.send_message(f'Opened file browser on ports {",".join(available_ports)}', ephemeral=True)

    @app_commands.command(name='stop-browsing-files', description='Stops the file browser')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(1013092707494809700)
    async def stop_browsing(self, interaction: Interaction):
        user_id = interaction.user.id
        container_name = self.format_file_browser_container_name(userid=user_id)
        container = self.docker.containers.get(container_id=container_name)
        container.stop()
        await interaction.response.send_message('Stopped file browser', ephemeral=True)

    @app_commands.command(name='delete', description='This will create a new minecraft server')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(1013092707494809700)
    @app_commands.describe(game='Game Server')
    async def delete(self, interaction: Interaction, game: str):
        userid = interaction.user.id
        container_name = self.format_game_container_name(userid, game)
        containers = self.docker.containers.list(all=True, filters={'name': container_name})
        if len(containers) == 0:
            await interaction.response.send_message(f'You do not have a server of game {await self.get_display_name_from_container_name(container_name, with_username=False)}', ephemeral=True)
            return
        try:
            for container in containers:
                container.remove(force=True)
                try:
                    volume = self.docker.volumes.get(container.name)
                    volume.remove(force=True)
                except NotFound:
                    pass

            await interaction.response.send_message(f'Deleted game {await self.get_display_name_from_container_name(container_name, with_username=False)}', ephemeral=True)
        except Exception as e:
            logging.error(f'Failed to delete container: {e}', exc_info=True)
            await interaction.response.send_message(f'Failed to delete server please try again later.', ephemeral=True)

    @app_commands.command(name='run_command', description='runs a command within your docker container')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(1013092707494809700)
    @app_commands.describe(command='command to run')
    async def run_command(self, interaction: Interaction, game: str, command: str):
        containers = self.docker.containers.list(filters={'name': self.format_game_container_name(game)})
        if not len(containers) == 1:
            await interaction.response.send_message(f'{await self.get_display_name_from_container_name(game)} is not running')
            return

        container = containers[0]
        sin = container.attach_socket(params={'stdin': True, 'stream': True, 'stdout': True, 'stderr': True})

        os.write(sin.fileno(), f'{command}\n'.encode('utf-8'))
        with open(sin.fileno(), 'rb') as f:
            while command in (r := ansi_escape.sub(b'', f.readline()).decode().replace('\n', '').replace('\r', '')) or not r or r == '>':
                pass
        sin.close()
        await interaction.response.send_message(r[:2000])

    @commands.command(name='sync')
    async def sync(self, ctx: commands.Context, guild: Optional[discord.Guild] = None):
        await self.bot.tree.sync(guild=guild)

    @app_commands.command(name='start')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(1013092707494809700)
    @app_commands.describe(game='What kind of server to start')
    async def start_container(self, interaction: discord.Interaction, game: str):
        containers = self.docker.containers.list(all=True, filters={'name': self.format_game_container_name(game)})
        if not containers:
            return
        container = containers[0]
        container.start()
        container = self.docker.containers.get(container_id=container.id)
        available_ports = self.get_ports_from_container(container)
        await interaction.response.send_message(f'Starting {await self.get_display_name_from_container_name(container.name)} on port(s): {",".join(available_ports)}')

    @staticmethod
    def get_ports_from_container(container):
        available_ports = []
        for key, value in container.ports.items():
            protocol = key.split('/')[-1]
            if value:
                host_ports = [v['HostPort'] for v in value]
                available_ports.extend(f'{port}/{protocol}' for port in host_ports)
        return available_ports

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
        games = self.docker.containers.list(all=True, filters={'name': self.format_game_container_name(current)})
        return [Choice(name=await self.get_display_name_from_container_name(game.name), value='-'.join(game.name.split('-')[1:])) for game in games]

    @delete.autocomplete('game')
    @start_browsing.autocomplete('game')
    async def autocomplete_user_containers(self, interaction: Interaction, current: str):
        userid = interaction.user.id
        games = self.docker.containers.list(all=True, filters={'name': self.format_game_container_name(userid, current)})
        return [Choice(name=await self.get_display_name_from_container_name(game.name, with_username=False), value='-'.join(game.name.split('-')[2:])) for game in games]

    @run_command.autocomplete('game')
    async def autocomplete_user_active_containers(self, interaction: Interaction, current: str):
        games = self.docker.containers.list(filters={'name': self.format_game_container_name(current)})
        return [Choice(name=await self.get_display_name_from_container_name(game.name), value='-'.join(game.name.split('-')[1:])) for game in games]


async def setup(bot: commands.Bot):
    await bot.add_cog(MinecraftCommands(bot=bot))
