from app.config import Settings


def test_cors_origins_strips_whitespace_and_drops_empties() -> None:
    settings = Settings(mongodb_uri="mongodb://localhost:27017", cors_allowed_origins="a, b ,,c")
    assert settings.cors_origins == ["a", "b", "c"]


def test_cors_origins_empty_string_is_empty_list() -> None:
    settings = Settings(mongodb_uri="mongodb://localhost:27017", cors_allowed_origins="")
    assert settings.cors_origins == []
