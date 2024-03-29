import os
import re
import time

from pydantic import BaseModel

import chardet
import docker
import select
from typing import Literal, Optional, List, Union, cast
from docker.models.containers import Container
from docker.models.images import Image
from docker.models.volumes import Volume
from docker.types import Mount
from docker_runner.container_runner.container_runner_interface import ContainerRunner, FileBrowserInfo, ImageInfo, Port, ServerInfo, ServerType
from pathlib import Path
from time import sleep

GAMES_REPOSITORY = 'games'
FILE_BROWSER_PREFIX = 'filebrowser'
FILE_BROWSER_IMAGE = 'filebrowser/filebrowser'

ANSI_ESCAPE = re.compile(br'(?:\x1B[@-Z\\-_]|[\x80-\x9A\x9C-\x9F]|(?:\x1B\[|\x9B)[0-?]*[ -/]*[@-~])')

PORTS_FORMAT = re.compile(r'(?P<port>\d+)(?:/(?P<protocol>\w+))?(?::(?P<destination>\d+))?')


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


class MaxServersReached(Exception):
    pass


class VolumeLabels(BaseModel):
    user_id: str
    image_id: str


class ContainerLabels(BaseModel):
    user_id: str
    image_id: str
    volume_id: str
    type: ServerType


class ImageLabels(BaseModel):
    type: ServerType


DOMAIN = 'acooldomain.co'


def create_labels_filter(**kwargs: Optional[str]) -> list[str]:
    return [f'{key}={value}' if value is not None else f'{key}' for key, value in kwargs.items()]


