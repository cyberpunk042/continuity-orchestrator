"""
Tick Lifecycle — The core execution loop.

The tick is the atomic unit of execution. Each tick:
1. Initializes context
2. Computes time fields
3. Evaluates rules (no renewal in prototype)
4. Applies mutations
5. Selects actions
6. Executes adapters (mock for prototype)
7. Records audit entries
8. Returns result

## Design Principles

- **Determinism**: Given the same state and time, the tick produces the same result
- **Idempotency**: Actions are not re-executed if already completed
- **Atomicity**: Either all changes persist or none do
- **Auditability**: Every decision is logged

## Tick ID Format

    T-{YYYYMMDD}T{HHMMSS}-{RANDOM}
    Example: T-20260204T221903-92929A

## Usage

    from src.engine.tick import run_tick
    
    result = run_tick(
        state=state,
        policy=policy,
        audit_writer=audit_writer,
        dry_run=False,
    )
    
    if result.state_changed:
        print(f"Transitioned to {result.new_state}")
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from ..models.state import ActionReceipt, State
from ..persistence.audit import AuditWriter
from ..policy.models import Policy
from .rules import evaluate_rules
from .state import apply_rules
from .time_eval import compute_time_fields

logger = logging.getLogger(__name__)


@dataclass
class TickResult:
    """Result of a tick execution."""

    tick_id: str
    started_at: str
    ended_at: Optional[str] = None
    duration_ms: int = 0

    # State info
    previous_state: str = ""
    new_state: str = ""
    state_changed: bool = False

    # Quiescence: True when the tick determined there was nothing to do.
    # Conditions: no state transition, all selected actions are terminal.
    quiescent: bool = False

    # Rules
    matched_rules: List[str] = field(default_factory=list)

    # Actions
    actions_selected: List[str] = field(default_factory=list)
    actions_executed: List[str] = field(default_factory=list)

    # Errors
    errors: List[str] = field(default_factory=list)


def generate_tick_id() -> str:
    """Generate a unique tick ID."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    suffix = uuid4().hex[:6].upper()
    return f"T-{ts}-{suffix}"


