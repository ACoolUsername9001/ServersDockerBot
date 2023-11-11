import socket
import logging
from typing import Optional, List, Union
import upnpclient

from docker_runner.container_runner.container_runner_interface import ContainerRunner, ImageInfo, Port, ServerInfo, ServerType
from enum import Enum


class Protocol(str, Enum):
    TCP = 'TCP'
    UDP = 'UDP'


class UpnpClient:
    def __init__(self):
        self._devices = [device for device in upnpclient.discover(timeout=0.1) if 'AddPortMapping' in (action.name for action in device.actions)]
        self._local_addr = self._get_ip()

    @classmethod
    def _get_ip(cls):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        try:
            # doesn't even have to be reachable
            s.connect(('8.8.8.8', 1))
            IP = s.getsockname()[0]
        except Exception:
            IP = '127.0.0.1'
        finally:
            s.close()
        return IP

    def add_port_mapping_using_server_info(self, server_info: ServerInfo):
        
        if server_info.ports is None:
            return server_info

        for port in server_info.ports:
            self.add_port_mapping(local_port=port.number, remote_port=port.number, protocol=Protocol(port.protocol.upper()))
        return server_info


    def add_port_mapping(self, protocol: Protocol, local_port: int, remote_addr: str = '', remote_port: Optional[int] = None):
        for device in self._devices:
            try:
                device.find_action('AddPortMapping')(
                    NewEnabled='1',
                    NewInternalClient=self._local_addr,
                    NewInternalPort=local_port,
                    NewExternalPort=remote_port if remote_port is not None else local_port,
                    NewRemoteHost=remote_addr,
                    NewLeaseDuration=0,
                    NewPortMappingDescription=f'{self._local_addr}:{local_port} to {remote_addr}:{remote_port} {protocol}',
                    NewProtocol=protocol,
                )
            except Exception as e:
                print(f'Faield to open {remote_addr}:{remote_port}->{self._local_addr}:{local_port} {protocol}, {e}')

class UPNPWrapper(ContainerRunner):
    def __init__(self, container_runner: ContainerRunner):
        self._devices = [device for device in upnpclient.discover(timeout=0.1) if 'AddPortMapping' in (action.name for action in device.actions)]
        self._container_runner = container_runner
        self._local_addr = self._get_ip()
        print(f'Local IP Address: {self._local_addr}')

    @staticmethod
    def _open_ports_decorator(func):
        def inner(self, *args, **kwargs):
            server_info: ServerInfo = func(self, *args, **kwargs)
            if server_info.ports is None:
                return server_info

            for port in server_info.ports:
                self._add_port_mapping(local_addr=self._local_addr, local_port=port.number, remote_port=port.number, protocol=port.protocol.upper())
            return server_info

        return inner

    def _add_port_mapping(self, protocol: Protocol, local_addr: str, local_port: int, remote_addr: str = '', remote_port: Optional[int] = None):
        for device in self._devices:
            try:
                device.find_action('AddPortMapping')(
                    NewEnabled='1',
                    NewInternalClient=local_addr,
                    NewInternalPort=local_port,
                    NewExternalPort=remote_port if remote_port is not None else local_port,
                    NewRemoteHost=remote_addr,
                    NewLeaseDuration=0,
                    NewPortMappingDescription=f'{local_addr}:{local_port} to {remote_addr}:{remote_port} {protocol}',
                    NewProtocol=protocol,
                )
            except Exception as e:
                print(f'Faield to open {remote_addr}:{remote_port}->{local_addr}:{local_port} {protocol}, {e}')

    def _remove_port_mapping(self, protocol: Protocol, remote_port: int, remote_addr: str = ''):
        for device in self._devices:
            try:
                device.find_action('DeletePortMapping')(NewExternalPort=remote_port, NewRemoteHost=remote_addr, NewProtocol=protocol)
            except Exception as e:
                logging.error(f'Faield to closed {remote_addr}:{remote_port} {protocol}, {e}', exc_info=True)

    def get_image_info(self, image_id: str) -> ImageInfo:
        return self.get_image_info(image_id=image_id)

    def list_servers(self, user_id: str | None = None, image_id: str | None = None, type: ServerType = ServerType.GAME) -> List[ServerInfo]:
        return self._container_runner.list_servers(user_id=user_id, image_id=image_id, type=type)

    def get_server_info(self, server_id: str, server_type: ServerType = ServerType.GAME) -> ServerInfo:
        return self._container_runner.get_server_info(server_id=server_id, server_type=server_type)

    def list_file_browser_servers(self, user_id: str) -> list[ServerInfo]:
        return self._container_runner.list_file_browser_servers(user_id=user_id)

    def list_images(self) -> List[ImageInfo]:
        return self._container_runner.list_images()

    def create_game_server(self, user_id: str, image_id: str) -> ServerInfo:
        return self._container_runner.create_game_server(user_id=user_id, image_id=image_id)

    @_open_ports_decorator
    def start_game_server(self, server_id: str, ports: Optional[dict[Port, Optional[Port]]] = None, command_parameters: Optional[str] = None) -> ServerInfo:
        return self._container_runner.start_game_server(server_id=server_id, ports=ports, command_parameters=command_parameters)

    def stop_game_server(self, server_id: str) -> ServerInfo:
        return self._container_runner.stop_game_server(server_id=server_id)

    def run_command(self, server_id: str, command: str) -> Optional[str]:
        return self._container_runner.run_command(server_id=server_id, command=command)

    def delete_game_server(self, server_id: str):
        return self._container_runner.delete_game_server(server_id=server_id)

    @_open_ports_decorator
    def start_file_browser(self, server_id: str, owner_id: str, hashed_password=None) -> ServerInfo:
        return self._container_runner.start_file_browser(server_id=server_id, owner_id=owner_id, hashed_password=hashed_password)

    def stop_file_browsing(self, user_id: str, server_id: Optional[str] = None):
        return self._container_runner.stop_file_browsing(user_id=user_id, server_id=server_id)

    def get_server_logs(
        self,
        server_id: str,
        lines_limit: Optional[Union[int, str]] = None,
    ) -> str:
        return self._container_runner.get_server_logs(server_id=server_id, lines_limit=lines_limit)
