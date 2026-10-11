import importlib


def test_packages_import() -> None:
    for name in ("app", "app.api", "app.services", "app.engine", "app.models"):
        importlib.import_module(name)
