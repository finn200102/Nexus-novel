from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from config.database import get_db
from app.auth.dependencies import get_current_user

router = APIRouter(
    prefix="/config",
    tags=["configs"],
    responses={404: {"description": "Not found"}},
)


