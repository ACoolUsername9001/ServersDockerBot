

from enum import Enum
from typing import Self

from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String

from .database import Base


class Permission(str, Enum):
    CREATE = 'create'
    START = 'start'
    BROWSE = 'browse'
    RUN_COMMAND = 'run-command'
    DELETE = 'delete'
    STOP = 'stop'
    ADMIN = 'admin'


class UserBase(BaseModel):
    username: str
    email: str
    max_owned_servers: int = 5
    permissions: list[Permission] = Field(default_factory=list)

    @classmethod
    def from_database_user(cls, database_user: 'DatabaseUser') -> Self:
        permissions = database_user.scope.split(':')
        return cls(
            username=database_user.username,
            email=database_user.email,
            permissions=permissions,
            max_owned_servers=database_user.max_owned_servers,
        )


class User(UserBase):
    password_hash: str
    @classmethod
    def from_database_user(cls, database_user: 'DatabaseUser') -> Self:
        permissions = database_user.scope.split(':')
        return cls(
            username=database_user.username,
            email=database_user.email,
            permissions=permissions,
            password_hash=database_user.password_hash,
            max_owned_servers=database_user.max_owned_servers,
        )


class DatabaseUser(Base):
    __tablename__ = 'users'
    
    username = Column(String, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    scope = Column(String)
    max_owned_servers=Column(Integer, default=5)
    

class DatabaseSignupToken(Base):
    __tablename__ = 'tokens'
    
    token = Column(String, primary_key=True, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    scope = Column(String)
    

class SignupToken(BaseModel):
    token: str
    email: str
    permissions: list[Permission]

    @classmethod
    def from_database_token(cls, database_token: DatabaseSignupToken) -> Self:
        permissions = database_token.scope.split(':')
        return cls(
            email=database_token.email,
            permissions=permissions,
            token=database_token.token,
        )
    
class DatabaseServerNickname(Base):
    __tablename__ = 'server_nicknames'
    server_id = Column(String, index=True, unique=True, primary_key=True)
    nickname = Column(String, index=True, unique=True)

class DatabasePermissions(Base):
    __tablename__ = 'server_permissions'
    index = Column(Integer, index=True, unique=True, autoincrement=True, primary_key=True)
    server_id = Column(String, index=True)
    user_id = Column(String, index=True)
    scope = Column(String)


class ServerNickname(BaseModel):
    server_id: str
    nickname: str

    @classmethod
    def from_database_nickname(cls, database_nickname: DatabaseServerNickname) -> Self:
        return cls(
            server_id=database_nickname.server_id,
            nickname=database_nickname.nickname,
        )

class ServerPermissions(BaseModel):
    server_id: str
    user_id: str
    permissions: list[Permission] = Field(default_factory=list)

    @classmethod
    def from_database_permissions(cls, database_permissions: DatabasePermissions) -> Self:
        permissions = database_permissions.scope.split(':')
        return cls(
            server_id=database_permissions.server_id,
            user_id=database_permissions.user_id,
            permissions=permissions,
        )