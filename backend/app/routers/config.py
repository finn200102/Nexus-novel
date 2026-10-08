from fastapi import APIRouter

router = APIRouter(
    prefix="/config",
    tags=["configs"],
    responses={404: {"description": "Not found"}},
)


