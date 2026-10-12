import math

GRID_STEP = 0.25
MAX_CELLS = 9

class RegionError(ValueError):
    pass

def _validate(lat: float, lon: float) -> None:
    if not math.isfinite(lat) or not math.isfinite(lon):
        raise RegionError("Coordinates must be finite numbers.")
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise RegionError("Latitude must be between -90 and 90 and longitude between -180 and 180.")

def _snap_index(value: float) -> int:
    return math.floor(value / GRID_STEP + 0.5)

def _snap(value: float) -> float:
    snapped = _snap_index(value) * GRID_STEP
    return 0.0 if snapped == 0.0 else snapped

def cell_id(lat: float, lon: float) -> str:
    _validate(lat, lon)
    return f"{_snap(lat):.2f}_{_snap(lon):.2f}"

def cell_center(cell_id: str) -> tuple[float, float]:
    try:
        lat, lon = (float(part) for part in cell_id.split("_"))
    except ValueError:
        raise RegionError("Invalid cell id.") from None
    _validate(lat, lon)
    return lat, lon

def cells_in_box(south: float, west: float, north: float, east: float) -> list[str]:
    _validate(south, west)
    _validate(north, east)
    if south > north:
        raise RegionError("south must not be greater than north.")
    if west > east:
        raise RegionError("west must not be greater than east.")
    south_idx = _snap_index(south)
    north_idx = _snap_index(north)
    west_idx = _snap_index(west)
    east_idx = _snap_index(east)
    if (north_idx - south_idx + 1) * (east_idx - west_idx + 1) > MAX_CELLS:
        raise RegionError(f"A region is limited to {MAX_CELLS} grid cells.")
    return [
        cell_id(lat_idx * GRID_STEP, lon_idx * GRID_STEP)
        for lat_idx in range(south_idx, north_idx + 1)
        for lon_idx in range(west_idx, east_idx + 1)
    ]