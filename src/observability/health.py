"""
Health Check — System health status for monitoring.

Provides a structured health check with component status.

## Usage

    from src.observability.health import HealthChecker
    
    checker = HealthChecker()
    status = checker.check()
    
    if status.healthy:
        print("All systems operational")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..models.state import State

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    """Health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ComponentHealth:
    """Health status of a single component."""
    
    name: str
    status: HealthStatus
    message: str = ""
    latency_ms: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass 
class SystemHealth:
    """Overall system health status."""
    
    status: HealthStatus
    timestamp: str
    uptime_seconds: float
    components: List[ComponentHealth]
    
    @property
    def healthy(self) -> bool:
        return self.status == HealthStatus.HEALTHY
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "timestamp": self.timestamp,
            "uptime_seconds": self.uptime_seconds,
            "healthy": self.healthy,
            "components": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "message": c.message,
                    "latency_ms": c.latency_ms,
                    "details": c.details,
                }
                for c in self.components
            ],
        }


class HealthChecker:
    """
    System health checker.
    
    Checks all components and provides aggregate status.
    """
    
    def __init__(
        self,
        state_path: Optional[Path] = None,
        audit_path: Optional[Path] = None,
    ):
        self.state_path = state_path or Path("state/current.json")
        self.audit_path = audit_path or Path("audit/ledger.ndjson")
        self._start_time = time.time()
    
    def check(self) -> SystemHealth:
        """Run all health checks and return status."""
        components = []
        
        # Check state file
        components.append(self._check_state_file())
        
        # Check audit log
        components.append(self._check_audit_log())
        
        # Check tick freshness
        components.append(self._check_tick_freshness())
        
        # Check retry queue
        components.append(self._check_retry_queue())
        
        # Check circuit breakers
        components.append(self._check_circuit_breakers())
        
        # Determine overall status
        statuses = [c.status for c in components]
        if HealthStatus.UNHEALTHY in statuses:
            overall = HealthStatus.UNHEALTHY
        elif HealthStatus.DEGRADED in statuses:
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY
        
        return SystemHealth(
            status=overall,
            timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            uptime_seconds=time.time() - self._start_time,
            components=components,
        )
    
    def _check_state_file(self) -> ComponentHealth:
        """Check if state file exists and is valid."""
        start = time.time()
        
        try:
            if not self.state_path.exists():
                return ComponentHealth(
                    name="state_file",
                    status=HealthStatus.UNHEALTHY,
                    message="State file not found",
                )
            
            # Try to load state
            from ..persistence.state_file import load_state
            state = load_state(self.state_path)
            
            latency = (time.time() - start) * 1000
            
            return ComponentHealth(
                name="state_file",
                status=HealthStatus.HEALTHY,
                message="State file loaded successfully",
                latency_ms=latency,
                details={
                    "state_id": state.meta.state_id,
                    "stage": state.escalation.state,
                },
            )
        except Exception as e:
            return ComponentHealth(
                name="state_file",
                status=HealthStatus.UNHEALTHY,
                message=f"Failed to load state: {e}",
            )
    
    def _check_audit_log(self) -> ComponentHealth:
        """Check audit log writability."""
        start = time.time()
        
        try:
            if not self.audit_path.parent.exists():
                return ComponentHealth(
                    name="audit_log",
                    status=HealthStatus.DEGRADED,
                    message="Audit directory not found",
                )
            
            # Check if writable
            writable = self.audit_path.parent.exists()
            
            latency = (time.time() - start) * 1000
            
            # Get log size if exists
            size = 0
            entries = 0
            if self.audit_path.exists():
                size = self.audit_path.stat().st_size
                with open(self.audit_path) as f:
                    entries = sum(1 for _ in f)
            
            return ComponentHealth(
                name="audit_log",
                status=HealthStatus.HEALTHY,
                message="Audit log accessible",
                latency_ms=latency,
                details={
                    "size_bytes": size,
                    "entries": entries,
                },
            )
        except Exception as e:
            return ComponentHealth(
                name="audit_log",
                status=HealthStatus.DEGRADED,
                message=f"Audit log check failed: {e}",
            )
    
    def _check_tick_freshness(self) -> ComponentHealth:
        """Check if ticks are running regularly."""
        try:
            from ..persistence.state_file import load_state
            state = load_state(self.state_path)
            
            # Parse last updated time
            updated_at = datetime.fromisoformat(
                state.meta.updated_at_iso.replace("Z", "+00:00")
            )
            now = datetime.now(timezone.utc)
            age_minutes = (now - updated_at).total_seconds() / 60
            
            if age_minutes > 60:
                return ComponentHealth(
                    name="tick_freshness",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Last tick was {age_minutes:.0f} minutes ago",
                    details={"age_minutes": age_minutes},
                )
            elif age_minutes > 30:
                return ComponentHealth(
                    name="tick_freshness",
                    status=HealthStatus.DEGRADED,
                    message=f"Last tick was {age_minutes:.0f} minutes ago",
                    details={"age_minutes": age_minutes},
                )
            else:
                return ComponentHealth(
                    name="tick_freshness",
                    status=HealthStatus.HEALTHY,
                    message=f"Last tick was {age_minutes:.1f} minutes ago",
                    details={"age_minutes": age_minutes},
                )
        except Exception as e:
            return ComponentHealth(
                name="tick_freshness",
                status=HealthStatus.DEGRADED,
                message=f"Could not check tick freshness: {e}",
            )
    
    def _check_retry_queue(self) -> ComponentHealth:
        """Check retry queue status."""
        try:
            from ..reliability.retry_queue import RetryQueue
            queue = RetryQueue()
            stats = queue.get_stats()
            
            if stats["total_items"] > 10:
                status = HealthStatus.DEGRADED
                message = f"Retry queue has {stats['total_items']} items"
            else:
                status = HealthStatus.HEALTHY
                message = f"Retry queue has {stats['total_items']} items"
            
            return ComponentHealth(
                name="retry_queue",
                status=status,
                message=message,
                details=stats,
            )
        except Exception as e:
            return ComponentHealth(
                name="retry_queue",
                status=HealthStatus.HEALTHY,
                message="Retry queue not initialized",
            )
    
    def _check_circuit_breakers(self) -> ComponentHealth:
        """Check circuit breaker status."""
        try:
            from ..reliability.circuit_breaker import get_registry
            registry = get_registry()
            open_circuits = registry.get_open_circuits()
            
            if open_circuits:
                return ComponentHealth(
                    name="circuit_breakers",
                    status=HealthStatus.DEGRADED,
                    message=f"Open circuits: {', '.join(open_circuits)}",
                    details={"open": open_circuits},
                )
            else:
                return ComponentHealth(
                    name="circuit_breakers",
                    status=HealthStatus.HEALTHY,
                    message="All circuits closed",
                )
        except Exception as e:
            return ComponentHealth(
                name="circuit_breakers",
                status=HealthStatus.HEALTHY,
                message="Circuit breakers not initialized",
            )
