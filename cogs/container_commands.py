import logging
import secrets
import string
from typing import Optional, Union

import bcrypt
import discord
from discord import app_commands, Interaction
from discord.app_commands import Choice
from discord.ext import commands
from docker_runner.docker_runner import DockerRunner
from docker_runner.container_runner.container_runner_interface import ContainerRunner, ImageInfo, Port, PortProtocol, ServerInfo
from docker_runner.upnp_wrapper import UPNPWrapper

MAX_MESSAGE_SIZE = 2000


class ContainerCommands(commands.Cog):
    def __init__(self, bot: commands.Bot, container_runner: Optional[ContainerRunner] = None, main_domain: Optional[str] = None, **kwargs):
        if not container_runner:
            container_runner = DockerRunner()
        self.container_runner = container_runner
        self.bot = bot
        self._main_domain = main_domain
        super().__init__(**kwargs)

    @app_commands.command(name='create', description='This will create a new minecraft server')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(1013092707494809700)
    @app_commands.describe(game='Game Server')
    async def create(self, interaction: Interaction, game: str):
        user_id = str(interaction.user.id)
        try:
            server_info: ServerInfo = self.container_runner.create_game_server(user_id=user_id, image_id=game)
            await interaction.response.send_message(
                f'Created server {server_info.image.name.replace("-", " ").replace(":", " ").replace("/", " ").title()}', ephemeral=True
            )
        except Exception as e:
            logging.error(f'Failed to create container: {e}', exc_info=True)
            await interaction.response.send_message('Failed to create server please try again later.', ephemeral=True)

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

        file_browser_info = self.container_runner.start_file_browser(owner_id=str(user_id), server_id=game, hashed_password=hashed_password)
        if file_browser_info.ports is None:
            await interaction.response.send_message('Failed to create file browser', ephemeral=True)
            return

        available_access_points = [f'http://{file_browser_info.domain}:{port.number}' for port in file_browser_info.ports]

        await interaction.response.send_message(f'Opened file browser on {", ".join(available_access_points)}, Password: `{password}`', ephemeral=True)

    @app_commands.command(name='stop-browsing-files', description='Stops the file browser')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(1013092707494809700)
    async def stop_browsing(self, interaction: Interaction, game: Optional[str] = None):
        user_id = interaction.user.id
        self.container_runner.stop_file_browsing(user_id=str(user_id), server_id=game)
        await interaction.response.send_message('Stopped file browser', ephemeral=True)

    @app_commands.command(name='delete', description='This will create a new minecraft server')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(1013092707494809700)
    @app_commands.describe(game='Game Server')
    async def delete(self, interaction: Interaction, game: str):
        try:
            server_info = self.container_runner.get_server_info(server_id=game)
            self.container_runner.delete_game_server(server_id=server_info.id_)
            await interaction.response.send_message(f'Deleted game {await self.format_display_name(info=server_info)}', ephemeral=True)
        except Exception as e:
            logging.error(f'Failed to delete container: {e}', exc_info=True)
            await interaction.response.send_message('Failed to delete server please try again later.', ephemeral=True)

    @app_commands.command(name='run_command', description='runs a command within your docker container')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(1013092707494809700)
    @app_commands.describe(command='command to run')
    async def run_command(self, interaction: Interaction, game: str, command: str):
        response = self.container_runner.run_command(server_id=game, command=command)
        if not response:
            await interaction.response.send_message('No output was found')
            return
        await interaction.response.send_message(response[:MAX_MESSAGE_SIZE])

    @app_commands.command(name='get-server-ports', description='Gets the ports the server is listening on')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(1013092707494809700)
    async def get_server_ports(self, interaction: Interaction, game: str):
        info = self.container_runner.get_server_info(server_id=game)
        if info.ports is None:
            await interaction.response.send_message('Failed to get server ports')
            return

        available_access_points = {f'{self._main_domain}:{port.number}/{port.protocol}' for port in info.ports}
        await interaction.response.send_message(f'{await self.format_display_name(info)} is listening on port(s): {", ".join(available_access_points)}')

    @app_commands.command(name='get-server-logs', description='Gets the logs of a given server')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(1013092707494809700)
    async def get_server_logs(self, interaction: Interaction, game: str):
        server_info = self.container_runner.get_server_info(server_id=game)
        prefix = f'***{await self.format_display_name(server_info)} Logs***\n'
        max_log_size = MAX_MESSAGE_SIZE - len(prefix)
        logs = self.container_runner.get_server_logs(server_id=server_info.id_, lines_limit=max_log_size)

        if len(logs) > max_log_size:
            logs = logs[-max_log_size:]
        await interaction.response.send_message(prefix + logs, ephemeral=True)

    @commands.command(name='sync')
    async def sync(self, ctx: commands.Context, guild: Optional[discord.Guild] = None):
        await self.bot.tree.sync(guild=guild)

    @app_commands.command(name='start')
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guilds(1013092707494809700)
    @app_commands.describe(
        game='What kind of server to start',
        server_ports='Space separated list of ports the server is listening on format: `port_on_server`:`target_port`/`protocol`',
        command_parameters='Optional parameters to pass to the server',
    )
    async def start_container(self, interaction: discord.Interaction, game: str, server_ports: Optional[str] = None, command_parameters: Optional[str] = None):
        if server_ports is not None:
            formatted_ports = {}
            for ports in server_ports.split(' '):
                ports = server_ports.split('/')
                if len(ports) == 2:
                    ports, protocol = ports
                else:
                    ports = ports[0]
                    protocol = PortProtocol.TCP

                ports = ports.split(':')
                if len(ports) == 2:
                    server_port, target_port = ports
                else:
                    server_port = ports[0]
                    target_port = None

                formatted_ports[Port(number=int(server_port), protocol=PortProtocol(protocol))] = (
                    Port(number=int(target_port), protocol=PortProtocol(protocol)) if target_port is not None else None
                )
        else:
            formatted_ports = None

        server_info = self.container_runner.start_game_server(server_id=game, ports=ports, command_parameters=command_parameters)
        if server_info.ports is None:
            await interaction.response.send_message('Failed to get server ports')
            return
        available_access_points = {f'{self._main_domain}:{port.number}/{port.protocol}' for port in server_info.ports}

        await interaction.response.send_message(f'Starting {await self.format_display_name(server_info)} on port(s): {", ".join(available_access_points)}')

    @create.autocomplete('game')
    async def auto_complete_all_images(self, interaction: Interaction, current: str):
        image_info_list = self.container_runner.list_images()
        return [
            Choice(name=await self.format_display_name(info=image_info), value=image_info.id_)
            for image_info in image_info_list
            if image_info.name.replace(':', ' ').replace('/', ' ').replace('-', ' ').index(current) != -1
        ]

    async def format_display_name(self, info: Union[ServerInfo, ImageInfo]):
        if isinstance(info, ImageInfo):
            new_container_name = f"{info.name.replace('-', ' ')} {info.version}".title()
            return new_container_name

        else:
            new_container_name = f"{info.image.name.replace('-', ' ')} {info.image.version}".title()

        user = await self.bot.fetch_user(int(info.user_id))
        return f'{user.name}#{user.discriminator}\'s {new_container_name}'

    @start_container.autocomplete('game')
    async def autocomplete_all_stopped_containers(self, interaction: Interaction, current: str):
        servers = self.container_runner.list_servers()
        choices = []
        for server in (server for server in servers if not server.on):
            display_name = await self.format_display_name(server)
            if current.lower() in display_name.lower():
                choices.append(Choice(name=display_name, value=server.id_))
        return choices

    @start_browsing.autocomplete('game')
    async def autocomplete_all_potential_file_browsers(self, interaction: Interaction, current: str):
        servers = self.container_runner.list_servers()
        file_browsers = self.container_runner.list_file_browser_servers(user_id=str(interaction.user.id))
        choices = []
        for server in servers:
            if server.id_ in (fb.id_ for fb in file_browsers):
                continue

            display_name = await self.format_display_name(server)
            if current.lower() in display_name.lower():
                choices.append(Choice(name=display_name, value=server.id_))
        return choices

    @stop_browsing.autocomplete('game')
    async def autocomplete_all_filebrowsers(self, interaction: Interaction, current: str):
        file_browsers = self.container_runner.list_file_browser_servers(user_id=str(interaction.user.id))
        choices = []
        for server in file_browsers:
            display_name = await self.format_display_name(server)
            if current.lower() in display_name.lower():
                choices.append(Choice(name=display_name, value=server.id_))
        return choices

    @delete.autocomplete('game')
    async def autocomplete_user_containers(self, interaction: Interaction, current: str):
        userid = interaction.user.id
        servers = self.container_runner.list_servers(user_id=userid)
        choices = []
        for server in servers:
            display_name = await self.format_display_name(server)
            if current.lower() in display_name.lower():
                choices.append(Choice(name=display_name, value=server.id_))
        return choices

    @run_command.autocomplete('game')
    @get_server_ports.autocomplete('game')
    @get_server_logs.autocomplete('game')
    async def autocomplete_user_active_containers(self, interaction: Interaction, current: str):
        servers = self.container_runner.list_servers()
        choices = []
        for server in servers:
            display_name = await self.format_display_name(server)
            if current.lower() in display_name.lower():
                choices.append(Choice(name=display_name, value=server.id_))
        return choices


async def setup(bot: commands.Bot, domain: str, cert_path: str, key_path: str):
    await bot.add_cog(ContainerCommands(bot=bot, main_domain=domain, container_runner=UPNPWrapper(DockerRunner(cert_path=cert_path, key_path=key_path))))
