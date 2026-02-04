"""
Validation — Input validation and error handling utilities.

Provides consistent validation patterns across the codebase.

## Usage

    from src.validation import validate_state_file, validate_policy_dir
    
    try:
        validate_state_file(state_path)
        validate_policy_dir(policy_path)
    except ValidationError as e:
        print(f"Validation failed: {e}")
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class ValidationError(Exception):
    """Raised when validation fails."""
    
    def __init__(self, message: str, field: Optional[str] = None, details: Optional[Dict] = None):
        self.message = message
        self.field = field
        self.details = details or {}
        super().__init__(self._format_message())
    
    def _format_message(self) -> str:
        if self.field:
            return f"{self.field}: {self.message}"
        return self.message


class ConfigurationError(Exception):
    """Raised when configuration is missing or invalid."""
    pass


def validate_path_exists(path: Path, description: str = "Path") -> None:
    """Validate that a path exists."""
    if not path.exists():
        raise ValidationError(f"{description} does not exist: {path}")


def validate_file_readable(path: Path, description: str = "File") -> None:
    """Validate that a file exists and is readable."""
    validate_path_exists(path, description)
    
    if not path.is_file():
        raise ValidationError(f"{description} is not a file: {path}")
    
    try:
        path.read_text()
    except PermissionError:
        raise ValidationError(f"{description} is not readable: {path}")
    except Exception as e:
        raise ValidationError(f"{description} cannot be read: {e}")


def validate_json_file(path: Path, description: str = "JSON file") -> Dict[str, Any]:
    """Validate and load a JSON file."""
    validate_file_readable(path, description)
    
    try:
        content = path.read_text()
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise ValidationError(
            f"Invalid JSON in {description}",
            details={"path": str(path), "error": str(e), "line": e.lineno},
        )


def validate_state_file(path: Path) -> Dict[str, Any]:
    """
    Validate a state file.
    
    Checks:
    - File exists and is readable
    - Valid JSON
    - Required top-level keys present
    
    Returns:
        Parsed state data
    
    Raises:
        ValidationError: If validation fails
    """
    data = validate_json_file(path, "State file")
    
    required_keys = ["meta", "mode", "timer", "escalation"]
    missing = [k for k in required_keys if k not in data]
    
    if missing:
        raise ValidationError(
            f"Missing required keys in state file: {missing}",
            details={"path": str(path), "missing_keys": missing},
        )
    
    # Validate meta section
    meta = data.get("meta", {})
    if "state_id" not in meta:
        raise ValidationError("Missing state_id in meta section")
    
    # Validate timer section
    timer = data.get("timer", {})
    if "deadline_iso" not in timer:
        raise ValidationError("Missing deadline_iso in timer section")
    
    return data


def validate_policy_dir(path: Path) -> Dict[str, Path]:
    """
    Validate a policy directory.
    
    Checks:
    - Directory exists
    - Required files are present
    - At least one plan exists
    
    Returns:
        Dict with paths to policy files
    
    Raises:
        ValidationError: If validation fails
    """
    validate_path_exists(path, "Policy directory")
    
    if not path.is_dir():
        raise ValidationError(f"Policy path is not a directory: {path}")
    
    # Required files
    states_file = path / "states.yaml"
    rules_file = path / "rules.yaml"
    plans_dir = path / "plans"
    
    files = {"states": states_file, "rules": rules_file}
    
    for name, file_path in files.items():
        if not file_path.exists():
            raise ValidationError(
                f"Missing required policy file: {name}.yaml",
                details={"path": str(path), "missing_file": str(file_path)},
            )
    
    # Check for at least one plan
    if plans_dir.exists() and plans_dir.is_dir():
        plans = list(plans_dir.glob("*.yaml"))
        if not plans:
            raise ValidationError(
                "No plan files found in plans directory",
                details={"path": str(plans_dir)},
            )
        files["plans"] = plans_dir
        files["default_plan"] = plans[0]
    else:
        raise ValidationError(
            "Plans directory not found",
            details={"path": str(plans_dir)},
        )
    
    return files


def validate_deadline_iso(deadline_iso: str) -> bool:
    """
    Validate an ISO datetime string.
    
    Returns:
        True if valid
    
    Raises:
        ValidationError: If invalid
    """
    from dateutil import parser as date_parser
    
    try:
        date_parser.isoparse(deadline_iso)
        return True
    except (ValueError, TypeError) as e:
        raise ValidationError(
            f"Invalid ISO datetime: {deadline_iso}",
            details={"error": str(e)},
        )


def validate_escalation_state(state: str, valid_states: List[str]) -> bool:
    """
    Validate an escalation state value.
    
    Returns:
        True if valid
    
    Raises:
        ValidationError: If invalid
    """
    if state not in valid_states:
        raise ValidationError(
            f"Invalid escalation state: {state}",
            details={"valid_states": valid_states},
        )
    return True
