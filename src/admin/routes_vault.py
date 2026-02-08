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
    """Lock the vault (encrypt .env)."""
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