class DockerRunner(ContainerRunner):
    def __init__(
        self,
        docker_client: Optional[docker.DockerClient] = None,
        filebrowser_repository: str = FILE_BROWSER_IMAGE,
        cert_path: Optional[str] = None,
        key_path: Optional[str] = None,
        domain: str = DOMAIN,
    ):
        if not docker_client:
            docker_client = docker.from_env()
        self.docker = docker_client
        
        try:
            self.docker.images.get(filebrowser_repository)
        except Exception as e:
            self.docker.images.pull(repository=filebrowser_repository)

        self._filebrowser_image = filebrowser_repository
        self._cert_path = cert_path
        self._key_path = key_path
        self._domain = domain
        try:
            self._browser_network = self.docker.networks.get('browsers')
        except:
            self._browser_network = self.docker.networks.create('browsers')
        try:
            self._nginx = self.docker.containers.get('browsers-nginx')
        except:
            self._nginx = None

        if self._nginx is None:
            self._nginx = self.docker.containers.run(image='nginx:latest', detach=True, name='browsers-nginx', ports={'80/tcp': ('127.0.0.1', '4080/tcp')}, network='browsers', mounts=[Mount(target='/etc/nginx/conf.d/default.conf', source=str(Path(__file__).parent/'nginx.conf'), read_only=True, type='bind')])
    

    def _get_server_container(self, server_info: ServerInfo, server_type: ServerType, user_id: Optional[str] = None) -> Optional[Container]:
        container_list: list[Container] = cast(
            list[Container],
            self.docker.containers.list(
                filters={
                    'label': create_labels_filter(
                        volume_id=server_info.id_,
                        image_id=server_info.image.id_,
                        type=server_type.value,
                        user_id=user_id,
                    ),
                },
            ),
        )

        if len(container_list) > 1:
            raise ValueError(f'More than one container was found {container_list}')

        if len(container_list) == 0:
            return None

        return container_list[0]

    def get_server_info(self, server_id: str, user_id: Optional[str] = None) -> ServerInfo:
        volume: Optional[Volume] = cast(Optional[Volume], self.docker.volumes.get(server_id))
        if volume is None:
            raise ServerNotFound()

        if volume.attrs is None:
            raise ServerNotFound('Volume has no attrs')

        volume_labels = VolumeLabels(**volume.attrs.get('Labels', {}))
        image = self.get_image_info(image_id=volume_labels.image_id)
        if image is None:
            raise GameNotFound()


        server_info = ServerInfo(id_=str(volume.id), user_id=volume_labels.user_id, image=image, on=False)

        container = self._get_server_container(server_info=server_info, user_id=user_id, server_type=ServerType.GAME)

        if container is None:
            return server_info

        return ServerInfo(
            id_=str(volume.id),
            user_id=volume_labels.user_id,
            image=image,
            on=True,
            domain=self._domain,
            ports=self._extract_ports_from_container(container=container),
        )

    def list_servers(self, user_id: Optional[str] = None, image_id: Optional[str] = None) -> List[ServerInfo]:
        volumes = self.docker.volumes.list(filters={'label': create_labels_filter(user_id=user_id, image_id=image_id)})
        return [self.get_server_info(str(volume.id)) for volume in volumes]

    def list_images(self) -> List[ImageInfo]:
        images = cast(list[Image], self.docker.images.list(filters={'label': create_labels_filter(type=ServerType.GAME.value)}))

        image_info_list: list[ImageInfo] = []

        for image in images:
            image_info_list.extend(self._extract_image_info_from_image(image))

        return image_info_list

    def get_image_info(self, image_id: str) -> ImageInfo:
        image: Optional[Image] = cast(Optional[Image], self.docker.images.get(image_id))
        if image is None:
            raise GameNotFound()

        image_info_list = self._extract_image_info_from_image(image)

        return image_info_list[0]

    def create_game_server(self, user_id: str, image_id: str) -> ServerInfo:
        image = self.get_image_info(image_id=image_id)

        if image is None:
            raise GameNotFound(f'Game {image_id} was not found')

        existing_servers = self.list_servers(user_id=user_id, image_id=image.id_)

        if len(existing_servers) > 5:
            raise MaxServersReached()

        volume: Volume = cast(Volume, self.docker.volumes.create(labels=VolumeLabels(user_id=user_id, image_id=image.id_).model_dump(mode='json')))

        assert volume.attrs is not None, 'Volume.attrs was None'

        volume_labels = VolumeLabels(**volume.attrs.get('Labels', {}))
        return ServerInfo(id_=str(volume.id), user_id=volume_labels.user_id, image=image, on=False)

    def _get_server_image_working_dir(self, image_id: str):
        image = self.docker.images.get(image_id)
        assert image.attrs is not None, 'Image.attrs was None'
        return image.attrs.get('Config', {}).get('WorkingDir')

    def start_game_server(self, server_id: str, ports: Optional[dict[Port, Optional[Port]]] = None, command_parameters: Optional[str] = None) -> ServerInfo:
        server_info = self.get_server_info(server_id)

        if server_info.on:
            raise ServerAlreadyRunning()

        working_dir = self._get_server_image_working_dir(server_info.image.id_)

        if working_dir:
            mount = [Mount(source=server_info.id_, target=working_dir, type='volume')]
        else:
            mount = None

        if ports is None:
            ports = {port: None for port in server_info.image.ports}

        container = cast(
            Container,
            self.docker.containers.create(
                image=server_info.image.id_,
                mounts=mount,
                command=command_parameters,
                ports={host_port.id_: container_port.id_ if container_port is not None else None for host_port, container_port in ports.items()},
                stdin_open=True,
                tty=True,
                auto_remove=True,
                labels=ContainerLabels(
                    user_id=server_info.user_id,
                    image_id=server_info.image.id_,
                    volume_id=server_info.id_,
                    type=ServerType.GAME,
                ).model_dump(mode='json'),
            ),
        )
        container.start()
        time.sleep(0.01)
        container = cast(Container, self.docker.containers.get(container_id=container.id))

        return ServerInfo(
            id_=server_info.id_,
            user_id=server_info.user_id,
            image=server_info.image,
            on=True,
            ports=self._extract_ports_from_container(container),
            domain=self._domain,
        )

    def run_command(self, server_id: str, command: str) -> Optional[str]:
        try:
            container = cast(Container, self.docker.containers.list(filters={'label': create_labels_filter(volume_id=server_id)})[0])
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

                r = ANSI_ESCAPE.sub(b'', f.readline()).decode().replace('\r', '')
                all_output += f'{r}\n'
                lines -= 1
            sin.close()
            return all_output

    def delete_game_server(self, server_id: str):
        try:
            volume = cast(Volume, self.docker.volumes.get(server_id))
        except Exception as e:
            raise ServerNotFound(e)

        for container in cast(list[Container], self.docker.containers.list(all=True, filters={'label': f'volume_id={server_id}'})):
            container.remove(force=True)

        volume.remove(force=True)

    def start_file_browser(self, server_id: str, owner_id: str, hashed_password=None) -> FileBrowserInfo:
        filebrowser_command = '-r /tmp/data'

        if hashed_password is not None:
            filebrowser_command += f' --username {owner_id} --password "{hashed_password}"'

        server_info = self.get_server_info(server_id=server_id)

        mounts = [Mount(source=server_info.id_, target='/tmp/data', type='volume')]

        container = self._get_server_container(server_info=server_info, user_id=owner_id, server_type=ServerType.FILE_BROWSER)
        if container is None:
            container = cast(
                Container,
                self.docker.containers.create(
                    image=FILE_BROWSER_IMAGE,
                    command=filebrowser_command,
                    mounts=mounts,
                    network='browsers',
                    labels=ContainerLabels(
                        user_id=owner_id, image_id=server_info.image.id_, volume_id=server_info.id_, type=ServerType.FILE_BROWSER,
                    ).model_dump(mode='json'),
                    tty=True,
                    auto_remove=True,
                ),
            )
            container.start()
            time.sleep(0.01)
            container = cast(Container, self.docker.containers.get(container_id=container.id))

        return FileBrowserInfo(id_=container.id[:12], domain=f'browsers.{self._domain}', connected_to=server_info, owner_id=owner_id)

    def stop_file_browsing_by_user_and_server(self, user_id: str, server_id: Optional[str] = None):
        file_browsers = cast(
            list[Container],
            self.docker.containers.list(
                filters={
                    'label': create_labels_filter(user_id=user_id, volume_id=server_id, type=ServerType.FILE_BROWSER.value)

                }
            ),
        )
        for file_browser in file_browsers:
            file_browser.stop()

    def stop_file_browsing_by_id(self, browser_id: str):
        file_browser = self.get_file_browser_by_id(browser_id=browser_id)
        if file_browser is None:
            return
        try:
            container = cast(Container, self.docker.containers.get(file_browser.id_))
        except Exception as e:
            return
        container.stop()

    def list_server_ports(self, server_id: str) -> List[Port]:
        server_info = self.get_server_info(server_id=server_id)
        if not server_info.on:
            raise ServerNotRunning()

        assert server_info.ports is not None, 'ServerInfo.ports is None'

        return server_info.ports

    def get_server_logs(
        self,
        server_id: str,
        lines_limit: Optional[Union[int, str]] = None,
    ) -> str:
        if lines_limit is None:
            lines_limit = 'all'

        server_info = self.get_server_info(server_id=server_id)
        container = self._get_server_container(server_info=server_info, server_type=ServerType.GAME)

        if container is None:
            raise ServerNotRunning()

        logs = ANSI_ESCAPE.sub(b'', container.logs(tail=lines_limit))
        return _convert_to_string(logs)

    def list_file_browser_servers(self, user_id: Optional[str] = None) -> list[FileBrowserInfo]:
        containers = cast(list[Container], self.docker.containers.list(filters={'label': create_labels_filter(user_id=user_id, type=ServerType.FILE_BROWSER.value)}))
        server_info_list: list[FileBrowserInfo] = []
        for container in containers:
            assert isinstance(container.attrs, dict), f'Container.attrs is not dict {type(container.attrs)=}'

            labels = ContainerLabels(**container.attrs.get('Config', {}).get('Labels', {}))
            server_info = self.get_server_info(server_id=labels.volume_id)
            server_info_list.append(FileBrowserInfo(id_=container.id[:12], domain=f'browsers.{self._domain}', connected_to=server_info, owner_id=labels.user_id))

        return server_info_list

    def get_file_browser_by_user_and_server(self, user_id: str, server_id: str) -> Optional[FileBrowserInfo]:
        containers = cast(list[Container], self.docker.containers.list(filters={'label': create_labels_filter(user_id=user_id, volume_id=server_id, type=ServerType.FILE_BROWSER.value)}))
        if len(containers) == 0:
            return None
        container = containers[0]
        labels = ContainerLabels(**container.attrs.get('Config', {}).get('Labels', {}))
        server_info = self.get_server_info(server_id=labels.volume_id)
        return FileBrowserInfo(id_=container.id[:12], domain=f'browsers.{self._domain}', connected_to=server_info, owner_id=labels.user_id)

    def get_file_browser_by_id(self, browser_id: str) -> Optional[FileBrowserInfo]:
        try:
            container = self.docker.containers.get(browser_id)
        except Exception as e:
            return None
        
        labels = ContainerLabels(**container.attrs.get('Config', {}).get('Labels', {}))
        server_info = self.get_server_info(server_id=labels.volume_id)
        return FileBrowserInfo(id_=container.id[:12], domain=f'browsers.{self._domain}', connected_to=server_info, owner_id=labels.user_id)


    def stop_game_server(self, server_id: str) -> ServerInfo:
        server_info = self.get_server_info(server_id=server_id)
        if not server_info.on:
            raise ServerNotRunning()

        container = self._get_server_container(server_info=server_info, server_type=ServerType.GAME)
        if container is None:
            raise ServerNotRunning()

        container.stop()
        return self.get_server_info(server_id=server_id)

    @staticmethod
    def _extract_image_info_from_image(image: Image) -> list[ImageInfo]:
        image_info_list: list[ImageInfo] = []
        tags = image.tags
        assert isinstance(image.attrs, dict), f'Image.attrs is not a dictionary, {type(image.attrs)}'
        exposed_ports = image.attrs.get('Config', {}).get('ExposedPorts', {})
        ports: list[Port] = []
        for port, data in exposed_ports.items():
            port_number, protocol = port.split('/')
            ports.append(Port(number=port_number, protocol=protocol))

        for tag in tags:
            name, version = tag.split(':')
            image_info_list.append(ImageInfo(name=name, version=version, ports=set(ports)))

        return image_info_list

    @staticmethod
    def _extract_ports_from_container(container: Container) -> List[Port]:
        available_ports: list[Port] = []
        for key, value in container.ports.items():
            protocol = key.split('/')[-1]
            if value:
                host_ports = [v['HostPort'] for v in value]
                available_ports.extend(Port(number=port, protocol=protocol) for port in host_ports)
        return available_ports
