"""
Sentinel Notifier — Push state / signals to the Cloudflare Sentinel Worker.

All calls are fire-and-forget with a short timeout.  If the sentinel is
unreachable or not configured, the engine continues normally.  The Worker's
own cron cadence ensures it eventually catches up.

Environment variables:
    SENTINEL_URL   — Base URL of the Worker (e.g. https://my-sentinel.workers.dev)
    SENTINEL_TOKEN — Bearer token for authenticating POST requests
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..engine.tick import TickResult
    from ..models.state import State

logger = logging.getLogger(__name__)

# Timeout for sentinel HTTP calls (seconds)
_TIMEOUT = 3


def _get_sentinel_config() -> tuple[str, str] | None:
    """Return (url, token) or None if sentinel is not configured."""
    url = os.environ.get("SENTINEL_URL", "").rstrip("/")
    token = os.environ.get("SENTINEL_TOKEN", "")
    if not url or not token:
        return None
    return url, token


def notify_sentinel(state: "State", tick_result: Optional["TickResult"] = None) -> bool:
    """Push the current state snapshot to the sentinel Worker.

    Called after every tick, reset, or state-changing operation.

    Args:
        state: Current State object (after persistence).
        tick_result: Optional TickResult for state_changed info.

    Returns:
        True if the sentinel was notified successfully, False otherwise.
    """
    cfg = _get_sentinel_config()
    if cfg is None:
        return False

    url, token = cfg

    payload = {
        "lastTickAt":      state.meta.updated_at_iso,
        "deadline":        state.timer.deadline_iso,
        "stage":           state.escalation.state,
        "stageEnteredAt":  state.escalation.state_entered_at_iso,
        "renewedThisTick": state.renewal.renewed_this_tick,
        "lastRenewalAt":   state.renewal.last_renewal_iso or "",
        "stateChanged":    tick_result.state_changed if tick_result else False,
        "version":         int(time.time()),
    }

    try:
        import httpx

        resp = httpx.post(
            f"{url}/state",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            logger.info("Sentinel notified: stage=%s", state.escalation.state)
            return True
        else:
            logger.warning("Sentinel returned %d: %s", resp.status_code, resp.text[:200])
            return False

    except Exception as exc:
        logger.debug("Sentinel notify failed (non-critical): %s", exc)
        return False


def signal_sentinel(signal_type: str = "renewal") -> bool:
    """Send a signal to the sentinel (renewal, release, urgent).

    Called when the user renews, triggers release, or other urgent actions.
    The sentinel will dispatch a workflow immediately on the next cron cycle.

    Args:
        signal_type: One of "renewal", "release", "urgent".

    Returns:
        True if the signal was sent successfully, False otherwise.
    """
    cfg = _get_sentinel_config()
    if cfg is None:
        return False

    url, token = cfg

    payload = {
        "type": signal_type,
        "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "nonce": secrets.token_hex(8),
    }

    try:
        import httpx

        resp = httpx.post(
            f"{url}/signal",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            logger.info("Sentinel signaled: type=%s", signal_type)
            return True
        else:
            logger.warning("Sentinel signal returned %d: %s", resp.status_code, resp.text[:200])
            return False

    except Exception as exc:
        logger.debug("Sentinel signal failed (non-critical): %s", exc)
        return False
