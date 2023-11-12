

from enum import Enum
from typing import Self

from pydantic import BaseModel
from sqlalchemy import Column, Integer, String

from .database import Base


class Permission(str, Enum):
    CREATE = 'create'
    START = 'start'
    BROWSE = 'browse'
    RUN_COMMAND = 'run-command'
    SEE_ALL = 'see-all'
    DELETE = 'delete'
    STOP = 'stop'
    ADMIN = 'admin'


class UserBase(BaseModel):
    username: str
    email: str
    permissions: list[Permission]

    @classmethod
    def from_database_user(cls, database_user: 'DatabaseUser') -> Self:
        permissions = database_user.scope.split(':')
        return cls(
            username=database_user.username,
            email=database_user.email,
            permissions=permissions,
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
            password_hash = database_user.password_hash,
        )


class DatabaseUser(Base):
    __tablename__ = 'users'
    
    username = Column(String, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    password_hash = Column(String)
    scope = Column(String)
    

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