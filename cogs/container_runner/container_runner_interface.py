from typing import Protocol, Optional, List, Any


class ContainerRunner(Protocol):

    @staticmethod
    def get_user_id_and_image_name_from_game_server_name(server_name) -> tuple[Optional[str], Optional[str]]:
        ...

    @staticmethod
    def get_user_id_and_image_name_from_file_browser_name(server_name) -> tuple[Optional[str], Optional[str]]:
        ...

    def list_game_ports(self, tag) -> list[str]:
        ...

    def list_server_names(self, user_id=None, prefix: Optional[str] = None) -> List[str]:
        ...

    def list_running_server_names(self, user_id=None, prefix: Optional[str] = None) -> List[str]:
        ...

    def list_stopped_server_names(self, user_id: Optional[Any] = None, prefix: Optional[str] = None) -> List[str]:
        ...

    def list_file_browser_names(self, user_id) -> List[str]:
        ...

    def list_game_names(self) -> List[str]:
        ...

    def create_game_server(self, user_id, game: str, custom_name: Optional[str] = None) -> str:
        ...

    @staticmethod
    def get_ports_from_container(container) -> List[str]:
        ...

    def start_game_server(self, game, ports: Optional[List[str]] = None, command_parameters: Optional[str] = None) -> List[str]:
        ...

    def run_command(self, server, command) -> Optional[str]:
        ...

    def delete_game_server(self, user_id, game):
        ...

    def start_file_browser(self, server, executor_id, hashed_password=None) -> List[str]:
        ...

    def stop_file_browsing(self, user_id, server: Optional[str] = None):
        ...

    def list_server_ports(self, server) -> List[str]:
        ...

    def get_server_logs(self, server, lines_limit: Optional[int] = None) -> str:
        ...
