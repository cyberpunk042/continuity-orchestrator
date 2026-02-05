"""
Circuit Breaker — Protect against cascading failures.

Implements the circuit breaker pattern to prevent repeated calls
to failing external services.

## States

- CLOSED: Normal operation, requests pass through
- OPEN: Service is failing, requests are rejected immediately
- HALF_OPEN: Testing if service recovered

## Usage

    from src.reliability.circuit_breaker import CircuitBreaker
    
    breaker = CircuitBreaker("email")
    
    if breaker.allow_request():
        try:
            result = send_email()
            breaker.record_success()
        except Exception as e:
            breaker.record_failure()
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Blocking requests
    HALF_OPEN = "half_open" # Testing recovery


@dataclass
class CircuitStats:
    """Statistics for a circuit breaker."""
    
    # Counts
    success_count: int = 0
    failure_count: int = 0
    rejected_count: int = 0
    
    # Timing
    last_success_at: Optional[str] = None
    last_failure_at: Optional[str] = None
    last_state_change_at: Optional[str] = None
    
    # Current window
    window_start_at: Optional[str] = None
    window_failures: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CircuitStats":
        return cls(**data)


@dataclass
class CircuitConfig:
    """Configuration for a circuit breaker."""
    
    # Failure threshold to trip circuit
    failure_threshold: int = 5
    
    # Time window for counting failures (seconds)
    failure_window_seconds: int = 60
    
    # Time to wait before testing recovery (seconds)
    reset_timeout_seconds: int = 30
    
    # Number of successes needed to close circuit
    success_threshold: int = 2


class CircuitBreaker:
    """
    Circuit breaker for external service protection.
    
    Prevents cascading failures by blocking requests to
    failing services until they recover.
    """
    
    def __init__(
        self,
        name: str,
        config: Optional[CircuitConfig] = None,
    ):
        self.name = name
        self.config = config or CircuitConfig()
        
        self._state = CircuitState.CLOSED
        self._stats = CircuitStats()
        self._opened_at: Optional[float] = None
        self._half_open_successes = 0
    
    @property
    def state(self) -> CircuitState:
        """Get current state, checking for automatic transitions."""
        if self._state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self._transition_to(CircuitState.HALF_OPEN)
        return self._state
    
    def allow_request(self) -> bool:
        """
        Check if a request should be allowed.
        
        Returns True if request can proceed, False if circuit is open.
        """
        current_state = self.state  # Triggers state check
        
        if current_state == CircuitState.CLOSED:
            return True
        
        if current_state == CircuitState.HALF_OPEN:
            return True  # Allow test request
        
        # Circuit is OPEN
        self._stats.rejected_count += 1
        logger.warning(f"Circuit {self.name} is OPEN, rejecting request")
        return False
    
    def record_success(self) -> None:
        """Record a successful request."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._stats.success_count += 1
        self._stats.last_success_at = now
        
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_successes += 1
            if self._half_open_successes >= self.config.success_threshold:
                self._transition_to(CircuitState.CLOSED)
                logger.info(f"Circuit {self.name} recovered, transitioning to CLOSED")
    
    def record_failure(self) -> None:
        """Record a failed request."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._stats.failure_count += 1
        self._stats.last_failure_at = now
        
        if self._state == CircuitState.HALF_OPEN:
            # Failed during recovery test, back to OPEN
            self._transition_to(CircuitState.OPEN)
            logger.warning(f"Circuit {self.name} failed recovery test, back to OPEN")
            return
        
        if self._state == CircuitState.CLOSED:
            self._record_window_failure()
            
            if self._stats.window_failures >= self.config.failure_threshold:
                self._transition_to(CircuitState.OPEN)
                logger.warning(
                    f"Circuit {self.name} tripped: {self._stats.window_failures} failures "
                    f"in {self.config.failure_window_seconds}s"
                )
    
    def _record_window_failure(self) -> None:
        """Record failure in current window, reset window if expired."""
        now = time.time()
        
        if self._stats.window_start_at:
            window_start = datetime.fromisoformat(
                self._stats.window_start_at.replace("Z", "+00:00")
            ).timestamp()
            
            if now - window_start > self.config.failure_window_seconds:
                # Window expired, start new one
                self._stats.window_start_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                self._stats.window_failures = 1
            else:
                self._stats.window_failures += 1
        else:
            self._stats.window_start_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            self._stats.window_failures = 1
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to test recovery."""
        if self._opened_at is None:
            return True
        
        elapsed = time.time() - self._opened_at
        return elapsed >= self.config.reset_timeout_seconds
    
    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state."""
        old_state = self._state
        self._state = new_state
        self._stats.last_state_change_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        if new_state == CircuitState.OPEN:
            self._opened_at = time.time()
            self._half_open_successes = 0
        elif new_state == CircuitState.CLOSED:
            self._opened_at = None
            self._half_open_successes = 0
            self._stats.window_failures = 0
            self._stats.window_start_at = None
        elif new_state == CircuitState.HALF_OPEN:
            self._half_open_successes = 0
        
        logger.info(f"Circuit {self.name}: {old_state.value} → {new_state.value}")
    
    def force_open(self) -> None:
        """Manually open the circuit."""
        self._transition_to(CircuitState.OPEN)
    
    def force_close(self) -> None:
        """Manually close the circuit."""
        self._transition_to(CircuitState.CLOSED)
    
    def reset(self) -> None:
        """Reset circuit to initial state."""
        self._state = CircuitState.CLOSED
        self._stats = CircuitStats()
        self._opened_at = None
        self._half_open_successes = 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get circuit statistics."""
        return {
            "name": self.name,
            "state": self.state.value,
            "stats": self._stats.to_dict(),
            "config": asdict(self.config),
        }


class CircuitBreakerRegistry:
    """
    Registry of circuit breakers for all adapters.
    
    Provides centralized management and persistence.
    """
    
    def __init__(self, persist_path: Optional[Path] = None):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._persist_path = persist_path
    
    def get(self, name: str, config: Optional[CircuitConfig] = None) -> CircuitBreaker:
        """Get or create a circuit breaker."""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name, config)
        return self._breakers[name]
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Get stats for all circuit breakers."""
        return {
            name: breaker.get_stats()
            for name, breaker in self._breakers.items()
        }
    
    def reset_all(self) -> None:
        """Reset all circuit breakers."""
        for breaker in self._breakers.values():
            breaker.reset()
    
    def get_open_circuits(self) -> List[str]:
        """Get names of all open circuits."""
        return [
            name for name, breaker in self._breakers.items()
            if breaker.state == CircuitState.OPEN
        ]


# Global registry instance
_registry: Optional[CircuitBreakerRegistry] = None


def get_circuit_breaker(name: str, config: Optional[CircuitConfig] = None) -> CircuitBreaker:
    """Get a circuit breaker from the global registry."""
    global _registry
    if _registry is None:
        _registry = CircuitBreakerRegistry()
    return _registry.get(name, config)


def get_registry() -> CircuitBreakerRegistry:
    """Get the global circuit breaker registry."""
    global _registry
    if _registry is None:
        _registry = CircuitBreakerRegistry()
    return _registry
