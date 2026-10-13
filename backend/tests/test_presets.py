from typing import Any

from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import AnalysisRequest
from app.services.presets import list_presets
from app.services.regions import cells_in_box

PRESETS = list_presets()
START_YEAR = 1990
END_YEAR = 2020
REGION_KEYS = ("lat", "lon", "south", "west", "north", "east")


def _request(preset: dict[str, Any]) -> AnalysisRequest:
    region = {key: preset[key] for key in REGION_KEYS if key in preset}
    return AnalysisRequest(start_year=START_YEAR, end_year=END_YEAR, **region)


def test_every_preset_is_a_valid_point_or_box() -> None:
    for preset in PRESETS:
        assert _request(preset).cell_ids


def test_every_box_resolves_to_at_most_nine_cells() -> None:
    for preset in PRESETS:
        if "south" in preset:
            cells = cells_in_box(preset["south"], preset["west"], preset["north"], preset["east"])
            assert 1 <= len(cells) <= 9


def test_preset_ids_are_unique() -> None:
    ids = [preset["id"] for preset in PRESETS]
    assert len(ids) == len(set(ids))


def test_all_indian_states_and_union_territories_are_present() -> None:
    indian_states = [p for p in PRESETS if p["kind"] == "state" and p["country"] == "India"]
    assert len(indian_states) == 36


def test_regions_endpoint_returns_the_same_list() -> None:
    response = TestClient(app).get("/api/regions")
    assert response.status_code == 200
    assert response.json() == PRESETS
