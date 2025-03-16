from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from app.models.novel import Novel
from app.models.author import Author
from app.models.library import Library
from app.models.user import User
from app.models.tag import Tag
from app.models.genre import Genre
from app.models.chapter import Chapter
from app.schemas.user import UserCreate

def create_user(db: Session, user_data: dict):
    # Remove the is_active default setting
    # if 'is_active' not in user_data:
    #     user_data['is_active'] = True
        
    user = User(**user_data)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_username(db: Session, username):
    """
    Returns Users that match that username
    """

    users = db.query(User).filter(User.username == username)
    return users

def get_user_by_id(db: Session, id):
    """
    Returns Users that match that id
    """

    users = db.query(User).filter(User.id == id).first()
    return users


def delete_user(db: Session, user_id):
    """
    Deletes a User from database
    """

    user = db.query(User).filter(User.id == user_id).first()
    if user:
        db.delete(user)
        db.commit()


def update_user(db: Session, user_id, user_data):
    """
    Update the User with User_data which can be complete new data or just part of it
    """
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        return None

    # Update User attributes
    for key, value in user_data.items():
        if hasattr(user, key):
            setattr(user, key, value)

    db.commit()
    db.refresh(user)
    return user
