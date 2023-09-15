from sqlalchemy.orm import Session
from . import models


def get_user(db: Session, user_id: str) -> models.User:
    return models.User.from_database_user(db.query(models.DatabaseUser).filter(models.DatabaseUser.username == user_id).first())


def get_user_by_email(db: Session, email: str) -> models.User:
    return models.User.from_database_user(db.query(models.DatabaseUser).filter(models.DatabaseUser.email == email).first())


def get_users(db: Session, skip: int = 0, limit: int = 100) -> list[models.User]:
    return [models.User.from_database_user(user) for user in db.query(models.DatabaseUser).offset(skip).limit(limit).all()]


def create_user(db: Session, user: models.User):
    db_user = models.DatabaseUser(email=user.email, password_hash=user.password_hash, username=user.username, scope=':'.join(user.permissions))
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user
