from typing import Optional
from sqlalchemy.orm import Session
from . import models


def get_user(db: Session, user_id: str) -> Optional[models.User]:
    user = db.query(models.DatabaseUser).filter(models.DatabaseUser.username == user_id).first()
    return models.User.from_database_user(user) if user is not None else user

def get_token(db: Session, token: str) -> Optional[models.SignupToken]:
    token = db.query(models.DatabaseSignupToken).filter(models.DatabaseSignupToken.token == token).first()
    return models.SignupToken.from_database_token(token)


def get_user_by_email(db: Session, email: str) -> Optional[models.User]:
    user = db.query(models.DatabaseUser).filter(models.DatabaseUser.email == email).first()
    return models.User.from_database_user(user) if user is not None else user


def get_users(db: Session, skip: int = 0, limit: int = 100) -> list[models.User]:
    return [models.User.from_database_user(user) for user in db.query(models.DatabaseUser).offset(skip).limit(limit).all()]


def create_user(db: Session, user: models.User):
    db_user = models.DatabaseUser(email=user.email, password_hash=user.password_hash, username=user.username, scope=':'.join(user.permissions))

    user = db.query(models.DatabaseUser).filter(models.DatabaseUser.username == db_user.username).delete()
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return models.User.from_database_user(db_user)


def delete_user(db: Session, username: str):
    db.query(models.DatabaseUser).filter(models.DatabaseUser.username == username).delete()
    db.commit()


def create_user_from_token(db: Session, token: str, username: str, password_hash: str):
    token_item = get_token(db, token)
    if token_item is None:
        raise Exception()
    
    db_user = models.DatabaseUser(email=token_item.email, scope=':'.join(token_item.permissions), username=username, password_hash=password_hash)
    
    db.query(models.DatabaseUser).filter(models.DatabaseUser.email == db_user.email).delete()

    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return models.User.from_database_user(db_user)


def create_token(db: Session, token: models.SignupToken):
    db_signup = models.DatabaseSignupToken(email=token.email, scope=':'.join(token.permissions), token=token.token)
    db.query(models.DatabaseSignupToken).filter(models.DatabaseSignupToken.email == token.email).delete()
    db.add(db_signup)
    db.commit()
    db.refresh(db_signup)
    return models.SignupToken.from_database_token(db_signup)
