"""
Retry Queue — Manages failed actions for automatic retry.

Failed actions are queued with exponential backoff and max retry limits.
The queue persists to disk and survives restarts.

## Usage

    from src.reliability.retry_queue import RetryQueue
    
    queue = RetryQueue()
    queue.enqueue(failed_action, receipt)
    
    # On next tick
    pending = queue.get_pending()
    for item in pending:
        # Retry...
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models.receipt import Receipt
from ..policy.models import ActionDefinition

logger = logging.getLogger(__name__)


@dataclass
class RetryItem:
    """An item in the retry queue."""
    
    action_id: str
    adapter: str
    channel: str
    template: Optional[str]
    
    # Retry state
    attempt_count: int = 0
    max_attempts: int = 3
    
    # Timing
    first_failed_at: str = ""
    last_failed_at: str = ""
    next_retry_at: str = ""
    
    # Error info
    last_error_code: str = ""
    last_error_message: str = ""
    
    # Original context
    tick_id: str = ""
    escalation_state: str = ""
    
    def should_retry(self) -> bool:
        """Check if this item should be retried."""
        if self.attempt_count >= self.max_attempts:
            return False
        
        now = datetime.now(timezone.utc)
        next_retry = datetime.fromisoformat(self.next_retry_at.replace("Z", "+00:00"))
        return now >= next_retry
    
    def calculate_next_retry(self) -> str:
        """Calculate next retry time with exponential backoff."""
        # Backoff: 1min, 5min, 15min, 30min, 60min
        backoff_minutes = [1, 5, 15, 30, 60]
        delay = backoff_minutes[min(self.attempt_count, len(backoff_minutes) - 1)]
        
        next_time = datetime.now(timezone.utc).timestamp() + (delay * 60)
        return datetime.fromtimestamp(next_time, timezone.utc).isoformat().replace("+00:00", "Z")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RetryItem":
        """Create from dictionary."""
        return cls(**data)


class RetryQueue:
    """
    Persistent retry queue for failed actions.
    
    Implements exponential backoff and max retry limits.
    Queue state persists to a JSON file.
    """
    
    DEFAULT_MAX_ATTEMPTS = 3
    
    def __init__(self, queue_path: Optional[Path] = None):
        self.queue_path = queue_path or self._default_path()
        self._items: Dict[str, RetryItem] = {}
        self._load()
    
    def _default_path(self) -> Path:
        """Get default queue file path."""
        return Path(__file__).parent.parent.parent / "state" / "retry_queue.json"
    
    def _load(self) -> None:
        """Load queue from disk."""
        if not self.queue_path.exists():
            self._items = {}
            return
        
        try:
            with open(self.queue_path) as f:
                data = json.load(f)
            
            self._items = {
                k: RetryItem.from_dict(v) 
                for k, v in data.get("items", {}).items()
            }
            logger.debug(f"Loaded {len(self._items)} items from retry queue")
        except Exception as e:
            logger.error(f"Failed to load retry queue: {e}")
            self._items = {}
    
    def _save(self) -> None:
        """Save queue to disk."""
        try:
            self.queue_path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                "version": 1,
                "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "items": {k: v.to_dict() for k, v in self._items.items()},
            }
            
            with open(self.queue_path, "w") as f:
                json.dump(data, f, indent=2)
            
            logger.debug(f"Saved {len(self._items)} items to retry queue")
        except Exception as e:
            logger.error(f"Failed to save retry queue: {e}")
    
    def enqueue(
        self,
        action: ActionDefinition,
        receipt: Receipt,
        tick_id: str,
        escalation_state: str,
        max_attempts: Optional[int] = None,
    ) -> bool:
        """
        Add a failed action to the retry queue.
        
        Returns True if enqueued, False if not retryable.
        """
        if receipt.status != "failed":
            return False
        
        if receipt.error and not receipt.error.retryable:
            logger.debug(f"Action {action.id} not retryable (error marked as non-retryable)")
            return False
        
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        # Check if already in queue
        if action.id in self._items:
            item = self._items[action.id]
            item.attempt_count += 1
            item.last_failed_at = now
            item.last_error_code = receipt.error.code if receipt.error else "unknown"
            item.last_error_message = receipt.error.message if receipt.error else "Unknown error"
            item.next_retry_at = item.calculate_next_retry()
            
            if item.attempt_count >= item.max_attempts:
                logger.warning(
                    f"Action {action.id} exceeded max retries ({item.max_attempts}), removing"
                )
                del self._items[action.id]
                self._save()
                return False
        else:
            item = RetryItem(
                action_id=action.id,
                adapter=action.adapter,
                channel=action.channel,
                template=action.template,
                attempt_count=1,
                max_attempts=max_attempts or self.DEFAULT_MAX_ATTEMPTS,
                first_failed_at=now,
                last_failed_at=now,
                next_retry_at="",
                last_error_code=receipt.error.code if receipt.error else "unknown",
                last_error_message=receipt.error.message if receipt.error else "Unknown error",
                tick_id=tick_id,
                escalation_state=escalation_state,
            )
            item.next_retry_at = item.calculate_next_retry()
            self._items[action.id] = item
        
        logger.info(
            f"Enqueued {action.id} for retry (attempt {item.attempt_count}/{item.max_attempts}, "
            f"next retry at {item.next_retry_at})"
        )
        
        self._save()
        return True
    
    def get_pending(self) -> List[RetryItem]:
        """Get all items ready for retry."""
        pending = [item for item in self._items.values() if item.should_retry()]
        return sorted(pending, key=lambda x: x.next_retry_at)
    
    def mark_success(self, action_id: str) -> None:
        """Remove action from queue after successful retry."""
        if action_id in self._items:
            del self._items[action_id]
            self._save()
            logger.info(f"Removed {action_id} from retry queue (success)")
    
    def clear(self) -> int:
        """Clear all items from queue. Returns count cleared."""
        count = len(self._items)
        self._items = {}
        self._save()
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        pending = self.get_pending()
        
        return {
            "total_items": len(self._items),
            "pending_now": len(pending),
            "by_adapter": self._count_by_field("adapter"),
            "by_attempt": self._count_by_field("attempt_count"),
        }
    
    def _count_by_field(self, field: str) -> Dict[str, int]:
        """Count items by a field value."""
        counts: Dict[str, int] = {}
        for item in self._items.values():
            key = str(getattr(item, field))
            counts[key] = counts.get(key, 0) + 1
        return counts
    
    def __len__(self) -> int:
        return len(self._items)
    
    def __contains__(self, action_id: str) -> bool:
        return action_id in self._items
