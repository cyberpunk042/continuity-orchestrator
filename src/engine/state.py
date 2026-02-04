"""
State Mutation — Apply rule mutations to state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from ..models.state import State
from ..policy.models import Rule


def set_nested_value(obj: Any, path: str, value: Any) -> None:
    """
    Set a nested value using dot notation.
    
    Args:
        obj: Object to modify
        path: Dot-separated path
        value: Value to set
    """
    parts = path.split(".")
    current = obj
    
    # Navigate to parent
    for part in parts[:-1]:
        if hasattr(current, part):
            current = getattr(current, part)
        elif isinstance(current, dict):
            current = current[part]
        else:
            return  # Path doesn't exist
    
    # Set final attribute
    final_part = parts[-1]
    if hasattr(current, final_part):
        setattr(current, final_part, value)
    elif isinstance(current, dict):
        current[final_part] = value


def clear_nested_value(obj: Any, path: str) -> None:
    """
    Clear a nested value (reset to default).
    
    For integers: 0
    For booleans: False
    For strings/others: None
    
    Args:
        obj: Object to modify
        path: Dot-separated path
    """
    parts = path.split(".")
    current = obj
    
    # Navigate to parent
    for part in parts[:-1]:
        if hasattr(current, part):
            current = getattr(current, part)
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return
    
    if current is None:
        return
    
    final_part = parts[-1]
    
    # Determine default value based on current type
    if hasattr(current, final_part):
        current_value = getattr(current, final_part)
        if isinstance(current_value, int):
            setattr(current, final_part, 0)
        elif isinstance(current_value, bool):
            setattr(current, final_part, False)
        else:
            setattr(current, final_part, None)
    elif isinstance(current, dict) and final_part in current:
        current_value = current[final_part]
        if isinstance(current_value, int):
            current[final_part] = 0
        elif isinstance(current_value, bool):
            current[final_part] = False
        else:
            current[final_part] = None


def apply_rule_mutation(state: State, rule: Rule, now: datetime) -> Dict[str, Any]:
    """
    Apply a rule's mutations to the state.
    
    Args:
        state: State to mutate
        rule: Rule containing mutations
        now: Current timestamp
    
    Returns:
        Dict with mutation details for auditing:
        - state_changed: bool
        - new_state: Optional[str]
        - fields_set: List[str]
        - fields_cleared: List[str]
    """
    result: Dict[str, Any] = {
        "state_changed": False,
        "new_state": None,
        "fields_set": [],
        "fields_cleared": [],
    }
    
    then = rule.then
    
    # Handle set_state
    if "set_state" in then:
        new_state = then["set_state"]
        old_state = state.escalation.state
        
        if old_state != new_state:
            state.escalation.state = new_state
            state.escalation.state_entered_at_iso = now.isoformat().replace("+00:00", "Z")
            state.escalation.last_transition_rule_id = rule.id
            result["state_changed"] = True
            result["new_state"] = new_state
    
    # Handle set
    if "set" in then:
        for path, value in then["set"].items():
            set_nested_value(state, path, value)
            result["fields_set"].append(path)
    
    # Handle clear
    if "clear" in then:
        for path in then["clear"]:
            clear_nested_value(state, path)
            result["fields_cleared"].append(path)
    
    return result


def apply_rules(
    state: State,
    matched_rules: List[Rule],
    now: datetime,
) -> Dict[str, Any]:
    """
    Apply all matched rules to the state.
    
    Args:
        state: State to mutate
        matched_rules: List of matched rules (in order)
        now: Current timestamp
    
    Returns:
        Combined mutation result
    """
    combined: Dict[str, Any] = {
        "state_changed": False,
        "new_state": None,
        "rules_applied": [],
    }
    
    for rule in matched_rules:
        result = apply_rule_mutation(state, rule, now)
        
        if result["state_changed"]:
            combined["state_changed"] = True
            combined["new_state"] = result["new_state"]
        
        combined["rules_applied"].append({
            "rule_id": rule.id,
            **result,
        })
    
    return combined
