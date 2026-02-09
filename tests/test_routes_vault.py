"""
Tests for admin vault API routes.

Tests the /api/vault/* endpoints (status, lock, unlock, quick-lock,
config, register-passphrase, export, import).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("flask")


# ── Status ───────────────────────────────────────────────────────────


class TestVaultStatus:

    def test_status(self, client):
        with patch("src.admin.vault.vault_status") as mock:
            mock.return_value = {"locked": False, "has_vault": False}
            resp = client.get("/api/vault/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "locked" in data


# ── Lock ─────────────────────────────────────────────────────────────


class TestVaultLock:

    def test_lock_no_passphrase(self, client):
        resp = client.post("/api/vault/lock", json={})
        assert resp.status_code == 400
        assert "passphrase" in resp.get_json()["error"].lower()

    def test_lock_success(self, client):
        with patch("src.admin.vault.lock_vault") as mock:
            mock.return_value = {"success": True, "locked": True}
            resp = client.post("/api/vault/lock", json={"passphrase": "test123"})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_lock_value_error(self, client):
        with patch("src.admin.vault.lock_vault", side_effect=ValueError("bad pass")):
            resp = client.post("/api/vault/lock", json={"passphrase": "x"})
        assert resp.status_code == 400

    def test_lock_generic_error(self, client):
        with patch("src.admin.vault.lock_vault", side_effect=RuntimeError("boom")):
            resp = client.post("/api/vault/lock", json={"passphrase": "x"})
        assert resp.status_code == 500


# ── Quick Lock ───────────────────────────────────────────────────────


class TestVaultQuickLock:

    def test_quick_lock_success(self, client):
        with patch("src.admin.vault.auto_lock") as mock:
            mock.return_value = {"success": True, "locked": True}
            resp = client.post("/api/vault/quick-lock")
        assert resp.status_code == 200

    def test_quick_lock_no_passphrase(self, client):
        with patch("src.admin.vault.auto_lock") as mock:
            mock.return_value = {"success": False, "message": "No passphrase stored"}
            resp = client.post("/api/vault/quick-lock")
        assert resp.status_code == 400

    def test_quick_lock_error(self, client):
        with patch("src.admin.vault.auto_lock", side_effect=RuntimeError("boom")):
            resp = client.post("/api/vault/quick-lock")
        assert resp.status_code == 500


# ── Unlock ───────────────────────────────────────────────────────────


class TestVaultUnlock:

    def test_unlock_no_passphrase(self, client):
        resp = client.post("/api/vault/unlock", json={})
        assert resp.status_code == 400

    def test_unlock_success(self, client):
        with patch("src.admin.vault.unlock_vault") as mock:
            mock.return_value = {"success": True, "locked": False}
            resp = client.post("/api/vault/unlock", json={"passphrase": "test123"})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_unlock_wrong_passphrase(self, client):
        with patch("src.admin.vault.unlock_vault", side_effect=ValueError("wrong passphrase")):
            resp = client.post("/api/vault/unlock", json={"passphrase": "wrong"})
        assert resp.status_code == 400


# ── Config ───────────────────────────────────────────────────────────


class TestVaultConfig:

    def test_config_no_body(self, client):
        resp = client.post("/api/vault/config",
                           content_type="application/json", data="")
        assert resp.status_code == 400

    def test_set_auto_lock_minutes(self, client):
        with patch("src.admin.vault.set_auto_lock_minutes") as mock:
            resp = client.post("/api/vault/config", json={"auto_lock_minutes": 15})
        assert resp.status_code == 200
        assert resp.get_json()["auto_lock_minutes"] == 15
        mock.assert_called_once_with(15)

    def test_invalid_auto_lock_minutes(self, client):
        resp = client.post("/api/vault/config", json={"auto_lock_minutes": "abc"})
        assert resp.status_code == 400

    def test_no_config_to_update(self, client):
        resp = client.post("/api/vault/config", json={"other_field": True})
        assert resp.status_code == 400


# ── Register Passphrase ──────────────────────────────────────────────


class TestVaultRegisterPassphrase:

    def test_register_no_passphrase(self, client):
        resp = client.post("/api/vault/register-passphrase", json={})
        assert resp.status_code == 400

    def test_register_success(self, client):
        with patch("src.admin.vault.register_passphrase") as mock:
            mock.return_value = {"success": True, "message": "Passphrase registered"}
            resp = client.post("/api/vault/register-passphrase",
                               json={"passphrase": "mypass"})
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_register_value_error(self, client):
        with patch("src.admin.vault.register_passphrase",
                    side_effect=ValueError("Too short")):
            resp = client.post("/api/vault/register-passphrase",
                               json={"passphrase": "x"})
        assert resp.status_code == 400


# ── Export ────────────────────────────────────────────────────────────


class TestVaultExport:

    def test_export_no_password(self, client):
        resp = client.post("/api/vault/export", json={})
        assert resp.status_code == 400

    def test_export_success(self, client):
        envelope = {"encrypted": True, "data": "..."}
        with patch("src.admin.vault.export_vault_file", return_value=envelope):
            resp = client.post("/api/vault/export", json={"password": "pass123"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["vault"]["encrypted"] is True

    def test_export_no_env(self, client):
        with patch("src.admin.vault.export_vault_file",
                    side_effect=ValueError("No .env file found")):
            resp = client.post("/api/vault/export", json={"password": "pass"})
        assert resp.status_code == 400


# ── Import ───────────────────────────────────────────────────────────


class TestVaultImport:

    def test_import_no_body(self, client):
        resp = client.post("/api/vault/import",
                           content_type="application/json", data="")
        assert resp.status_code == 400

    def test_import_no_vault_data(self, client):
        resp = client.post("/api/vault/import", json={"password": "pass"})
        assert resp.status_code == 400

    def test_import_no_password(self, client):
        resp = client.post("/api/vault/import", json={"vault": {"data": "..."}})
        assert resp.status_code == 400

    def test_import_success(self, client):
        result = {"success": True, "key_count": 5, "changes": []}
        with patch("src.admin.vault.import_vault_file", return_value=result):
            resp = client.post("/api/vault/import", json={
                "vault": {"encrypted": True, "data": "..."},
                "password": "pass123",
            })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["key_count"] == 5

    def test_import_dry_run(self, client):
        result = {"success": True, "key_count": 3, "changes": ["A", "B", "C"]}
        with patch("src.admin.vault.import_vault_file", return_value=result) as mock:
            resp = client.post("/api/vault/import", json={
                "vault": {"data": "..."},
                "password": "pass",
                "dry_run": True,
            })
        _, kwargs = mock.call_args
        assert kwargs["dry_run"] is True

    def test_import_wrong_password(self, client):
        with patch("src.admin.vault.import_vault_file",
                    side_effect=ValueError("Wrong password")):
            resp = client.post("/api/vault/import", json={
                "vault": {"data": "..."},
                "password": "wrong",
            })
        assert resp.status_code == 400
