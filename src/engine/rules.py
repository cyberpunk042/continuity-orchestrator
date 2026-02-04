"""
Rule Evaluation — Match policy rules against state.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..models.state import State
from ..policy.models import Rule, RulesPolicy


def get_nested_value(obj: Any, path: str) -> Any:
    """
    Get a nested value from an object using dot notation.
    
    Example: get_nested_value(state, "timer.time_to_deadline_minutes")
    
    Args:
        obj: Object to traverse (can be Pydantic model or dict)
        path: Dot-separated path
    
    Returns:
        Value at path, or None if not found
    """
    # Path aliasing: policy rules may use different names than state
    path_aliases = {
        "time.": "timer.",
        # renewal. and security. match as-is
    }
    
    for alias, replacement in path_aliases.items():
        if path.startswith(alias):
            path = replacement + path[len(alias):]
            break
    
    parts = path.split(".")
    current = obj
    
    for part in parts:
        if current is None:
            return None
        
        if hasattr(current, part):
            current = getattr(current, part)
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    
    return current


def resolve_value(value: Any, constants: Dict[str, int]) -> Any:
    """
    Resolve constant references.
    
    Example: "constants.remind_1_at_minutes" -> 360
    
    Args:
        value: Value that might be a constant reference
        constants: Dictionary of constant values
    
    Returns:
        Resolved value
    """
    if isinstance(value, str) and value.startswith("constants."):
        const_name = value.split(".", 1)[1]
        return constants.get(const_name, value)
    return value


def evaluate_condition(
    key: str,
    expected: Any,
    state: State,
    constants: Dict[str, int],
) -> bool:
    """
    Evaluate a single condition.
    
    Supported operators:
    - state_is: Exact state match
    - state_in: State in list
    - always: Always true
    - field_lte: Less than or equal
    - field_lt: Less than
    - field_gte: Greater than or equal
    - field_gt: Greater than
    - field (no suffix): Equality
    
    Args:
        key: Condition key (may include operator suffix)
        expected: Expected value
        state: Current state
        constants: Rule constants
    
    Returns:
        True if condition matches
    """
    expected = resolve_value(expected, constants)
    
    # Special conditions
    if key == "always":
        return expected is True
    
    if key == "state_is":
        return state.escalation.state == expected
    
    if key == "state_in":
        return state.escalation.state in expected
    
    # Parse operator suffix
    operators = ["_lte", "_lt", "_gte", "_gt"]
    operator: Optional[str] = None
    field_path = key
    
    for op in operators:
        if key.endswith(op):
            operator = op
            field_path = key[:-len(op)]
            break
    
    # Get actual value from state
    actual = get_nested_value(state, field_path)
    
    if actual is None:
        return False
    
    # Compare based on operator
    if operator is None:
        return actual == expected
    elif operator == "_lte":
        return actual <= expected
    elif operator == "_lt":
        return actual < expected
    elif operator == "_gte":
        return actual >= expected
    elif operator == "_gt":
        return actual > expected
    
    return False


def evaluate_rule(rule: Rule, state: State, constants: Dict[str, int]) -> bool:
    """
    Evaluate all conditions of a rule.
    
    All conditions must match (AND logic).
    
    Args:
        rule: Rule to evaluate
        state: Current state
        constants: Rule constants
    
    Returns:
        True if all conditions match
    """
    for key, expected in rule.when.items():
        if not evaluate_condition(key, expected, state, constants):
            return False
    return True


def evaluate_rules(state: State, rules_policy: RulesPolicy) -> List[Rule]:
    """
    Evaluate all rules and return matched rules.
    
    Rules are evaluated in order. A rule with stop=True ends evaluation.
    
    Args:
        state: Current state
        rules_policy: Rules policy with rules and constants
    
    Returns:
        List of matched rules (in order)
    """
    matched: List[Rule] = []
    
    for rule in rules_policy.rules:
        if evaluate_rule(rule, state, rules_policy.constants):
            matched.append(rule)
            if rule.stop:
                break
    
    return matched
