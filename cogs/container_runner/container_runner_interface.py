from typing import Protocol, Optional, List, Any


class ContainerRunner(Protocol):

    @staticmethod
    def get_user_id_and_image_name_from_game_server_name(server_name):
        pass

    @staticmethod
    def get_user_id_and_image_name_from_file_browser_name(server_name):
        pass

    def list_game_ports(self, tag) -> list[str]:
        pass

    def list_server_names(self, user_id=None, prefix: Optional[str] = None) -> List[str]:
        pass

    def list_running_server_names(self, user_id=None, prefix: Optional[str] = None) -> List[str]:
        pass

    def list_stopped_server_names(self, user_id: Optional[Any] = None, prefix: Optional[str] = None) -> List[str]:
        pass

    def list_file_browser_names(self, user_id) -> List[str]:
        pass

    def list_game_names(self) -> List[str]:
        pass

    def create_game_server(self, user_id, game: str) -> str:
        pass

    @staticmethod
    def get_ports_from_container(container) -> List[str]:
        pass

    def start_game_server(self, game, ports: Optional[List[str]] = None, command_parameters: Optional[str] = None) -> List[str]:
        pass

    def run_command(self, server, command) -> Optional[str]:
        pass

    def delete_game_server(self, user_id, game):
        pass

    def start_file_browser(self, server, executor_id, hashed_password=None) -> List[str]:
        pass

    def stop_file_browsing(self, user_id, server: Optional[str] = None):
        pass

    def list_server_ports(self, server) -> List[str]:
        pass

    def get_server_logs(self, server, lines_limit: Optional[int] = None) -> str:
        pass
