"""
Tests for the Reliability Module — Retry Queue and Circuit Breakers.
"""

import pytest
import tempfile
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from src.reliability.retry_queue import RetryQueue, RetryItem
from src.reliability.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitState,
    CircuitConfig,
    get_circuit_breaker,
    get_registry,
)
from src.models.receipt import Receipt
from src.policy.models import ActionDefinition


class TestRetryItem:
    """Tests for RetryItem."""
    
    def test_should_retry_under_max_attempts(self):
        """Test item should retry if under max attempts."""
        now = datetime.now(timezone.utc)
        past = (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        
        item = RetryItem(
            action_id="test",
            adapter="email",
            channel="email",
            template=None,
            attempt_count=1,
            max_attempts=3,
            next_retry_at=past,
        )
        
        assert item.should_retry() is True
    
    def test_should_not_retry_at_max_attempts(self):
        """Test item should not retry at max attempts."""
        item = RetryItem(
            action_id="test",
            adapter="email",
            channel="email",
            template=None,
            attempt_count=3,
            max_attempts=3,
            next_retry_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )
        
        assert item.should_retry() is False
    
    def test_should_not_retry_before_next_time(self):
        """Test item should not retry before next_retry_at."""
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        
        item = RetryItem(
            action_id="test",
            adapter="email",
            channel="email",
            template=None,
            attempt_count=1,
            max_attempts=3,
            next_retry_at=future,
        )
        
        assert item.should_retry() is False
    
    def test_calculate_next_retry_exponential(self):
        """Test exponential backoff calculation."""
        item = RetryItem(
            action_id="test",
            adapter="email",
            channel="email",
            template=None,
        )
        
        # First attempt: 1 minute
        item.attempt_count = 1
        next1 = item.calculate_next_retry()
        
        # Second attempt: 5 minutes
        item.attempt_count = 2
        next2 = item.calculate_next_retry()
        
        # Parse and compare
        t1 = datetime.fromisoformat(next1.replace("Z", "+00:00"))
        t2 = datetime.fromisoformat(next2.replace("Z", "+00:00"))
        
        # t2 should be about 4 minutes later than t1 would be
        assert t2 > t1


class TestRetryQueue:
    """Tests for RetryQueue."""
    
    @pytest.fixture
    def temp_queue_path(self):
        """Create temporary queue file."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)
        yield path
        if path.exists():
            path.unlink()
    
    @pytest.fixture
    def sample_action(self):
        """Create sample action."""
        return ActionDefinition(
            id="test_action",
            adapter="email",
            channel="email",
            template="test.md",
        )
    
    @pytest.fixture
    def failed_receipt(self):
        """Create failed receipt."""
        return Receipt.failed(
            adapter="email",
            action_id="test_action",
            channel="email",
            error_code="send_error",
            error_message="Failed to send",
            retryable=True,
        )
    
    def test_enqueue_failed_action(self, temp_queue_path, sample_action, failed_receipt):
        """Test enqueueing a failed action."""
        queue = RetryQueue(temp_queue_path)
        
        result = queue.enqueue(
            sample_action,
            failed_receipt,
            tick_id="T001",
            escalation_state="OK",
        )
        
        assert result is True
        assert len(queue) == 1
        assert "test_action" in queue
    
    def test_enqueue_non_retryable_rejected(self, temp_queue_path, sample_action):
        """Test non-retryable actions are not enqueued."""
        queue = RetryQueue(temp_queue_path)
        
        receipt = Receipt.failed(
            adapter="email",
            action_id="test_action",
            channel="email",
            error_code="permanent_error",
            error_message="Invalid address",
            retryable=False,
        )
        
        result = queue.enqueue(
            sample_action,
            receipt,
            tick_id="T001",
            escalation_state="OK",
        )
        
        assert result is False
        assert len(queue) == 0
    
    def test_enqueue_success_rejected(self, temp_queue_path, sample_action):
        """Test successful receipts are not enqueued."""
        queue = RetryQueue(temp_queue_path)
        
        receipt = Receipt.ok(
            adapter="email",
            action_id="test_action",
            channel="email",
            delivery_id="msg123",
        )
        
        result = queue.enqueue(
            sample_action,
            receipt,
            tick_id="T001",
            escalation_state="OK",
        )
        
        assert result is False
    
    def test_persistence(self, temp_queue_path, sample_action, failed_receipt):
        """Test queue persists to disk."""
        queue1 = RetryQueue(temp_queue_path)
        queue1.enqueue(sample_action, failed_receipt, "T001", "OK")
        
        # Create new queue from same path
        queue2 = RetryQueue(temp_queue_path)
        
        assert len(queue2) == 1
        assert "test_action" in queue2
    
    def test_mark_success_removes_item(self, temp_queue_path, sample_action, failed_receipt):
        """Test marking success removes item."""
        queue = RetryQueue(temp_queue_path)
        queue.enqueue(sample_action, failed_receipt, "T001", "OK")
        
        queue.mark_success("test_action")
        
        assert len(queue) == 0
    
    def test_clear(self, temp_queue_path, sample_action, failed_receipt):
        """Test clearing queue."""
        queue = RetryQueue(temp_queue_path)
        queue.enqueue(sample_action, failed_receipt, "T001", "OK")
        
        count = queue.clear()
        
        assert count == 1
        assert len(queue) == 0
    
    def test_get_stats(self, temp_queue_path, sample_action, failed_receipt):
        """Test getting queue stats."""
        queue = RetryQueue(temp_queue_path)
        queue.enqueue(sample_action, failed_receipt, "T001", "OK")
        
        stats = queue.get_stats()
        
        assert stats["total_items"] == 1
        assert "by_adapter" in stats


class TestCircuitBreaker:
    """Tests for CircuitBreaker."""
    
    def test_initial_state_closed(self):
        """Test circuit starts closed."""
        breaker = CircuitBreaker("test")
        assert breaker.state == CircuitState.CLOSED
    
    def test_allow_request_when_closed(self):
        """Test requests allowed when closed."""
        breaker = CircuitBreaker("test")
        assert breaker.allow_request() is True
    
    def test_trips_after_threshold(self):
        """Test circuit trips after failure threshold."""
        config = CircuitConfig(failure_threshold=3, failure_window_seconds=60)
        breaker = CircuitBreaker("test", config)
        
        # Record failures
        for _ in range(3):
            breaker.record_failure()
        
        assert breaker.state == CircuitState.OPEN
        assert breaker.allow_request() is False
    
    def test_rejects_when_open(self):
        """Test requests rejected when open."""
        breaker = CircuitBreaker("test")
        breaker.force_open()
        
        assert breaker.allow_request() is False
    
    def test_half_open_after_timeout(self):
        """Test transitions to half-open after reset timeout."""
        config = CircuitConfig(reset_timeout_seconds=0)  # Immediate
        breaker = CircuitBreaker("test", config)
        breaker.force_open()
        
        # Check state triggers transition
        assert breaker.state == CircuitState.HALF_OPEN
    
    def test_closes_after_successes(self):
        """Test closes after success threshold in half-open."""
        config = CircuitConfig(success_threshold=2, reset_timeout_seconds=0)
        breaker = CircuitBreaker("test", config)
        breaker.force_open()
        
        # Trigger half-open
        _ = breaker.state
        
        # Record successes
        breaker.record_success()
        breaker.record_success()
        
        assert breaker.state == CircuitState.CLOSED
    
    def test_reopens_on_failure_in_half_open(self):
        """Test reopens on failure in half-open state."""
        config = CircuitConfig(reset_timeout_seconds=0)
        breaker = CircuitBreaker("test", config)
        breaker.force_open()
        
        # Trigger half-open
        _ = breaker.state
        
        # Record failure
        breaker.record_failure()
        
        # Check internal state directly to avoid re-triggering transition
        assert breaker._state == CircuitState.OPEN
    
    def test_reset(self):
        """Test reset clears state."""
        breaker = CircuitBreaker("test")
        breaker.force_open()
        breaker.reset()
        
        assert breaker.state == CircuitState.CLOSED
    
    def test_get_stats(self):
        """Test getting stats."""
        breaker = CircuitBreaker("test")
        breaker.record_success()
        
        stats = breaker.get_stats()
        
        assert stats["name"] == "test"
        assert stats["state"] == "closed"
        assert stats["stats"]["success_count"] == 1


class TestCircuitBreakerRegistry:
    """Tests for CircuitBreakerRegistry."""
    
    def test_get_creates_breaker(self):
        """Test get creates new breaker."""
        registry = CircuitBreakerRegistry()
        
        breaker = registry.get("email")
        
        assert breaker is not None
        assert breaker.name == "email"
    
    def test_get_returns_same_breaker(self):
        """Test get returns same instance."""
        registry = CircuitBreakerRegistry()
        
        b1 = registry.get("email")
        b2 = registry.get("email")
        
        assert b1 is b2
    
    def test_get_open_circuits(self):
        """Test getting open circuits."""
        registry = CircuitBreakerRegistry()
        
        registry.get("email").force_open()
        registry.get("sms")
        
        open_circuits = registry.get_open_circuits()
        
        assert "email" in open_circuits
        assert "sms" not in open_circuits
    
    def test_reset_all(self):
        """Test resetting all breakers."""
        registry = CircuitBreakerRegistry()
        
        registry.get("email").force_open()
        registry.get("sms").force_open()
        registry.reset_all()
        
        assert registry.get("email").state == CircuitState.CLOSED
        assert registry.get("sms").state == CircuitState.CLOSED
