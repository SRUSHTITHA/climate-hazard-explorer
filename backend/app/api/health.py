from typing import Annotated
from fastapi import APIRouter, Depends
from pymongo.database import Database
from app.db import get_db

router = APIRouter()
@router.get("/health")
def health(db: Annotated[Database, Depends(get_db)]) -> dict[str, str]:
    try:
        db.command("ping")
        database = "up"
    except Exception:
        database = "down"
    return {"status": "ok", "database": database}
