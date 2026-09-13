"""Shared pytest fixtures: isolated SQLite DB + memory rate limiting."""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("REDIS_URL", "")


@pytest.fixture()
def client(tmp_path):
    db_file = tmp_path / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["REDIS_URL"] = ""

    from app import main as main_module
    from app.config import Settings, get_settings

    get_settings.cache_clear()
    settings = Settings(database_url=f"sqlite:///{db_file}", redis_url="")

    # Fresh engine per test module import state.
    main_module.init_state(settings)
    app = main_module.create_app(settings)
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()
