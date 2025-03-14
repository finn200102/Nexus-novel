# routers/auth.py
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from config.database import get_db
import bcrypt
from ..schemas.user import UserCreate, User as UserSchema, LoginResponse, UserLogin
from app.services.user_services import create_user, get_user_by_username

router = APIRouter(
    prefix="/auth",
    tags=["authentication"],
    responses={404: {"description": "Not found"}},
)

@router.post("/signup", response_model=UserSchema, status_code=status.HTTP_201_CREATED)
def signup(user: UserCreate, db: Session = Depends(get_db)):
    if get_user_by_username(db, user.username).first():
        raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already registered"
            )

    # Hash the password
    hashed_password = bcrypt.hashpw(user.password.encode('utf-8'), bcrypt.gensalt())
    
    # Debug information
    print(f"Original password: {user.password}")
    print(f"Hashed password type: {type(hashed_password)}")
    print(f"Hashed password: {hashed_password}")

    # Convert bytes to string for storage
    hashed_password_str = hashed_password.decode('utf-8')
    
    result = create_user(db, user_data={"username": user.username, "password": hashed_password_str})
    print(result)
    
    return result


@router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
def login(user_data: UserLogin, db: Session = Depends(get_db)):
    # Find the user by username
    user = get_user_by_username(db, user_data.username).first()

    # Check if user exists
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )

    try:
        # Verify password - handle different password formats
        password_bytes = user_data.password.encode('utf-8')
        stored_password = user.password
        
        # Debug information
        print(f"Input password: {user_data.password}")
        print(f"Stored password type: {type(stored_password)}")
        print(f"Stored password: {stored_password}")
        
        # Check if the stored password is a hex string representation of bytes
        if stored_password.startswith('\\x'):
            # This is likely a hex representation from PostgreSQL
            print("Detected hex string format, attempting to convert")
            try:
                # Try to create a new user with the correct password format
                raise ValueError("Password stored in incompatible format")
            except Exception as e:
                print(f"Error converting hex password: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid username or password"
                )
        else:
            # Normal bcrypt string format
            password_valid = bcrypt.checkpw(password_bytes, stored_password.encode('utf-8'))
            
            if not password_valid:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid username or password"
                )
    except ValueError as e:
        # If we get a ValueError (invalid salt), the password is definitely wrong
        # or stored in an incompatible format
        print(f"ValueError during password check: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )

    # Return user data with response model
    return {
        "id": user.id,
        "username": user.username,
        "message": "Login successful"
    }

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
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    hashed_password_str = hashed_password.decode('utf-8')
    
    user = create_user(db, user_data={"username": "testuser2", "password": hashed_password_str})
    
    return {"message": "Test user created", "username": "testuser2", "password": "testpassword"}



    
    
