"""
Policy Loader — Load and validate policy YAML files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from .models import Plan, Policy, RulesPolicy, StatesPolicy


def load_yaml(path: Path) -> Dict[str, Any]:
    """Load a YAML file and return its contents."""
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_states(policy_dir: Path) -> StatesPolicy:
    """Load states.yaml."""
    path = policy_dir / "states.yaml"
    data = load_yaml(path)
    return StatesPolicy(**data)


def load_rules(policy_dir: Path) -> RulesPolicy:
    """Load rules.yaml."""
    path = policy_dir / "rules.yaml"
    data = load_yaml(path)
    return RulesPolicy(**data)


def load_plan(policy_dir: Path, plan_id: str = "default") -> Plan:
    """Load a plan from the plans directory."""
    plans_dir = policy_dir / "plans"
    
    # Try YAML first, then JSON
    yaml_path = plans_dir / f"{plan_id}.yaml"
    
    if yaml_path.exists():
        data = load_yaml(yaml_path)
        return Plan(**data)
    
    raise FileNotFoundError(f"Plan '{plan_id}' not found in {plans_dir}")


def load_policy(policy_dir: Path, plan_id: str = "default") -> Policy:
    """
    Load all policy files from a directory.
    
    Args:
        policy_dir: Path to the policy directory
        plan_id: ID of the plan to load (default: "default")
    
    Returns:
        Combined Policy object
    """
    policy_path = Path(policy_dir)
    
    states = load_states(policy_path)
    rules = load_rules(policy_path)
    plan = load_plan(policy_path, plan_id)
    
    return Policy(
        states=states,
        rules=rules,
        plan=plan,
    )
