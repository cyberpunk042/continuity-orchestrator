"""
Receipt Model — Adapter execution results.

Every adapter call produces a receipt, regardless of success or failure.
Receipts are stored in the audit ledger and state for idempotency.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


class ErrorDetails(BaseModel):
    """Details about an execution error."""

    code: str
    message: str
    retryable: bool = False
    retry_in_seconds: Optional[int] = None


class Receipt(BaseModel):
    """
    Result of an adapter execution.

    Every adapter call produces a receipt.
    """

    status: Literal["ok", "skipped", "failed"]
    adapter: str
    action_id: str
    channel: str
    delivery_id: Optional[str] = None
    ts_iso: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    details: Optional[Dict[str, Any]] = None
    error: Optional[ErrorDetails] = None

    @classmethod
    def ok(
        cls,
        adapter: str,
        action_id: str,
        channel: str,
        delivery_id: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> "Receipt":
        """Create a successful receipt."""
        return cls(
            status="ok",
            adapter=adapter,
            action_id=action_id,
            channel=channel,
            delivery_id=delivery_id,
            details=details,
        )

    @classmethod
    def skipped(
        cls,
        adapter: str,
        action_id: str,
        channel: str,
        reason: str,
    ) -> "Receipt":
        """Create a skipped receipt."""
        return cls(
            status="skipped",
            adapter=adapter,
            action_id=action_id,
            channel=channel,
            details={"skip_reason": reason},
        )

    @classmethod
    def failed(
        cls,
        adapter: str,
        action_id: str,
        channel: str,
        error_code: str,
        error_message: str,
        retryable: bool = False,
        retry_in_seconds: Optional[int] = None,
    ) -> "Receipt":
        """Create a failed receipt."""
        return cls(
            status="failed",
            adapter=adapter,
            action_id=action_id,
            channel=channel,
            error=ErrorDetails(
                code=error_code,
                message=error_message,
                retryable=retryable,
                retry_in_seconds=retry_in_seconds,
            ),
        )
