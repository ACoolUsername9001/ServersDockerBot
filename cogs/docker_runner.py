import os
import re
import time

import chardet
import docker
import select
from typing import Optional, List, Dict, Any, Union
from docker.models.containers import Container
from docker.models.images import Image
from docker.models.volumes import Volume
from docker.types import Mount
from .container_runner.container_runner_interface import ContainerRunner

GAMES_REPOSITORY = 'games'
FILE_BROWSER_PREFIX = 'filebrowser'
FILE_BROWSER_IMAGE = 'filebrowser/filebrowser'

ansi_escape = re.compile(br'(?:\x1B[@-Z\\-_]|[\x80-\x9A\x9C-\x9F]|(?:\x1B\[|\x9B)[0-?]*[ -/]*[@-~])')

ports_format = re.compile(r'(?P<port>\d+)(?:/(?P<protocol>\w+))?(?::(?P<destination>\d+))?')


def _convert_to_string(byte_str: Union[bytes, bytearray]) -> str:
    encoding = chardet.detect(byte_str).get('encoding')
    if encoding:
        return byte_str.decode(encoding)
    return byte_str.decode()


class GameNotFound(Exception):
    pass


class ServerNotFound(Exception):
    pass


class ServerAlreadyRunning(Exception):
    pass


class ServerNotRunning(Exception):
    pass


