import json
from pathlib import Path
from typing import Any

_PRESETS_PATH = Path(__file__).resolve().parent.parent / "data" / "presets.json"
_PRESETS: list[dict[str, Any]] = json.loads(_PRESETS_PATH.read_text(encoding="utf-8"))

def list_presets() -> list[dict[str, Any]]:
    return _PRESETS
