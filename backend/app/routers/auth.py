# routers/auth.py
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from config.database import get_db
import bcrypt
from ..schemas.user import UserCreate, User as UserSchema, LoginResponse, UserLogin
from app.services.user_services import create_user, get_user_by_username
from app.models.user import User
from app.auth.dependencies import get_current_user

from datetime import timedelta
from app.auth.jwt import create_access_token

router = APIRouter(
    prefix="/auth",
    tags=["authentication"],
    responses={404: {"description": "Not found"}},
)


def _login_response(user: User) -> dict:
    access_token = create_access_token(
        data={"sub": str(user.id)}, expires_delta=timedelta(minutes=30)
    )
    return {
        "id": user.id,
        "username": user.username,
        "message": "Login successful",
        "access_token": access_token,
        "token_type": "bearer",
    }


@router.post("/signup", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
def signup(user: UserCreate, db: Session = Depends(get_db)):
    if get_user_by_username(db, user.username).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    # Hash the password
    hashed_password = bcrypt.hashpw(user.password.encode("utf-8"), bcrypt.gensalt())

    # Convert bytes to string for storage
    hashed_password_str = hashed_password.decode("utf-8")

    result = create_user(
        db, user_data={"username": user.username, "password": hashed_password_str}
    )
    return _login_response(result)


@router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
def login(user_data: UserLogin, db: Session = Depends(get_db)):
    # Find the user by username
    user = get_user_by_username(db, user_data.username).first()

    # Check if user exists
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    try:
        # Verify password - handle different password formats
        password_bytes = user_data.password.encode("utf-8")
        stored_password = user.password

        # Check if the stored password is a hex string representation of bytes
        if stored_password.startswith("\\x"):
            # This is likely a hex representation from PostgreSQL
            try:
                # Try to create a new user with the correct password format
                raise ValueError("Password stored in incompatible format")
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid username or password",
                )
        else:
            # Normal bcrypt string format
            password_valid = bcrypt.checkpw(
                password_bytes, stored_password.encode("utf-8")
            )

            if not password_valid:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid username or password",
                )
    except ValueError:
        # If we get a ValueError (invalid salt), the password is definitely wrong
        # or stored in an incompatible format
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    return _login_response(user)


@router.post("/test-user", status_code=status.HTTP_201_CREATED)
def create_test_user(db: Session = Depends(get_db)):
    # Check if test user exists
    if get_user_by_username(db, "testuser2").first():
        # Delete existing user
        user = get_user_by_username(db, "testuser2").first()
        db.delete(user)
        db.commit()

    # Create a new user with properly stored password
    password = "testpassword"
    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    hashed_password_str = hashed_password.decode("utf-8")

    user = create_user(
        db, user_data={"username": "testuser2", "password": hashed_password_str}
    )

    return {
        "message": "Test user created",
        "username": "testuser2",
        "password": "testpassword",
    }


@router.get("/verify-token", response_model=UserSchema)
def verify_token_endpoint(current_user: User = Depends(get_current_user)):
    """Endpoint to verify if the current token is valid"""
    return current_user
