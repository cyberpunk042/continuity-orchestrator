"""
Vault API routes — lock/unlock the .env file.
"""

from flask import Blueprint, jsonify, request

vault_bp = Blueprint("vault", __name__)


@vault_bp.route("/vault/status", methods=["GET"])
def api_vault_status():
    """Check if the vault is locked or unlocked."""
    from .vault import vault_status
    return jsonify(vault_status())


@vault_bp.route("/vault/lock", methods=["POST"])
def api_vault_lock():
    """Lock the vault (encrypt .env) with a new passphrase."""
    from .vault import lock_vault

    body = request.get_json()
    if not body or not body.get("passphrase"):
        return jsonify({"error": "Passphrase is required"}), 400

    try:
        result = lock_vault(body["passphrase"])
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Lock failed: {e}"}), 500


@vault_bp.route("/vault/quick-lock", methods=["POST"])
def api_vault_quick_lock():
    """Lock the vault using the passphrase stored from last unlock.

    No passphrase input needed — re-uses the one in memory.
    Returns 400 if no passphrase is stored (first lock must use /vault/lock).
    """
    from .vault import auto_lock

    try:
        result = auto_lock()
        if result.get("success"):
            return jsonify(result)
        else:
            return jsonify({"error": result.get("message", "Quick-lock failed")}), 400
    except Exception as e:
        return jsonify({"error": f"Lock failed: {e}"}), 500


@vault_bp.route("/vault/unlock", methods=["POST"])
def api_vault_unlock():
    """Unlock the vault (decrypt .env.vault back to .env)."""
    from .vault import unlock_vault

    body = request.get_json()
    if not body or not body.get("passphrase"):
        return jsonify({"error": "Passphrase is required"}), 400

    try:
        result = unlock_vault(body["passphrase"])
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Unlock failed: {e}"}), 500


@vault_bp.route("/vault/config", methods=["POST"])
def api_vault_config():
    """Update vault configuration (auto-lock timeout)."""
    from .vault import set_auto_lock_minutes

    body = request.get_json()
    if not body:
        return jsonify({"error": "No JSON body"}), 400

    if "auto_lock_minutes" in body:
        try:
            minutes = int(body["auto_lock_minutes"])
            set_auto_lock_minutes(minutes)
            return jsonify({"success": True, "auto_lock_minutes": minutes})
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid value for auto_lock_minutes"}), 400

    return jsonify({"error": "No config to update"}), 400


@vault_bp.route("/vault/export", methods=["POST"])
def api_vault_export():
    """Export .env as an encrypted vault file.

    Accepts: {"password": "..."}
    Returns: vault envelope JSON (downloadable).
    """
    from .vault import export_vault_file

    body = request.get_json()
    if not body or not body.get("password"):
        return jsonify({"error": "Password is required"}), 400

    try:
        envelope = export_vault_file(body["password"])
        return jsonify({"success": True, "vault": envelope})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Export failed: {e}"}), 500


@vault_bp.route("/vault/import", methods=["POST"])
def api_vault_import():
    """Import an encrypted vault file to restore .env.

    Accepts: {"vault": {...envelope...}, "password": "...", "dry_run": false}
    Returns: {"success": true, "changes": [...], "key_count": N}
    """
    from .vault import import_vault_file

    body = request.get_json()
    if not body:
        return jsonify({"error": "No JSON body"}), 400
    if not body.get("vault"):
        return jsonify({"error": "Vault data is required"}), 400
    if not body.get("password"):
        return jsonify({"error": "Password is required"}), 400

    try:
        result = import_vault_file(
            body["vault"],
            body["password"],
            dry_run=body.get("dry_run", False),
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Import failed: {e}"}), 500
