from contextlib import contextmanager
from datetime import datetime, timedelta
from typing_extensions import Annotated
from sqlalchemy.orm import Session
import secrets
import string
from typing import Annotated, Any, Optional, Union
import bcrypt
from fastapi import Depends, FastAPI, Form, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import requests
from api_code.database import models
from api_code.database.crud import create_user, get_user, get_users as get_all_users
from api_code.database.database import engine, SessionLocal
from docker_runner.docker_runner import DockerRunner
from docker_runner.container_runner.container_runner_interface import FileBrowserInfo, ServerInfo, Port, ImageInfo
from jose import JWTError, jwt
from passlib.context import CryptContext

from docker_runner.upnp_wrapper import UpnpClient
docker_runner = DockerRunner()

models.Base.metadata.create_all(bind=engine)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# oauth2_code_scheme = OAuth2AuthorizationCodeBearer(authorizationUrl='https://discord.com/oauth2/authorize?scope=guilds', tokenUrl='https://discord.com/api/oauth2/token', scopes={'guilds':'guilds'},)


oauth2_password_scheme = OAuth2PasswordBearer(tokenUrl='token')

SECRET_KEY = '7ce5bc4af7304247a472558dbc2853451a2b69f281a9d352966fea4ea4fec24c'
ALGORITHM = "HS256"
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


class PasswordRequestForm(OAuth2PasswordRequestForm):
    def __init__(self, *, 
                 grant_type: str | None = None, 
                 username: str, 
                 password: str, 
                 scope: str = "", 
                 client_id: str | None = None, 
                 client_secret: str | None = None, 
                 remember: bool = False,):
        super().__init__(grant_type=grant_type, username=username, password=password, scope=scope, client_id=client_id, client_secret=client_secret)
        self.remember = remember



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


def user_data(db_context: Annotated[Session, Depends(get_db)], token: Annotated[str, Depends(oauth2_password_scheme)]) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
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
    form_data: Annotated[PasswordRequestForm, Depends()]
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


def user_with_permissions(*permissions: models.Permission):
    def user_with_permissions_inner(user: Annotated[models.User, Depends(user_data)]):
        if set(permissions) - set(user.permissions) and models.Permission.ADMIN not in user.permissions:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user
    return user_with_permissions_inner


@app.get('/users')
def get_users(user: Annotated[models.User, Depends(user_data)]) -> list[models.UserBase]:
    with get_db() as db:
        return get_all_users(db)


class CreateUserRequest(BaseModel):
    username: str
    password: str
    email: str
    permissions: list[models.Permission]


@app.post('/users')
def create_user_api(user: Annotated[models.User, Depends(user_with_permissions(models.Permission.ADMIN))], request: CreateUserRequest) -> list[models.User]:
    with get_db() as db:
        return create_user(db, models.User(username=request.username, email=request.email, permissions=request.permissions, password_hash=get_password_hash(request.password)))


@app.get('/servers')
def get_servers(user: Annotated[models.User, Depends(user_data)]) -> list[ServerInfo]:
    docker_runner = DockerRunner()
    return sorted(docker_runner.list_servers(), key=lambda x: x.id_)

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

@app.post('/servers/{server_id}/start', summary='Start')
def start_server(user: Annotated[models.User, Depends(user_data)], server_id: str, request: StartServerRequest) -> ServerInfo:
    docker_runner = DockerRunner()
    server_info = docker_runner.start_game_server(server_id=server_id, ports={mapping.source_port: mapping.destination_port for mapping in request.ports} if len(request.ports) > 0 else None, command_parameters=request.command,)
    UpnpClient().add_port_mapping_using_server_info(server_info=server_info)
    return server_info


@app.post('/servers/{server_id}/stop', summary='Stop')
def stop_server(user: Annotated[models.User, Depends(user_data)], server_id: str) -> ServerInfo:
    docker_runner = DockerRunner()
    return docker_runner.stop_game_server(server_id=server_id)


class CreateServer(BaseModel):
    image_id: str


@app.post('/servers')
def create_server(user: Annotated[models.User, Depends(user_with_permissions(models.Permission.CREATE))], request: CreateServer) -> ServerInfo:
    docker_runner = DockerRunner()
    return docker_runner.create_game_server(image_id=request.image_id, user_id=user.username)


@app.delete('/servers/{server_id}')
def delete_server(user: Annotated[models.User, Depends(user_data)], server_id: str) -> None:
    docker_runner = DockerRunner()
    return docker_runner.delete_game_server(server_id=server_id)


class RunCommandRequest(BaseModel):
    command: str

@app.post('/servers/{server_id}/command')
def run_command(user: Annotated[models.User, Depends(user_data)], server_id: str, request: RunCommandRequest) -> str:
    if models.Permission.RUN_COMMAND not in user.permissions and models.Permission.ADMIN not in user.permissions:
        raise HTTPException(401, 'Unauthorized')
    docker_runner = DockerRunner()
    response = docker_runner.run_command(server_id=server_id, command=request.command)
    if response is None:
        raise Exception()  # TODO: change to HTTP exception
    return response


@app.get('/servers/{server_id}/logs')
def get_server_logs(user: Annotated[models.User, Depends(user_data)], server_id: str) -> str:
    docker_runner = DockerRunner()
    response = docker_runner.get_server_logs(server_id=server_id)

    if response is None:
        raise Exception()  # TODO: change to HTTP exception
    
    return response


class FileBrowserData(BaseModel):
    url: str
    username: str
    password: str


@app.post('/browsers/{server_id}')
def start_file_browser(user: Annotated[models.User, Depends(user_data)], server_id: str) -> FileBrowserData:
    alphabet = string.ascii_letters + string.digits + string.punctuation
    alphabet = ''.join(x for x in alphabet if x != '`')
    password = ''.join([secrets.choice(alphabet) for _ in range(12)])
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    file_browser_server_info = docker_runner.start_file_browser(server_id=server_id, owner_id=user.username, hashed_password=hashed_password)
    if file_browser_server_info.ports is None:
        raise Exception()
    
    url = f'http://{docker_runner._domain}:{file_browser_server_info.ports[0].number}'    
    
    return FileBrowserData(url=url, username='admin', password=password)


@app.get('/browsers')
def get_file_browsers(user: Annotated[models.User, Depends(user_data)]) -> list[FileBrowserInfo]:
    docker_runner = DockerRunner()
    return docker_runner.list_file_browser_servers(user_id=user.username)


@app.delete('/browsers/{server_id}')
def stop_file_browser(user: Annotated[models.User, Depends(user_data)], server_id: str):
    docker_runner = DockerRunner()
    docker_runner.stop_file_browsing(user_id=user.username, server_id=server_id)