def run_tick(
    state: State,
    policy: Policy,
    now: Optional[datetime] = None,
    audit_writer: Optional[AuditWriter] = None,
    dry_run: bool = False,
) -> TickResult:
    """
    Execute a single tick of the continuity engine.

    This is the main entry point for the engine.

    Args:
        state: Current state (will be mutated)
        policy: Loaded policy
        now: Override timestamp (optional)
        audit_writer: Audit ledger writer (optional)
        dry_run: If True, don't execute adapters

    Returns:
        TickResult with execution details
    """
    start_time = time.time()
    tick_id = generate_tick_id()

    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    result = TickResult(
        tick_id=tick_id,
        started_at=now.isoformat().replace("+00:00", "Z"),
        previous_state=state.escalation.state,
    )

    logger.info(
        f"{'═' * 50}\n"
        f"  Starting Tick {tick_id}\n"
        f"  ├─ Project: {state.meta.project}\n"
        f"  ├─ State: {state.escalation.state}\n"
        f"  ├─ Plan: {state.meta.plan_id}\n"
        f"  └─ Mode: {'ARMED' if state.mode.armed else 'DISARMED'}\n"
        f"{'─' * 50}"
    )

    # --- Phase 1: Initialization ---
    # Reset per-tick ephemeral flags — these only remain true if
    # a renewal actually happens during THIS tick's lifecycle.
    state.renewal.renewed_this_tick = False

    # Sync project name from environment if it has changed
    env_project = os.environ.get("PROJECT_NAME")
    if env_project and env_project != state.meta.project:
        logger.info(
            f"Project name updated: '{state.meta.project}' → '{env_project}'"
        )
        state.meta.project = env_project

    # Sync routing fields from environment — env vars are the source of truth
    _routing = state.integrations.routing
    _env_sync = {
        "operator_sms": ("OPERATOR_SMS", _routing.operator_sms),
        "operator_email": ("OPERATOR_EMAIL", _routing.operator_email),
    }
    for field_name, (env_key, current_val) in _env_sync.items():
        env_val = os.environ.get(env_key)
        if env_val and env_val != current_val:
            logger.info(f"Routing sync: {field_name} updated from {env_key}")
            setattr(_routing, field_name, env_val)

    state_id = state.meta.state_id

    # Buffer audit entries — flushed at finalization only if not quiescent.
    # This prevents tick_start and rule_matched entries from being written
    # for ticks that turn out to have nothing to do.
    _audit_buffer = []

    # Record tick_start (buffered)
    if audit_writer:
        _audit_buffer.append((
            "tick_start",
            dict(
                tick_id=tick_id,
                state_id=state_id,
                escalation_state=state.escalation.state,
                policy_version=state.meta.policy_version,
                plan_id=state.meta.plan_id,
                now_iso=now.isoformat().replace("+00:00", "Z"),
                deadline_iso=state.timer.deadline_iso,
            ),
        ))

    # --- Phase 2: Time Evaluation ---
    compute_time_fields(state, now)

    logger.info(
        f"Time: deadline={state.timer.deadline_iso}, "
        f"time_to_deadline={state.timer.time_to_deadline_minutes}m, "
        f"overdue={state.timer.overdue_minutes}m"
    )

    # --- Phase 3: Renewal Evaluation ---
    # In prototype, renewal is manual via set-deadline command
    # No automatic renewal check here

    # --- Phase 4: Policy Evaluation (Rules) ---
    matched = evaluate_rules(state, policy.rules)
    result.matched_rules = [r.id for r in matched]

    for r in matched:
        logger.info(f"Rule matched: {r.id}")
        if audit_writer:
            _audit_buffer.append((
                "rule_matched",
                dict(
                    tick_id=tick_id,
                    state_id=state_id,
                    rule_id=r.id,
                    escalation_state=state.escalation.state,
                    policy_version=state.meta.policy_version,
                    plan_id=state.meta.plan_id,
                ),
            ))

    # --- Phase 5: State Mutation ---
    previous_state = state.escalation.state
    mutation_result = apply_rules(state, matched, now)

    if mutation_result["state_changed"]:
        result.state_changed = True
        result.new_state = mutation_result["new_state"]
        logger.info(f"State transition: {previous_state} → {result.new_state}")

        if audit_writer:
            _audit_buffer.append(("state_transition", dict(
                tick_id=tick_id,
                state_id=state_id,
                from_state=previous_state,
                to_state=result.new_state,
                rule_id=matched[-1].id if matched else "unknown",
                policy_version=state.meta.policy_version,
                plan_id=state.meta.plan_id,
            )))
    else:
        result.new_state = state.escalation.state

    # --- Phase 5b: Manual Release Trigger Check ---
    # If release was manually triggered, check if delay has passed and execute
    if hasattr(state, 'release') and state.release.triggered:
        from dateutil import parser as date_parser
        
        execute_after = state.release.execute_after_iso
        should_execute = False
        
        if execute_after:
            # Delayed release - check if time has passed
            execute_time = date_parser.isoparse(execute_after)
            if execute_time.tzinfo is None:
                execute_time = execute_time.replace(tzinfo=timezone.utc)
            should_execute = now >= execute_time
        else:
            # Immediate release (no delay)
            should_execute = True
        
        if should_execute:
            target_stage = state.release.target_stage or "FULL"
            logger.info(f"🚨 Manual release triggered - forcing stage to {target_stage}")
            
            # Force state transition to target stage
            if state.escalation.state != target_stage:
                result.state_changed = True
                result.previous_state = state.escalation.state
                state.escalation.state = target_stage
                state.escalation.state_entered_at_iso = now.isoformat().replace("+00:00", "Z")
                state.escalation.last_transition_rule_id = "MANUAL_RELEASE"
                result.new_state = target_stage
                
                if audit_writer:
                    _audit_buffer.append(("state_transition", dict(
                        tick_id=tick_id,
                        state_id=state_id,
                        from_state=result.previous_state,
                        to_state=target_stage,
                        rule_id="MANUAL_RELEASE",
                        policy_version=state.meta.policy_version,
                        plan_id=state.meta.plan_id,
                    )))
            
            # Keep release.triggered set so site continues showing DELAYED
            logger.info("Release executed (triggered flag retained)")

    # --- Phase 6: Action Selection ---
    current_stage = state.escalation.state
    actions_for_stage = policy.plan.get_actions_for_stage(current_stage)
    result.actions_selected = [a.id for a in actions_for_stage]

    logger.info(f"Actions for stage {current_stage}: {result.actions_selected}")

    # --- Phase 6b: Quiescence Check ---
    # If no state changed and all selected actions are already terminal,
    # the tick has nothing to do. Skip adapter execution and audit.
    if not result.state_changed and not dry_run:
        all_terminal = True
        for action in actions_for_stage:
            if not action.enabled:
                continue  # Disabled actions don't count
            if action.id in state.actions.executed:
                prev = state.actions.executed[action.id]
                if prev.status in ("ok", "skipped"):
                    continue  # Terminal
            # Found a non-terminal action
            all_terminal = False
            break

        if all_terminal:
            result.quiescent = True
            logger.info("Tick is quiescent — nothing to do")

    # --- Phase 7: Adapter Execution ---
    # Clear previous tick's actions
    state.actions.last_tick_actions = []

    if not dry_run and actions_for_stage and not result.quiescent:
        from pathlib import Path

        from ..adapters.base import ExecutionContext
        from ..adapters.registry import AdapterRegistry
        from ..templates.context import build_template_context
        from ..templates.resolver import TemplateResolver

        # Check environment for mock mode (default to True for safety)
        mock_mode = os.environ.get("ADAPTER_MOCK_MODE", "true").lower() in ("true", "1", "yes")
        registry = AdapterRegistry(mock_mode=mock_mode)
        
        if not mock_mode:
            logger.info("Running with REAL adapters")
        
        # Template resolver (looks for templates in project root)
        project_root = Path(__file__).parent.parent.parent
        template_resolver = TemplateResolver(project_root / "templates")

        for action in actions_for_stage:
            # Check if action is disabled in the plan
            if not action.enabled:
                logger.info(f"Skipping {action.id}: disabled in plan")
                state.actions.executed[action.id] = ActionReceipt(
                    status="skipped",
                    last_executed_iso=state.timer.now_iso or "",
                )
                state.actions.last_tick_actions.append(action.id)
                continue

            # Check idempotency — terminal statuses: ok, skipped
            # "ok" = action succeeded; "skipped" = action evaluated but not applicable
            # (e.g., no webhook URLs configured). Both are terminal for this
            # escalation cycle. A reset/renew clears all receipts.
            if action.id in state.actions.executed:
                prev = state.actions.executed[action.id]
                if prev.status in ("ok", "skipped"):
                    logger.info(f"Skipping {action.id}: already {prev.status}")
                    continue

            # Resolve template if specified
            template_content = None
            if action.template:
                tpl_context = build_template_context(state, action, tick_id)
                template_content = template_resolver.resolve_and_render(
                    action.template, tpl_context
                )
                if template_content:
                    logger.debug(f"Resolved template '{action.template}'")

                    # Resolve media:// URIs to public URLs
                    from ..templates.media import resolve_media_uris
                    template_content = resolve_media_uris(
                        template_content, stage=current_stage
                    )

            # Build context
            context = ExecutionContext(
                state=state,
                action=action,
                tick_id=tick_id,
                template_content=template_content,
            )

            # Execute with timing
            action_start = time.time()
            logger.info(
                f"→ Executing action: {action.id} "
                f"[adapter={action.adapter}, channel={action.channel}]"
            )
            
            receipt = registry.execute_action(action, context)
            
            action_duration_ms = int((time.time() - action_start) * 1000)

            # Log result with status indicator
            if receipt.status == "ok":
                logger.info(
                    f"  ✓ {action.id}: OK "
                    f"[delivery_id={receipt.delivery_id}, {action_duration_ms}ms]"
                )
            elif receipt.status == "skipped":
                skip_reason = receipt.details.get("skip_reason", "unknown") if receipt.details else "unknown"
                logger.info(
                    f"  ⊘ {action.id}: SKIPPED [{skip_reason}]"
                )
            else:
                error_msg = receipt.error.message if receipt.error else "unknown error"
                error_code = receipt.error.code if receipt.error else "unknown"
                retryable = receipt.error.retryable if receipt.error else False
                logger.warning(
                    f"  ✗ {action.id}: FAILED "
                    f"[code={error_code}, retryable={retryable}, {action_duration_ms}ms] "
                    f"— {error_msg}"
                )

            # Record receipt
            state.actions.executed[action.id] = ActionReceipt(
                status=receipt.status,
                last_delivery_id=receipt.delivery_id,
                last_executed_iso=receipt.ts_iso,
            )
            state.actions.last_tick_actions.append(action.id)
            result.actions_executed.append(action.id)

            # Audit
            if audit_writer:
                audit_writer.emit(
                    event_type="action_receipt",
                    tick_id=tick_id,
                    state_id=state_id,
                    escalation_state=current_stage,
                    policy_version=state.meta.policy_version,
                    plan_id=state.meta.plan_id,
                    details=receipt.model_dump(),
                )

    # --- Phase 8: Finalization ---
    end_time = time.time()
    result.duration_ms = int((end_time - start_time) * 1000)
    result.ended_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # When quiescent, don't mutate state or write audit.
    # The state file should remain untouched so no git commit is triggered.
    # Liveness is tracked by sentinel (separate from audit).
    if not result.quiescent:
        # Update state metadata
        state.meta.updated_at_iso = result.ended_at

        # Flush buffered audit entries
        if audit_writer:
            for entry_type, entry_kwargs in _audit_buffer:
                if entry_type == "tick_start":
                    audit_writer.emit_tick_start(**entry_kwargs)
                elif entry_type == "rule_matched":
                    audit_writer.emit_rule_matched(**entry_kwargs)
                elif entry_type == "state_transition":
                    audit_writer.emit_state_transition(**entry_kwargs)

            # Emit tick_end audit
            audit_writer.emit_tick_end(
                tick_id=tick_id,
                state_id=state_id,
                escalation_state=state.escalation.state,
                policy_version=state.meta.policy_version,
                plan_id=state.meta.plan_id,
                duration_ms=result.duration_ms,
                actions_executed=len(result.actions_executed),
                state_changed=result.state_changed,
                matched_rules=result.matched_rules,
            )

    # Log detailed tick summary
    state_indicator = "🔄" if result.state_changed else "━"
    state_change_str = f"{result.previous_state} → {result.new_state}" if result.state_changed else result.new_state
    
    logger.info(
        f"{'═' * 50}\n"
        f"  Tick {tick_id} Complete\n"
        f"  ├─ Duration: {result.duration_ms}ms\n"
        f"  ├─ State: {state_indicator} {state_change_str}\n"
        f"  ├─ Rules matched: {len(result.matched_rules)}\n"
        f"  ├─ Actions selected: {len(result.actions_selected)}\n"
        f"  └─ Actions executed: {len(result.actions_executed)}\n"
        f"{'═' * 50}"
    )

    return result
