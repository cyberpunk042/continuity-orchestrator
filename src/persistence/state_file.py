"""
State File Persistence — JSON state backend.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..models.state import State

logger = logging.getLogger(__name__)


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
    logger.debug(f"Loading state from {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    state = State(**data)
    logger.debug(f"State loaded: stage={state.escalation.state}, project={state.meta.project}")
    return state


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
    logger.info(f"State saved: stage={state.escalation.state} → {path.name}")
