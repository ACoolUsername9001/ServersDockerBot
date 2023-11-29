from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import wraps
import json
import logging
from typing_extensions import Annotated
from uuid import uuid4
from sqlalchemy.orm import Session
from typing import Annotated, Literal, Optional, cast
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from api_code.database import models
from api_code.database.crud import change_permissions, change_server_nickname, create_token, create_user, create_user_from_token, delete_user, get_all_server_nicknames, get_server_permissions_for_user, get_user, get_users as get_all_users, set_server_permissions_for_user
from api_code.database.database import engine, SessionLocal
from docker_runner.docker_runner import DockerRunner
from docker_runner.container_runner.container_runner_interface import FileBrowserInfo, ServerInfo, Port, ImageInfo
from jose import JWTError, jwt
from passlib.context import CryptContext

from docker_runner.upnp_wrapper import UpnpClient
from mail import MailClient

models.Base.metadata.create_all(bind=engine)

class MailConfig(BaseModel):
    username: str
    password: str
    domain: str


class SiteConfig(BaseModel):
    key: str
    algorithm: str


class Config(BaseModel):
    mail: MailConfig
    backend: SiteConfig


with open('credentials.json', 'r') as f:
    CONFIG = Config(**json.load(f))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class JsonSchemaExtraRequest(BaseModel):
    fetch_url: str
    fetch_key_path: str
    fetch_display_path: str


class OpenApiExtra(BaseModel):
    api_response: Literal['Ignore', 'Browse'] = 'Ignore'
    permissions: list[models.Permission] = Field(default_factory=list)


oauth2_password_scheme = HTTPBearer()

SECRET_KEY = CONFIG.backend.key
ALGORITHM = CONFIG.backend.algorithm

ACCESS_TOKEN_EXPIRE_MINUTES = 30

app = FastAPI()

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PasswordRequestForm(BaseModel):
    username: str
    password: str
    remember: bool|str = False


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def authenticate_user(db_context, username: str, password: str):
    with db_context as db:
        user = get_user(db, username)
    if not user:
        return False
    if not verify_password(password, user.password_hash):
        return False
    return user


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# Dependency
@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def user_data(db_context: Annotated[Session, Depends(get_db)], token: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_password_scheme)]) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get('sub')
        if username is None:
            raise credentials_exception
        data = TokenData(username=username)

    except JWTError:
        raise credentials_exception
    with db_context as db:
        user = get_user(db, data.username)
    
    if user is None:
        raise credentials_exception
    
    return user


