"""
Logging Configuration — Structured logging setup.

Provides consistent logging across all modules with:
- JSON output for production (machine-readable)
- Human-readable output for development
- Configurable log levels

## Environment Variables

- LOG_LEVEL: DEBUG, INFO, WARNING, ERROR (default: INFO)
- LOG_FORMAT: json, text (default: text)

## Usage

    from src.logging_config import setup_logging
    
    setup_logging()  # Call once at startup
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict


class JSONFormatter(logging.Formatter):
    """
    JSON log formatter for structured logging.
    
    Output format:
    {"ts": "...", "level": "...", "logger": "...", "message": "...", ...}
    """
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add extra fields
        if hasattr(record, "tick_id"):
            log_entry["tick_id"] = record.tick_id
        if hasattr(record, "state_id"):
            log_entry["state_id"] = record.state_id
        if hasattr(record, "action_id"):
            log_entry["action_id"] = record.action_id
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_entry)


class HumanFormatter(logging.Formatter):
    """
    Human-readable log formatter for development.
    
    Output format:
    12:34:56 INFO  [module] Message
    """
    
    COLORS = {
        "DEBUG": "\033[36m",    # Cyan
        "INFO": "\033[32m",     # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",    # Red
        "CRITICAL": "\033[35m", # Magenta
    }
    RESET = "\033[0m"
    
    def format(self, record: logging.LogRecord) -> str:
        # Time without date
        time_str = datetime.now().strftime("%H:%M:%S")
        
        # Colored level (if terminal supports it)
        level = record.levelname
        if sys.stderr.isatty():
            color = self.COLORS.get(level, "")
            level = f"{color}{level:7}{self.RESET}"
        else:
            level = f"{level:7}"
        
        # Short module name
        module = record.name.split(".")[-1][:15]
        
        # Format message
        msg = record.getMessage()
        
        return f"{time_str} {level} [{module:15}] {msg}"


def setup_logging(
    level: str | None = None,
    format_type: str | None = None,
) -> None:
    """
    Configure logging for the application.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR). 
               Defaults to LOG_LEVEL env var or INFO.
        format_type: Output format (json, text).
                     Defaults to LOG_FORMAT env var or text.
    """
    # Get configuration from environment or arguments
    log_level = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    log_format = (format_type or os.environ.get("LOG_FORMAT", "text")).lower()
    
    # Convert level string to constant
    numeric_level = getattr(logging, log_level, logging.INFO)
    
    # Create formatter
    formatter: logging.Formatter
    if log_format == "json":
        formatter = JSONFormatter()
    else:
        formatter = HumanFormatter()
    
    # Configure root logger
    root = logging.getLogger()
    root.setLevel(numeric_level)
    
    # Remove existing handlers
    root.handlers.clear()
    
    # Add stderr handler
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    handler.setLevel(numeric_level)
    root.addHandler(handler)
    
    # Suppress noisy loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    
    # Log the configuration
    logging.getLogger(__name__).debug(
        f"Logging configured: level={log_level}, format={log_format}"
    )


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the given name.
    
    Use this instead of logging.getLogger() for consistency.
    
    Args:
        name: Logger name (typically __name__)
    
    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)
