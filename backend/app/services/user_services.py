from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models.user import User

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
    Returns Users whose username matches, ignoring case (usernames are unique
    case-insensitively)
    """

    users = db.query(User).filter(func.lower(User.username) == func.lower(username))
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
