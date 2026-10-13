import math
import time

import pytest

from app.errors import AppError
from app.services.regions import cell_center, cell_id, cells_in_box


@pytest.mark.parametrize(
    ("lat", "lon", "expected"),
    [
        (28.6139, 77.2090, "28.50_77.25"),
        (-33.87, 151.21, "-33.75_151.25"),
        (0.125, 0.125, "0.25_0.25"),
        (-0.125, -0.125, "0.00_0.00"),
        (90, 180, "90.00_180.00"),
    ],
)
def test_cell_id_snaps_to_canonical_id(lat: float, lon: float, expected: str) -> None:
    assert cell_id(lat, lon) == expected


@pytest.mark.parametrize(
    ("lat", "lon"),
    [
        (math.nan, 0.0),
        (0.0, math.inf),
        (90.0001, 0.0),
        (0.0, -180.0001),
        (-90.0001, 0.0),
        (0.0, 180.0001),
    ],
)
def test_cell_id_rejects_invalid_coordinates(lat: float, lon: float) -> None:
    with pytest.raises(AppError) as excinfo:
        cell_id(lat, lon)
    assert excinfo.value.code == "invalid_region"


def test_cells_in_box_returns_all_cells_in_ascending_order() -> None:
    cells = cells_in_box(28.4, 77.0, 28.8, 77.4)
    assert len(cells) == 6
    assert cells == [
        "28.50_77.00",
        "28.50_77.25",
        "28.50_77.50",
        "28.75_77.00",
        "28.75_77.25",
        "28.75_77.50",
    ]


def test_cells_in_box_cap_boundary_is_allowed() -> None:
    cells = cells_in_box(10, 70, 10.5, 70.5)
    assert len(cells) == 9
    assert cells[0] == "10.00_70.00"
    assert cells[-1] == "10.50_70.50"


def test_cells_in_box_exceeding_cap_raises() -> None:
    with pytest.raises(AppError):
        cells_in_box(10, 70, 10.75, 70.5)


@pytest.mark.parametrize(
    ("south", "west", "north", "east"),
    [
        (29.0, 77.0, 28.0, 77.0),
        (28.0, 78.0, 28.0, 77.0),
        (math.nan, 0.0, 1.0, 1.0),
    ],
)
def test_cells_in_box_rejects_inverted_or_invalid_box(
    south: float, west: float, north: float, east: float
) -> None:
    with pytest.raises(AppError):
        cells_in_box(south, west, north, east)


def test_cells_in_box_world_bbox_rejected_instantly() -> None:
    start = time.perf_counter()
    with pytest.raises(AppError):
        cells_in_box(-90, -180, 90, 180)
    assert time.perf_counter() - start < 0.1


def test_cell_center_round_trips_to_snapped_coordinates() -> None:
    assert cell_center("28.50_77.25") == (28.5, 77.25)
    assert cell_id(*cell_center(cell_id(28.6139, 77.2090))) == "28.50_77.25"
    assert cell_id(*cell_center(cell_id(-0.125, -0.125))) == "0.00_0.00"


@pytest.mark.parametrize(
    "value",
    ["abc", "28.50", "999.00_0.00", "28.50_77.25_1", "x_y"],
)
def test_cell_center_rejects_invalid_ids(value: str) -> None:
    with pytest.raises(AppError):
        cell_center(value)
