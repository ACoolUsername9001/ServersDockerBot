import socket
import logging
from typing import Optional, List, Any
import upnpclient
from .docker_runner import DockerRunner
from .container_runner.container_runner_interface import ContainerRunner
from enum import Enum

class Protocol(str, Enum):
    TCP = 'TCP'
    UDP = 'UDP'


class UPNPWrapper(ContainerRunner):

    def __init__(self, container_runner: ContainerRunner):
        self._devices = [device for device in upnpclient.discover() if 'AddPortMapping' in (action.name for action in device.actions)]
        self._container_runner = container_runner
        self._local_addr = self._get_ip()
        print(f'Local IP Address: {self._local_addr}')

    @staticmethod
    def _open_ports_decorator(func):
        def inner(self, *args, **kwargs):
            res = func(self, *args, **kwargs)
            for port, protocol in (r.split('/') for r in res):
                self._add_port_mapping(local_addr=self._local_addr, local_port=int(port), remote_port=int(port), protocol=protocol)
            return res
        return inner

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
                    NewProtocol=protocol
                    )
            except Exception as e:
                print(f'Faield to open {remote_addr}:{remote_port}->{local_addr}:{local_port} {protocol}, {e}')

    def _remove_port_mapping(self, protocol: Protocol, remote_port: int, remote_addr: str = ''):
        for device in self._devices:
            try:
                device.find_action('DeletePortMapping')(
                    NewExternalPort=remote_port, 
                    NewRemoteHost=remote_addr,
                    NewProtocol=protocol
                )
            except Exception as e:
                logging.error(f'Faield to closed {remote_addr}:{remote_port} {protocol}, {e}', exc_info=True)

    def get_user_id_and_image_name_from_game_server_name(self, server_name):
        return self._container_runner.get_user_id_and_image_name_from_game_server_name(server_name=server_name)

    def get_user_id_and_image_name_from_file_browser_name(self, server_name):
        return self._container_runner.get_user_id_and_image_name_from_file_browser_name(server_name=server_name)

    def list_game_ports(self, tag) -> list[str]:
        return self._container_runner.list_game_ports(tag=tag)

    def list_server_names(self, user_id=None, prefix: Optional[str] = None) -> List[str]:
        return self._container_runner.list_server_names(user_id=user_id, prefix=prefix)

    def list_running_server_names(self, user_id=None, prefix: Optional[str] = None) -> List[str]:
        return self._container_runner.list_running_server_names(user_id=user_id, prefix=prefix)

    def list_stopped_server_names(self, user_id: Optional[Any] = None, prefix: Optional[str] = None) -> List[str]:
        return self._container_runner.list_stopped_server_names(user_id=user_id, prefix=prefix)

    def list_file_browser_names(self, user_id) -> List[str]:
        return self._container_runner.list_file_browser_names(user_id=user_id)

    def list_game_names(self) -> List[str]:
        return self._container_runner.list_game_names()

    def create_game_server(self, user_id, game: str) -> str:
        return self._container_runner.create_game_server(user_id=user_id, game=game)

    def get_ports_from_container(self, container) -> List[str]:
        return self._container_runner.get_ports_from_container(container=container)

    @_open_ports_decorator
    def start_game_server(self, game, ports: Optional[List[str]] = None, command_parameters: Optional[str] = None) -> List[str]:
        return self._container_runner.start_game_server(game=game, ports=ports, command_parameters=command_parameters)

    def run_command(self, server, command) -> Optional[str]:
        return self._container_runner.run_command(server=server, command=command)

    def delete_game_server(self, user_id, game):
        return self._container_runner.delete_game_server(user_id=user_id, game=game)

    @_open_ports_decorator
    def start_file_browser(self, server, executor_id, hashed_password=None) -> List[str]:
        return self._container_runner.start_file_browser(server=server, executor_id=executor_id)

    def stop_file_browsing(self, user_id, server: Optional[str] = None):
        return self._container_runner.stop_file_browsing(user_id=user_id, server=server)

    def list_server_ports(self, server) -> List[str]:
        return self._container_runner.list_server_ports(server=server)

    def get_server_logs(self, server, lines_limit: Optional[int] = None) -> str:
        return self._container_runner.get_server_logs(server=server, lines_limit=lines_limit)
