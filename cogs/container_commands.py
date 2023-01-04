import hashlib
import logging
import secrets
import string
from hashlib import sha256
from typing import Optional

import bcrypt
import discord
from discord import app_commands, Interaction
from discord.app_commands import Choice
from discord.ext import commands
from cogs.docker_runner import DockerRunner

MAX_MESSAGE_SIZE = 2000


class ContainerCommands(commands.Cog):

    def __init__(self, bot: commands.Bot, container_runner: DockerRunner = None, main_domain: Optional[str] = None, **kwargs):
        if not container_runner:
            container_runner = DockerRunner()
        self.docker = container_runner
        self.bot = bot
        self._main_domain = main_domain
        super().__init__(**kwargs)

    @app_commands.command(name='create', description='This will create a new minecraft server')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(1013092707494809700)
    @app_commands.describe(game='Game Server')
    async def create(self, interaction: Interaction, game: str):
        userid = interaction.user.id
        try:
            self.docker.create_game_server(user_id=userid, game=game)
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
        alphabet = string.ascii_letters + string.digits + string.punctuation
        alphabet = ''.join(x for x in alphabet if x != '`')
        password = ''.join([secrets.choice(alphabet) for _ in range(12)])
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        available_ports = self.docker.start_file_browser(user_id=user_id, server=game, hashed_password=hashed_password)
        available_access_points = {f'http://{self._main_domain}:{port.split("/")[0]}/' for port in available_ports}

        await interaction.response.send_message(f'Opened file browser on {", ".join(available_access_points)}, Password: `{password}`', ephemeral=True)

    @app_commands.command(name='stop-browsing-files', description='Stops the file browser')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(1013092707494809700)
    async def stop_browsing(self, interaction: Interaction, game: Optional[str] = None):
        user_id = interaction.user.id
        self.docker.stop_file_browsing(user_id=user_id, server=game)
        await interaction.response.send_message('Stopped file browser', ephemeral=True)

    @app_commands.command(name='delete', description='This will create a new minecraft server')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(1013092707494809700)
    @app_commands.describe(game='Game Server')
    async def delete(self, interaction: Interaction, game: str):
        userid = interaction.user.id
        try:
            self.docker.delete_game_server(user_id=userid, game=game)
            await interaction.response.send_message(f'Deleted game {await self.format_display_name(server_name=game)}', ephemeral=True)
        except Exception as e:
            logging.error(f'Failed to delete container: {e}', exc_info=True)
            await interaction.response.send_message(f'Failed to delete server please try again later.', ephemeral=True)

    @app_commands.command(name='run_command', description='runs a command within your docker container')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(1013092707494809700)
    @app_commands.describe(command='command to run')
    async def run_command(self, interaction: Interaction, game: str, command: str):
        response = self.docker.run_command(game, command)
        if not response:
            await interaction.response.send_message('No output was found')
            return
        await interaction.response.send_message(response[:MAX_MESSAGE_SIZE])

    @app_commands.command(name='get-server-ports', description='Gets the ports the server is listening on')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(1013092707494809700)
    async def get_server_ports(self, interaction: Interaction, game: str):
        ports = self.docker.list_server_ports(server=game)
        available_access_points = {f'{self._main_domain}:{port}' for port in ports}
        user_id, server_name = self.docker.get_user_id_and_image_name_from_game_server_name(server_name=game)
        await interaction.response.send_message(f'{await self.format_display_name(user_id=user_id, server_name=server_name)} is listening on port(s): {", ".join(available_access_points)}')

    @app_commands.command(name='get-server-logs', description='Gets the logs of a given server')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(1013092707494809700)
    async def get_server_logs(self, interaction: Interaction, game: str):
        user_id, server_name = self.docker.get_user_id_and_image_name_from_game_server_name(server_name=game)
        prefix = f'***{await self.format_display_name(server_name=server_name, user_id=user_id)} Logs***\n'
        max_log_size = MAX_MESSAGE_SIZE - len(prefix)
        logs = self.docker.get_server_logs(server=game, lines_limit=max_log_size)

        if len(logs) > max_log_size:
            logs = logs[-max_log_size:]
        await interaction.response.send_message(prefix+logs, ephemeral=True)

    @commands.command(name='sync')
    async def sync(self, ctx: commands.Context, guild: Optional[discord.Guild] = None):
        await self.bot.tree.sync(guild=guild)

    @app_commands.command(name='start')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(1013092707494809700)
    @app_commands.describe(game='What kind of server to start',
                           server_ports='Space separated list of ports the server is listening on',
                           command_parameters='Optional parameters to pass to the server')
    async def start_container(self, interaction: discord.Interaction, game: str, server_ports: Optional[str] = None, command_parameters: Optional[str] = None):
        if server_ports is not None:
            ports = server_ports.split()
        else:
            ports = None

        available_ports = self.docker.start_game_server(game=game, ports=ports, command_parameters=command_parameters)
        available_access_points = {f'{self._main_domain}:{port}' for port in available_ports}

        user_id, server = self.docker.get_user_id_and_image_name_from_game_server_name(game)
        await interaction.response.send_message(f'Starting {await self.format_display_name(user_id=user_id, server_name=server)} on port(s): {", ".join(available_access_points)}')

    @create.autocomplete('game')
    async def auto_complete_all_images(self, interaction: Interaction, current: str):
        games = self.docker.list_game_names()
        return [Choice(name=await self.format_display_name(server_name=game), value=game) for game in games if game.startswith(current)]

    async def format_display_name(self, server_name, user_id: Optional[int] = None):
        new_container_name = server_name.replace('-', ' ').title()

        if user_id:
            user = await self.bot.fetch_user(int(user_id))
            return f'{user.name}#{user.discriminator}\'s {new_container_name}'

        return new_container_name

    @start_container.autocomplete('game')
    async def autocomplete_all_stopped_containers(self, interaction: Interaction, current: str):
        games = self.docker.list_stopped_server_names()
        choices = []
        for game in games:
            user_id, server = self.docker.get_user_id_and_image_name_from_game_server_name(game)
            display_name = await self.format_display_name(user_id=user_id, server_name=server)
            if current.lower() in display_name.lower():
                choices.append(Choice(name=display_name, value=game))
        return choices

    @start_browsing.autocomplete('game')
    async def autocomplete_all_containers(self, interaction: Interaction, current: str):
        games = self.docker.list_server_names()
        choices = []
        for game in games:
            user_id, server = self.docker.get_user_id_and_image_name_from_game_server_name(game)
            display_name = await self.format_display_name(user_id=user_id, server_name=server)
            if current.lower() in display_name.lower():
                choices.append(Choice(name=display_name, value=game))
        return choices

    @stop_browsing.autocomplete('game')
    async def autocomplete_all_containers(self, interaction: Interaction, current: str):
        games = self.docker.list_file_browser_names(user_id=interaction.user.id)
        choices = []
        for game in games:
            user_id, server = self.docker.get_user_id_and_image_name_from_game_server_name(game)
            display_name = await self.format_display_name(user_id=user_id, server_name=server)
            if current.lower() in display_name.lower():
                choices.append(Choice(name=display_name, value=game))
        return choices

    @delete.autocomplete('game')
    async def autocomplete_user_containers(self, interaction: Interaction, current: str):
        userid = interaction.user.id
        games = self.docker.list_server_names(user_id=userid)
        choices = []
        for game in games:
            user_id, server = self.docker.get_user_id_and_image_name_from_game_server_name(game)
            display_name = await self.format_display_name(user_id=user_id, server_name=server)
            if current.lower() in display_name.lower():
                choices.append(Choice(name=display_name, value=server))
        return choices

    @run_command.autocomplete('game')
    @get_server_ports.autocomplete('game')
    @get_server_logs.autocomplete('game')
    async def autocomplete_user_active_containers(self, interaction: Interaction, current: str):
        games = self.docker.list_running_server_names()
        choices = []
        for game in games:
            user_id, server = self.docker.get_user_id_and_image_name_from_game_server_name(game)
            display_name = await self.format_display_name(user_id=user_id, server_name=server)
            if current.lower() in display_name.lower():
                choices.append(Choice(name=display_name, value=game))
        return choices


async def setup(bot: commands.Bot, domain: str, cert_path: str, key_path: str):

    await bot.add_cog(ContainerCommands(bot=bot, main_domain=domain, container_runner=DockerRunner(cert_path=cert_path, key_path=key_path)))
