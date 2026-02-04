"""
State File Persistence — JSON state backend.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..models.state import State


def load_state(path: Path) -> State:
    """
    Load state from a JSON file.
    
    Args:
        path: Path to the state file
    
    Returns:
        Parsed State object
    
    Raises:
        FileNotFoundError: If the state file doesn't exist
        ValidationError: If the state file is invalid
    """
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return State(**data)


def save_state(state: State, path: Path) -> None:
    """
    Save state to a JSON file.
    
    Uses atomic write (write to temp, then rename) to prevent corruption.
    
    Args:
        state: State object to save
        path: Path to write the state file
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write to temp file first for atomicity
    temp_path = path.with_suffix(".tmp")
    
    with temp_path.open("w", encoding="utf-8") as f:
        json.dump(state.model_dump(), f, indent=4)
        f.write("\n")  # Trailing newline
    
    # Atomic rename
    temp_path.rename(path)
