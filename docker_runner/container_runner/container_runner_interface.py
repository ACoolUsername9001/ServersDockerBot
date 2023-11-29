import abc
from enum import Enum
from typing import Optional, List, Protocol, Union

from pydantic import BaseModel, Field, computed_field


class PortProtocol(str, Enum):
    TCP = 'tcp'
    UDP = 'udp'


class ServerType(str, Enum):
    GAME = 'GAME'
    FILE_BROWSER = 'FILE-BROWSER'


class Port(BaseModel):
    number: int = Field(lt=65535, gt=1)
    protocol: PortProtocol

    @computed_field()
    @property
    def id_(self) -> str:
        return f'{self.number}/{self.protocol.value}'

    def __hash__(self) -> int:
        return hash(self.id_)


class ImageInfo(BaseModel):
    name: str
    version: str
    ports: set[Port] = Field(default_factory=set)

    @computed_field()
    @property
    def id_(self) -> str:
        return f'{self.name}:{self.version}'
    
    @computed_field()
    @property
    def display_name(self) -> str:
        return f'{self.name} {self.version}'.title()


class ServerInfo(BaseModel):
    id_: str
    user_id: str
    image: ImageInfo
    on: bool
    domain: Optional[str] = None
    ports: Optional[set[Port]] = None
    nickname: Optional[str] = None

class FileBrowserInfo(BaseModel):
    id_: str
    owner_id: str
    domain: str
    connected_to: ServerInfo
    
    @computed_field()
    @property
    def url(self) -> str:
        return f'{self.id_}.{self.domain}'


class ContainerRunner(Protocol):
    @abc.abstractmethod
    def get_image_info(self, image_id: str) -> ImageInfo:
        ...

    @abc.abstractmethod
    def get_server_info(self, server_id: str, server_type: ServerType = ServerType.GAME) -> ServerInfo:
        ...

    @abc.abstractmethod
    def list_file_browser_servers(self, user_id: str) -> list[FileBrowserInfo]:
        ...

    @abc.abstractmethod
    def list_images(self) -> List[ImageInfo]:
        ...

    @abc.abstractmethod
    def create_game_server(self, user_id: str, image_id: str) -> ServerInfo:
        ...

    @abc.abstractmethod
    def list_servers(self, user_id: Optional[str] = None, image_id: Optional[str] = None, type: ServerType = ServerType.GAME) -> List[ServerInfo]:
        ...


    @abc.abstractmethod
    def start_game_server(self, server_id: str, ports: Optional[dict[Port, Optional[Port]]] = None, command_parameters: Optional[str] = None) -> ServerInfo:
        ...

    @abc.abstractmethod
    def stop_game_server(self, server_id: str) -> ServerInfo:
        ...

    @abc.abstractmethod
    def run_command(self, server_id: str, command: str) -> Optional[str]:
        ...

    @abc.abstractmethod
    def delete_game_server(self, server_id: str):
        ...

    @abc.abstractmethod
    def start_file_browser(self, server_id: str, owner_id: str, hashed_password=None) -> FileBrowserInfo:
        ...

    @abc.abstractmethod
    def stop_file_browsing(self, user_id: str, server_id: Optional[str] = None):
        ...

    @abc.abstractmethod
    def get_server_logs(
        self,
        server_id: str,
        lines_limit: Optional[Union[int, str]] = None,
    ) -> str:
        ...