@app.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: PasswordRequestForm,
):
    user = authenticate_user(get_db(), form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if form_data.remember:
        access_token_expires = timedelta(days=30)
    else:
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return Token(access_token=access_token, token_type="bearer")


def user_with_permissions(*permissions):        

    def users_with_permissions_or_owner(user: Annotated[models.User, Depends(user_data)], server_id: Optional[str] = None) -> models.User:
        missing_permissions = set(permissions) - set(user.permissions)
        permissions_allowed = len(missing_permissions) == 0 or models.Permission.ADMIN in user.permissions
        
        if permissions_allowed:
            return user
        
        if not server_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        

        server_info = DockerRunner().get_server_info(server_id=server_id)

        if server_info.user_id == user.username:    
            return user
        
        with get_db() as db:
            server_permissions = get_server_permissions_for_user(db, server_id=server_id, user_id=user.username)
        
        if not server_permissions:
            logging.warning(f'User {user.username} has no special permissions for this servrer')
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission Denied",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        if len(missing_permissions - set(server_permissions.permissions)) == 0 or models.Permission.ADMIN in server_permissions.permissions:
            return user

        raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
    return users_with_permissions_or_owner


@app.get('/users')
def get_users(user: Annotated[models.User, Depends(user_data)]) -> list[models.UserBase]:
    with get_db() as db:
        return cast(list[models.UserBase], get_all_users(db))


class InviteUserRequests(BaseModel):
    email: str
    permissions: list[models.Permission]


@app.post('/users', summary='Invite User', openapi_extra=OpenApiExtra(api_response='Ignore', permissions=[models.Permission.ADMIN]).model_dump(mode='json'))
def invite_user_api(user: Annotated[models.User, Depends(user_with_permissions(models.Permission.ADMIN))], request: InviteUserRequests) -> InviteUserRequests:
    token_str = f'{uuid4()}'
    with get_db() as db:
        token = create_token(db, token=models.SignupToken(token=token_str, email=request.email, permissions=request.permissions))
        
    m = MailClient(**CONFIG.mail.model_dump())
    m.send_message(token.email, 'You have been invited to join ACoolGameManagement', f'please open this link: https://games.acooldomain.co/signup?token={token.token}')
    m.quit()
    
    return request


class CreateUserRequest(BaseModel):
    username: str
    password: str


@app.get('/users/@me')
def get_self(user: Annotated[models.User, Depends(user_data)]) -> models.UserBase:
    return user


@app.post('/signup')
def sign_up(token: str, request: CreateUserRequest) -> models.UserBase:
    with get_db() as db:
        return create_user_from_token(db, token=token, username=request.username, password_hash=get_password_hash(request.password))


@app.delete('/users/{username}', name='Delete', openapi_extra=OpenApiExtra(api_response='Ignore', permissions=[models.Permission.ADMIN]).model_dump(mode='json'))
def delete_user_api(user: Annotated[models.User, Depends(user_with_permissions(models.Permission.ADMIN))], username: str):
    with get_db() as db:
        delete_user(db, username=username)


class ChangeUserRequest(BaseModel):
    permissions: list[models.Permission]


@app.post('/users/{username}/permissions', name='Change Permissions', openapi_extra=OpenApiExtra(api_response='Ignore', permissions=[models.Permission.ADMIN]).model_dump(mode='json'))
def change_user_data(user: Annotated[models.User, Depends(user_with_permissions(models.Permission.ADMIN))], username: str, request: ChangeUserRequest):
    with get_db() as db:
        change_permissions(db, username, request.permissions)


@app.get('/servers')
def get_servers(user: Annotated[models.User, Depends(user_data)]) -> list[ServerInfo]:
    docker_runner = DockerRunner()
    servers = docker_runner.list_servers()
    with get_db() as db:
        nicknames = get_all_server_nicknames(db)

    for server in servers:
        server.nickname = nicknames.get(server.id_)

    return sorted(servers, key=lambda x: x.id_)

@app.get('/images')
def get_images(user: Annotated[models.User, Depends(user_data)]) -> list[ImageInfo]:
    docker_runner = DockerRunner()
    return docker_runner.list_images()

@app.get('/servers/{server_id}', include_in_schema=False)
def get_server(user: Annotated[models.User, Depends(user_data)], server_id: str) -> ServerInfo:
    docker_runner = DockerRunner()
    return docker_runner.get_server_info(server_id=server_id)


class PortMapping(BaseModel):
    source_port: Port
    destination_port: Optional[Port] = None

class StartServerRequest(BaseModel):
    ports: list[PortMapping] = []
    command: Optional[str] = None

@app.post('/servers/{server_id}/start', summary='Start', openapi_extra=OpenApiExtra(api_response='Ignore', permissions=[models.Permission.START]).model_dump(mode='json'))
def start_server(user: Annotated[models.User, Depends(user_with_permissions(models.Permission.START))], server_id: str, request: StartServerRequest) -> ServerInfo:
    docker_runner = DockerRunner()
    server_info = docker_runner.start_game_server(server_id=server_id, ports={mapping.source_port: mapping.destination_port for mapping in request.ports} if len(request.ports) > 0 else None, command_parameters=request.command,)
    UpnpClient().add_port_mapping_using_server_info(server_info=server_info)
    return server_info


@app.post('/servers/{server_id}/stop', summary='Stop', openapi_extra=OpenApiExtra(api_response='Ignore', permissions=[models.Permission.STOP]).model_dump(mode='json'))
def stop_server(user: Annotated[models.User, Depends(user_with_permissions(models.Permission.STOP))], server_id: str) -> ServerInfo:
    docker_runner = DockerRunner()
    return docker_runner.stop_game_server(server_id=server_id)


class CreateServer(BaseModel):
    image_id: str = Field(json_schema_extra=JsonSchemaExtraRequest(fetch_url='/images', fetch_key_path='id_', fetch_display_path='display_name').model_dump())


@app.post('/servers', openapi_extra=OpenApiExtra(api_response='Ignore', permissions=[models.Permission.CREATE]).model_dump(mode='json'))
def create_server(user: Annotated[models.User, Depends(user_with_permissions(models.Permission.CREATE))], request: CreateServer) -> ServerInfo:
    docker_runner = DockerRunner()
    if not models.Permission.ADMIN in user.permissions and user.max_owned_servers < len(docker_runner.list_servers(user_id=user.username)):
        raise HTTPException(401, 'Unauthorized, Max servers count reached')
        
    return docker_runner.create_game_server(image_id=request.image_id, user_id=user.username)


@app.delete('/servers/{server_id}', openapi_extra=OpenApiExtra(api_response='Ignore', permissions=[models.Permission.DELETE]).model_dump(mode='json'))
def delete_server(user: Annotated[models.User, Depends(user_with_permissions(models.Permission.DELETE))], server_id: str) -> None:
    docker_runner = DockerRunner()
    return docker_runner.delete_game_server(server_id=server_id)


class RunCommandRequest(BaseModel):
    command: str

@app.post('/servers/{server_id}/command', openapi_extra=OpenApiExtra(api_response='Ignore', permissions=[models.Permission.RUN_COMMAND]).model_dump(mode='json'))
def run_command(user: Annotated[models.User, Depends(user_with_permissions(models.Permission.RUN_COMMAND))], server_id: str, request: RunCommandRequest) -> str:
    docker_runner = DockerRunner()
    response = docker_runner.run_command(server_id=server_id, command=request.command)
    if response is None:
        raise Exception()  # TODO: change to HTTP exception
    return response


@app.get('/servers/{server_id}/logs', include_in_schema=False)
def get_server_logs(user: Annotated[models.User, Depends(user_data)], server_id: str) -> str:
    docker_runner = DockerRunner()
    response = docker_runner.get_server_logs(server_id=server_id)

    if response is None:
        raise Exception()  # TODO: change to HTTP exception
    
    return response


class FileBrowserData(BaseModel):
    url: str


class StartFileBrowserRequest(BaseModel):
    server_id: str = Field(json_schema_extra=JsonSchemaExtraRequest(fetch_url='/servers', fetch_key_path='id_', fetch_display_path='nickname').model_dump(by_alias=True))


@app.post('/browsers', openapi_extra=OpenApiExtra(api_response='Ignore', permissions=[models.Permission.BROWSE]).model_dump(mode='json'))
def start_file_browser(user: Annotated[models.User, Depends(user_with_permissions(models.Permission.BROWSE))], server_id: StartFileBrowserRequest) -> FileBrowserData:
    docker_runner = DockerRunner()
    file_browser_server_info = docker_runner.start_file_browser(server_id=server_id.server_id, owner_id=user.username, hashed_password=user.password_hash)
    return FileBrowserData(url=file_browser_server_info.url)


@app.get('/browsers')
def get_file_browsers(user: Annotated[models.User, Depends(user_data)]) -> list[FileBrowserInfo]:
    docker_runner = DockerRunner()
    return docker_runner.list_file_browser_servers(user_id=user.username)

class StopFileBrowserRequest(BaseModel):
    server_id: str = Field(json_schema_extra=JsonSchemaExtraRequest(fetch_url='/servers', fetch_key_path='id_', fetch_display_path='nickname').model_dump(by_alias=True))

@app.delete('/browsers')
def stop_file_browser(user: Annotated[models.User, Depends(user_data)], server_id: StopFileBrowserRequest):
    docker_runner = DockerRunner()
    docker_runner.stop_file_browsing(user_id=user.username, server_id=server_id.server_id)


class SetServerNicknameRequest(BaseModel):
    nickname: str


@app.post('/servers/{server_id}/nickname', summary='Set Nickname', description='Set Nickname', openapi_extra=OpenApiExtra(api_response='Ignore', permissions=[models.Permission.ADMIN]).model_dump(mode='json'))
def api_set_server_nickname(user: Annotated[models.User, Depends(user_with_permissions(models.Permission.ADMIN))], server_id: str, set_server_nickname_request: SetServerNicknameRequest):
    DockerRunner().get_server_info(server_id=server_id)

    with get_db() as db:
        return change_server_nickname(db, server_nickname=models.ServerNickname(server_id=server_id, nickname=set_server_nickname_request.nickname))


class SetServerPermissionsRequest(BaseModel):
    username: str = Field(json_schema_extra=JsonSchemaExtraRequest(fetch_url='/users', fetch_key_path='username', fetch_display_path='username').model_dump(by_alias=True))
    permissions: list[models.Permission] = Field(default_factory=list)


@app.post('/servers/{server_id}/permissions', summary='Add Permissions', openapi_extra=OpenApiExtra(api_response='Ignore', permissions=[models.Permission.ADMIN]).model_dump(mode='json'))
def api_set_server_user_permissions(user: Annotated[models.User, Depends(user_with_permissions(models.Permission.ADMIN))], server_id: str, request: SetServerPermissionsRequest):
    DockerRunner().get_server_info(server_id=server_id)
    with get_db() as db:
        set_server_permissions_for_user(db, models.ServerPermissions(server_id=server_id, user_id=request.username, permissions=request.permissions))


@app.get('/servers/{server_id}/permissions', summary='Get Permissions', include_in_schema=False)
def api_get_server_user_permissions(user: Annotated[models.User, Depends(user_data)], server_id: str) -> list[models.Permission]:
    with get_db() as db:
        permissions = get_server_permissions_for_user(db, server_id=server_id, user_id=user.username)
    if permissions is None:
        return []

    return permissions.permissions
