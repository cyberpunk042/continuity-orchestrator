"""
Tests for admin core API routes.

Tests the /api/* core endpoints (status, run, renew, set-deadline, reset,
trigger, scaffold, policy constants) using Flask test client.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("flask")


# ── Status ───────────────────────────────────────────────────────────


class TestApiStatus:

    def test_status_returns_json(self, client, state_file, minimal_state):
        from tests.conftest import write_state
        write_state(state_file, minimal_state)

        with patch("src.config.system_status.get_system_status") as mock:
            mock.return_value = MagicMock(to_dict=lambda: {"state": "OK", "project": "test"})
            resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["state"] == "OK"


# ── Run ──────────────────────────────────────────────────────────────


class TestApiRun:

    def test_unknown_command_400(self, client):
        resp = client.post("/api/run", json={"command": "rm -rf /"})
        assert resp.status_code == 400
        assert "Unknown command" in resp.get_json()["error"]

    def test_valid_command_runs(self, client):
        mock_result = MagicMock(
            returncode=0,
            stdout="OK output",
            stderr="",
        )
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/run", json={"command": "status"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["output"] == "OK output"
        # Verify the correct command was called
        args = mock_run.call_args[0][0]
        assert args == ["python", "-m", "src.main", "status"]

    def test_timeout_returns_504(self, client):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 60)):
            resp = client.post("/api/run", json={"command": "tick"})
        assert resp.status_code == 504
        assert "timed out" in resp.get_json()["error"].lower()

    def test_exception_returns_500(self, client):
        with patch("subprocess.run", side_effect=OSError("spawn failed")):
            resp = client.post("/api/run", json={"command": "status"})
        assert resp.status_code == 500

    def test_all_allowed_commands_accepted(self, client):
        """Verify no allowed command gets rejected as unknown."""
        import subprocess
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        allowed = [
            "status", "tick", "tick-dry", "build-site", "check-config",
            "test-all", "health", "config-status", "explain", "simulate",
            "retry-queue", "circuit-breakers", "circuit-breakers --reset",
            "test email", "test sms", "reset",
            "trigger-release-full",
            "trigger-shadow-0", "trigger-shadow-30",
            "trigger-shadow-60", "trigger-shadow-120",
            "deploy-site", "trigger-cron",
        ]
        with patch("subprocess.run", return_value=mock_result):
            for cmd in allowed:
                resp = client.post("/api/run", json={"command": cmd})
                assert resp.status_code == 200, f"Command {cmd!r} should be allowed"


# ── Test Email / SMS ─────────────────────────────────────────────────


class TestApiTestEmail:

    def test_basic_email(self, client):
        mock_result = MagicMock(returncode=0, stdout="sent", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/test/email", json={})
        assert resp.status_code == 200
        args = mock_run.call_args[0][0]
        assert args == ["python", "-m", "src.main", "test", "email"]

    def test_email_with_options(self, client):
        mock_result = MagicMock(returncode=0, stdout="sent", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/test/email", json={
                "to": "user@example.com",
                "subject": "Test",
                "body": "Hello",
            })
        args = mock_run.call_args[0][0]
        assert "--to" in args
        assert "user@example.com" in args
        assert "--subject" in args
        assert "--body" in args

    def test_email_timeout(self, client):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 30)):
            resp = client.post("/api/test/email", json={})
        assert resp.status_code == 504


class TestApiTestSms:

    def test_basic_sms(self, client):
        mock_result = MagicMock(returncode=0, stdout="sent", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/test/sms", json={})
        args = mock_run.call_args[0][0]
        assert args == ["python", "-m", "src.main", "test", "sms"]

    def test_sms_with_options(self, client):
        mock_result = MagicMock(returncode=0, stdout="sent", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/test/sms", json={
                "to": "+15551234567",
                "message": "Test message",
            })
        args = mock_run.call_args[0][0]
        assert "--to" in args
        assert "--message" in args


# ── Renew ────────────────────────────────────────────────────────────


class TestApiRenew:

    def test_renew_default_hours(self, client):
        mock_result = MagicMock(returncode=0, stdout="Renewed", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/renew", json={})
        assert resp.status_code == 200
        args = mock_run.call_args[0][0]
        assert "--hours" in args
        assert "48" in args  # default

    def test_renew_custom_hours(self, client):
        mock_result = MagicMock(returncode=0, stdout="Renewed", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/renew", json={"hours": 72})
        args = mock_run.call_args[0][0]
        assert "72" in args


# ── Set Deadline ─────────────────────────────────────────────────────


class TestApiSetDeadline:

    def test_missing_hours_400(self, client):
        resp = client.post("/api/state/set-deadline", json={})
        assert resp.status_code == 400
        assert "hours" in resp.get_json()["error"].lower()

    def test_set_deadline(self, client):
        mock_result = MagicMock(returncode=0, stdout="Deadline set", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/state/set-deadline", json={"hours": 24})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        args = mock_run.call_args[0][0]
        assert "24" in args


# ── State Reset ──────────────────────────────────────────────────────


class TestApiStateReset:

    def test_reset(self, client):
        mock_result = MagicMock(returncode=0, stdout="Reset", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            resp = client.post("/api/state/reset", json={})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True


# ── Factory Reset ────────────────────────────────────────────────────


class TestApiFactoryReset:

    def test_factory_reset_default(self, client):
        mock_result = MagicMock(returncode=0, stdout="Factory reset", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/state/factory-reset", json={})
        assert resp.status_code == 200
        args = mock_run.call_args[0][0]
        assert "--full" in args
        assert "-y" in args
        assert "--backup" in args  # default is True

    def test_factory_reset_no_backup(self, client):
        mock_result = MagicMock(returncode=0, stdout="Done", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/state/factory-reset", json={"backup": False})
        args = mock_run.call_args[0][0]
        assert "--no-backup" in args

    def test_factory_reset_with_options(self, client):
        mock_result = MagicMock(returncode=0, stdout="Done", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/state/factory-reset", json={
                "include_content": True,
                "purge_history": True,
                "decrypt_content": True,
                "scaffold": False,
            })
        args = mock_run.call_args[0][0]
        assert "--include-content" in args
        assert "--purge-history" in args
        assert "--decrypt-content" in args
        assert "--no-scaffold" in args


# ── Trigger ──────────────────────────────────────────────────────────


class TestApiStateTrigger:

    def test_invalid_stage_400(self, client):
        resp = client.post("/api/state/trigger", json={"stage": "INVALID"})
        assert resp.status_code == 400

    def test_valid_trigger(self, client):
        mock_result = MagicMock(returncode=0, stdout="Triggered", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/state/trigger", json={
                "stage": "FULL",
                "delay": 30,
                "silent": True,
            })
        assert resp.status_code == 200
        args = mock_run.call_args[0][0]
        assert "--stage" in args
        assert "FULL" in args
        assert "--delay" in args
        assert "30" in args
        assert "--silent" in args

    def test_trigger_timeout(self, client):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 60)):
            resp = client.post("/api/state/trigger", json={"stage": "FULL"})
        assert resp.status_code == 504


# ── Scaffold ─────────────────────────────────────────────────────────


class TestApiScaffold:

    def test_scaffold_default(self, client):
        with patch("src.content.scaffold.generate_scaffold") as mock:
            mock.return_value = {"created": ["about.json"], "skipped": []}
            resp = client.post("/api/content/scaffold", json={})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "about.json" in data["created"]

    def test_scaffold_with_overwrite(self, client):
        with patch("src.content.scaffold.generate_scaffold") as mock:
            mock.return_value = {"created": [], "skipped": []}
            resp = client.post("/api/content/scaffold", json={"overwrite": True})
        mock.assert_called_once()
        _, kwargs = mock.call_args
        assert kwargs["overwrite"] is True


# ── Policy Constants ─────────────────────────────────────────────────


class TestApiPolicyConstants:

    def test_read_constants(self, client):
        mock_result = MagicMock(
            returncode=0,
            stdout=json.dumps({"constants": {}, "rules": []}),
            stderr="",
        )
        with patch("subprocess.run", return_value=mock_result):
            resp = client.get("/api/policy/constants")
        assert resp.status_code == 200

    def test_read_constants_failure(self, client):
        mock_result = MagicMock(returncode=1, stdout="", stderr="fail")
        with patch("subprocess.run", return_value=mock_result):
            resp = client.get("/api/policy/constants")
        assert resp.status_code == 500

    def test_update_constants(self, client):
        mock_result = MagicMock(
            returncode=0,
            stdout=json.dumps({"constants": {"K": "1"}, "rules": []}),
            stderr="",
        )
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/policy/constants", json={
                "constants": {"DEADLINE_HOURS": "48"},
                "enable": ["R10"],
                "disable": ["R20"],
            })
        assert resp.status_code == 200
        args = mock_run.call_args[0][0]
        assert "--set" in args
        assert "--enable" in args
        assert "--disable" in args

    def test_update_preset(self, client):
        mock_result = MagicMock(
            returncode=0,
            stdout=json.dumps({"constants": {}}),
            stderr="",
        )
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            resp = client.post("/api/policy/constants", json={"preset": "demo"})
        args = mock_run.call_args[0][0]
        assert "--preset" in args
        assert "demo" in args
