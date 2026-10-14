"""Shared test setup: every test gets its own fresh, empty database."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(str(tmp_path / "test.db"))
    yield connection
    connection.close()


@pytest.fixture
def issue(conn):
    prop = db.get_or_create_property(conn)
    return db.create_issue(conn, prop["id"], "Kitchen sink leaking", "kitchen", "water")
