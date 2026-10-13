from typing import Literal
from fastapi import APIRouter
from pydantic import BaseModel
from app.services.presets import list_presets

router = APIRouter(prefix="/api")

class PresetOut(BaseModel):
    id: str
    name: str
    kind: Literal["city", "state", "global"]
    country: str
    lat: float | None = None
    lon: float | None = None
    south: float | None = None
    west: float | None = None
    north: float | None = None
    east: float | None = None

@router.get("/regions", response_model=list[PresetOut], response_model_exclude_none=True)
def regions() -> list[PresetOut]:
    return [PresetOut(**preset) for preset in list_presets()]