class DockerRunner(ContainerRunner):

    def __init__(self, docker_client: Optional[docker.DockerClient] = None,
                 games_repository: str = GAMES_REPOSITORY,
                 games_prefix: str = GAMES_REPOSITORY,
                 filebrowser_prefix: str = FILE_BROWSER_PREFIX,
                 filebrowser_repository: str = FILE_BROWSER_IMAGE,
                 cert_path: Optional[str] = None,
                 key_path: Optional[str] = None):
        if not docker_client:
            docker_client = docker.from_env()
        self._games_repository = games_repository
        self._games_prefix = games_prefix
        self._filebrowser_prefix = filebrowser_prefix
        self.docker = docker_client
        self.docker.images.pull(repository=filebrowser_repository)
        self._filebrowser_image = filebrowser_repository
        self._cert_path = cert_path
        self._key_path = key_path

    @staticmethod
    def get_user_id_and_image_name_from_game_server_name(server_name):
        match = re.match(r'(?P<userid>\w+)-(?P<server>.+)', server_name)
        groups = match.groupdict()
        return groups.get('userid'), groups.get('server')

    @staticmethod
    def get_user_id_and_image_name_from_file_browser_name(server_name):
        match = re.match(rf'(?P<userid>\w+)-(?P<server>.+)', server_name)
        groups = match.groupdict()
        return groups.get('userid'), groups.get('server')

    def _hide_games_prefix(self, name: str):
        return name[len(self._games_prefix)+1:]

    def _hide_file_browser_prefix(self, name):
        return name[len(self._filebrowser_prefix) + 1:]

    def list_game_ports(self, tag) -> list[str]:
        image = self.docker.images.get(self._format_image_name(tag=tag))
        ports = list(image.attrs.get('Config', {}).get('ExposedPorts', {}))
        return ports

    def _format_game_container_name(self, user_id=None, game=None) -> str:
        if not game:
            if not user_id:
                return f'{self._games_prefix}-'
            return f'{self._games_prefix}-{user_id}-'
        return f'{self._games_prefix}-{user_id}-{game}'

    def _format_file_browser_container_name(self, user_id, server: Optional[str] = None) -> str:
        return f'{self._filebrowser_prefix}-{user_id}-{server if server is not None else ""}'

    def _format_image_name(self, tag):
        return f'{self._games_repository}:{tag}'

    def _list_server_volumes(self, user_id=None, prefix: Optional[str] = None) -> List[Volume]:
        return self.docker.volumes.list(filters={'name': self._format_game_container_name(user_id=user_id, game=prefix)})

    def _list_running_server_containers(self, user_id=None, prefix: Optional[str] = None) -> List[Container]:
        return self.docker.containers.list(filters={'name': self._format_game_container_name(user_id=user_id, game=prefix)})

    def _list_file_browsers(self, user_id, server: Optional[str] = None) -> List[Container]:
        return self.docker.containers.list(filters={'name': self._format_file_browser_container_name(user_id=user_id, server=server)})

    def _list_game_images(self) -> List[Image]:
        return self.docker.images.list(all=True, name=self._games_repository)

    def list_server_names(self, user_id=None, prefix: Optional[str] = None) -> List[str]:
        return [self._hide_games_prefix(v.name) for v in self._list_server_volumes(user_id, prefix)]

    def list_running_server_names(self, user_id=None, prefix: Optional[str] = None) -> List[str]:
        return [self._hide_games_prefix(c.name) for c in self._list_running_server_containers(user_id=user_id, prefix=prefix)]

    def list_stopped_server_names(self, user_id: Optional[Any] = None, prefix: Optional[str] = None) -> List[str]:
        servers = self.list_server_names(user_id=user_id, prefix=prefix)
        running_servers = self.list_running_server_names(user_id=user_id, prefix=prefix)
        return [server for server in servers if server not in running_servers]

    def list_file_browser_names(self, user_id) -> List[str]:
        return [self._hide_file_browser_prefix(c.name)[len(f'{user_id}-'):] for c in self._list_file_browsers(user_id=user_id)]

    def list_game_names(self) -> List[str]:
        tags = []
        for image in self._list_game_images():
            tags.extend(x.split(':')[1] for x in image.tags)
        return tags

    def create_game_server(self, user_id, game: str) -> str:
        game_images = self.list_game_names()

        if game not in game_images:
            raise GameNotFound(f'Game {game} was not found')

        return self._hide_games_prefix(self.docker.volumes.create(name=self._format_game_container_name(user_id=user_id, game=game)).name)

    def _get_server_image_working_dir(self, image_tag):
        image_name = self._format_image_name(image_tag)
        image = self.docker.images.get(image_name)
        return image.attrs.get('Config', {}).get('WorkingDir')

    @staticmethod
    def _find_suitable_ports(ports: List[str]) -> Dict[str, Optional[str]]:
        suitable_ports = {}
        for port in ports:
            match = ports_format.match(port).groupdict()
            port_number = match.get('port')
            protocol = match.get('protocol', 'tcp')
            if protocol is None:
                protocol = 'tcp'
            destination = match.get('destination', None)
            suitable_ports[f'{port_number}/{protocol}'] = destination
        return suitable_ports

    @staticmethod
    def get_ports_from_container(container) -> List[str]:
        available_ports = []
        for key, value in container.ports.items():
            protocol = key.split('/')[-1]
            if value:
                host_ports = [v['HostPort'] for v in value]
                available_ports.extend(f'{port}/{protocol}' for port in host_ports)
        return available_ports

    def start_game_server(self, game, ports: Optional[List[str]] = None, command_parameters: Optional[str] = None) -> List[str]:
        user_id, image_name = self.get_user_id_and_image_name_from_game_server_name(game)
        if image_name not in self.list_game_names():
            raise GameNotFound(f'Game {image_name} was not found')

        all_servers = self.list_server_names(user_id=user_id, prefix=image_name)
        if len(all_servers) == 0:
            raise ServerNotFound(f'Server of game {game} was not found')

        running_servers = self.list_running_server_names(user_id=user_id, prefix=game)
        if len(running_servers) > 1:
            raise ServerAlreadyRunning(f'Server of game {game} is already running')

        working_dir = self._get_server_image_working_dir(image_name)
        server_name = self._format_game_container_name(user_id=user_id, game=image_name)
        if working_dir:
            mount = [Mount(target=working_dir, source=server_name, type='volume')]
        else:
            mount = None
        if ports is None:
            ports = self.list_game_ports(image_name)

        ports = self._find_suitable_ports(ports)

        container = self.docker.containers.create(image=self._format_image_name(image_name),
                                                  name=server_name,
                                                  mounts=mount,
                                                  command=command_parameters,
                                                  ports=ports,
                                                  stdin_open=True,
                                                  tty=True,
                                                  auto_remove=True)
        container.start()
        time.sleep(0.01)
        container = self.docker.containers.get(container_id=container.id)
        return self.get_ports_from_container(container)

    def run_command(self, server, command) -> Optional[str]:
        try:
            user_id, image_name = self.get_user_id_and_image_name_from_game_server_name(server_name=server)
            container = self.docker.containers.get(self._format_game_container_name(user_id=user_id, game=image_name))
        except Exception as e:
            raise ServerNotRunning(e)

        sin = container.attach_socket(params={'stdin': True, 'stream': True, 'stdout': True, 'stderr': True})

        os.write(sin.fileno(), f'{command}\n'.encode('utf-8'))
        all_output = ''
        with open(sin.fileno(), 'rb') as f:
            read, _, _ = select.select([f], [], [], 0.1)
            retries = 5
            lines = 20
            while lines > 0:
                read, _, _ = select.select([f], [], [], 0.1)
                if f not in read:
                    if retries >= 0:
                        retries -= 1
                        continue
                    break

                r = ansi_escape.sub(b'', f.readline()).decode().replace('\r', '')
                all_output += f'{r}\n'
                lines -= 1
            sin.close()
            return all_output

    def delete_game_server(self, user_id, game):
        server = self._format_game_container_name(user_id=user_id, game=game)
        try:
            volume = self.docker.volumes.get(server)
        except Exception as e:
            raise ServerNotFound(e)

        for container in self._list_running_server_containers(user_id=user_id, prefix=game):
            container.remove(force=True)

        for browser in self._list_file_browsers(user_id=user_id):
            mounts = browser.attrs.get('Mounts')
            for mount in mounts:
                if mount.get('Name') == server:
                    browser.remove(force=True)
                    break

        volume.remove(force=True)

    def start_file_browser(self, server, executor_id, hashed_password=None) -> List[str]:
        filebrowser_command = f'-r /tmp/data'
        if hashed_password is not None:
            filebrowser_command += f' --username admin --password "{hashed_password}"'

        user_id, game = self.get_user_id_and_image_name_from_game_server_name(server_name=server)

        mounts = [Mount(source=self._format_game_container_name(user_id=user_id, game=game), target='/tmp/data', type='volume')]

        if self._cert_path:
            mounts.append(Mount(source=self._cert_path, target='/tmp/cert'))
            filebrowser_command += ' --cert /tmp/cert'
        if self._key_path:
            mounts.append(Mount(source=self._key_path, target='/tmp/key'))
            filebrowser_command += ' --key /tmp/key'

        file_browser_name = self._format_file_browser_container_name(user_id=executor_id, server=server)
        if len(self.list_file_browser_names(user_id=executor_id)) > 2:
            raise ServerAlreadyRunning()
        container = self.docker.containers.create(image=self._filebrowser_image,
                                                  name=file_browser_name,
                                                  auto_remove=True,
                                                  command=filebrowser_command,
                                                  mounts=mounts,
                                                  ports={'80/tcp': None})
        container.start()
        time.sleep(0.01)
        container = self.docker.containers.get(container_id=container.id)
        available_ports = self.get_ports_from_container(container)
        return available_ports

    def stop_file_browsing(self, user_id, server: Optional[str] = None):
        file_browsers = self._list_file_browsers(user_id=user_id, server=server)
        for file_browser in file_browsers:
            file_browser.stop()

    def list_server_ports(self, server) -> List[str]:
        user_id, image_name = self.get_user_id_and_image_name_from_game_server_name(server_name=server)
        container = self.docker.containers.get(self._format_game_container_name(user_id=user_id, game=image_name))
        return self.get_ports_from_container(container)

    def get_server_logs(self, server, lines_limit: Optional[int] = None) -> str:
        if lines_limit is None:
            lines_limit = 'all'
        user_id, image_name = self.get_user_id_and_image_name_from_game_server_name(server_name=server)
        container = self.docker.containers.get(self._format_game_container_name(user_id=user_id, game=image_name))
        logs = ansi_escape.sub(b'', container.logs(tail=lines_limit))
        return _convert_to_string(logs)
