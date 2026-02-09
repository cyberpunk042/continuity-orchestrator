"""
Shared fixtures for admin route tests.

Provides a Flask test app with a temporary project root and pre-created
directory structure so admin routes can operate without hitting the real
filesystem.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("flask")


@pytest.fixture
def app(tmp_path: Path):
    """Create a Flask test app with temp project root."""
    from src.admin.server import create_app

    app = create_app()
    app.config["PROJECT_ROOT"] = tmp_path
    app.config["TESTING"] = True

    # Create the standard directory structure
    (tmp_path / "state").mkdir()
    (tmp_path / "audit").mkdir()
    (tmp_path / "policy" / "plans").mkdir(parents=True)
    (tmp_path / "content" / "articles").mkdir(parents=True)
    (tmp_path / "content" / "media").mkdir(parents=True)
    (tmp_path / "templates").mkdir()
    (tmp_path / "backups").mkdir()

    return app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def state_file(app):
    """Path to state/current.json inside the temp project."""
    return app.config["PROJECT_ROOT"] / "state" / "current.json"


@pytest.fixture
def env_file(app):
    """Path to .env inside the temp project."""
    return app.config["PROJECT_ROOT"] / ".env"


@pytest.fixture
def backups_dir(app):
    """Path to backups/ inside the temp project."""
    return app.config["PROJECT_ROOT"] / "backups"


@pytest.fixture
def articles_dir(app):
    """Path to content/articles/ inside the temp project."""
    return app.config["PROJECT_ROOT"] / "content" / "articles"


@pytest.fixture
def policy_dir(app):
    """Path to policy/ inside the temp project."""
    return app.config["PROJECT_ROOT"] / "policy"


@pytest.fixture
def minimal_state():
    """Minimal valid state JSON."""
    return {
        "meta": {
            "schema_version": 1,
            "project": "test-project",
            "state_id": "S-TEST-001",
            "updated_at_iso": "2026-02-09T00:00:00Z",
            "policy_version": 1,
            "plan_id": "default",
        },
        "timer": {
            "mode": "renewable_countdown",
            "armed": True,
            "deadline_iso": "2026-12-31T00:00:00Z",
            "grace_minutes": 0,
        },
        "escalation": {
            "state": "OK",
        },
        "actions": {
            "executed": [],
        },
        "integrations": {
            "enabled_adapters": {},
            "routing": {},
        },
    }


def write_state(state_file: Path, state: dict) -> None:
    """Helper to write a state JSON file."""
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
