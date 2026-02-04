"""
Configuration Validator — Check adapter and system configuration.

This module validates that all required environment variables and
configuration are present before attempting to use adapters.

## Usage

    from src.config.validator import ConfigValidator

    validator = ConfigValidator()
    status = validator.validate_all()
    
    for adapter, result in status.items():
        if not result.configured:
            print(f"{adapter}: Missing {result.missing}")
            print(f"  → {result.guidance}")
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ConfigStatus:
    """Status of a configuration check."""
    
    adapter: str
    configured: bool
    missing: List[str] = field(default_factory=list)
    present: List[str] = field(default_factory=list)
    guidance: Optional[str] = None
    mode: str = "unknown"  # "real", "mock", "disabled"
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for logging."""
        return {
            "adapter": self.adapter,
            "configured": self.configured,
            "mode": self.mode,
            "missing": self.missing,
            "guidance": self.guidance,
        }


# Adapter configuration requirements
ADAPTER_REQUIREMENTS = {
    "email": {
        "required": ["RESEND_API_KEY"],
        "optional": ["RESEND_FROM_EMAIL"],
        "guidance": "Get API key from https://resend.com/api-keys",
        "docs": "docs/adapters/email.md",
    },
    "sms": {
        "required": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"],
        "optional": [],
        "guidance": "Get credentials from https://console.twilio.com",
        "docs": "docs/adapters/sms.md",
    },
    "webhook": {
        "required": [],  # URLs come from state routing
        "optional": ["WEBHOOK_TIMEOUT"],
        "guidance": "Configure webhook URLs in state.json integrations.routing.observer_webhooks",
        "docs": "docs/adapters/webhook.md",
    },
    "github_surface": {
        "required": ["GITHUB_TOKEN"],
        "optional": ["GITHUB_REPOSITORY"],
        "guidance": "Create a personal access token at https://github.com/settings/tokens",
        "docs": "docs/adapters/github.md",
    },
    "persistence_api": {
        "required": ["PERSISTENCE_API_URL"],
        "optional": ["PERSISTENCE_API_KEY", "PERSISTENCE_API_TIMEOUT"],
        "guidance": "Set URL of your persistence API endpoint",
        "docs": "docs/adapters/persistence.md",
    },
    "article_publish": {
        "required": [],  # Uses local site generator
        "optional": [],
        "guidance": "No external configuration required",
        "docs": "docs/site-generation.md",
    },
    "x": {
        "required": ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"],
        "optional": [],
        "guidance": "Create app at https://developer.twitter.com/en/portal",
        "docs": "docs/adapters/x.md",
    },
    "reddit": {
        "required": ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USERNAME", "REDDIT_PASSWORD"],
        "optional": [],
        "guidance": "Create app at https://www.reddit.com/prefs/apps",
        "docs": "docs/adapters/reddit.md",
    },
}


class ConfigValidator:
    """
    Validate adapter and system configuration.
    
    Checks environment variables and provides guidance for missing config.
    """
    
    def __init__(self):
        self.requirements = ADAPTER_REQUIREMENTS
    
    def validate_adapter(self, adapter_name: str) -> ConfigStatus:
        """
        Check if an adapter is properly configured.
        
        Args:
            adapter_name: Name of the adapter to check
        
        Returns:
            ConfigStatus with details about configuration state
        """
        if adapter_name not in self.requirements:
            return ConfigStatus(
                adapter=adapter_name,
                configured=False,
                mode="unknown",
                guidance=f"Unknown adapter: {adapter_name}",
            )
        
        reqs = self.requirements[adapter_name]
        required = reqs.get("required", [])
        optional = reqs.get("optional", [])
        guidance = reqs.get("guidance", "")
        
        missing = []
        present = []
        
        # Check required vars
        for var in required:
            if os.environ.get(var):
                present.append(var)
            else:
                missing.append(var)
        
        # Check optional vars
        for var in optional:
            if os.environ.get(var):
                present.append(var)
        
        # Check if mock mode
        mock_mode = os.environ.get("ADAPTER_MOCK_MODE", "false").lower() == "true"
        
        if missing:
            mode = "mock" if mock_mode else "disabled"
            return ConfigStatus(
                adapter=adapter_name,
                configured=False,
                missing=missing,
                present=present,
                mode=mode,
                guidance=guidance,
            )
        
        return ConfigStatus(
            adapter=adapter_name,
            configured=True,
            present=present,
            mode="mock" if mock_mode else "real",
        )
    
    def validate_all(self) -> Dict[str, ConfigStatus]:
        """
        Validate all known adapters.
        
        Returns:
            Dictionary mapping adapter name to ConfigStatus
        """
        results = {}
        for adapter_name in self.requirements:
            results[adapter_name] = self.validate_adapter(adapter_name)
        return results
    
    def log_status(self) -> None:
        """Log configuration status for all adapters."""
        results = self.validate_all()
        
        configured = []
        missing = []
        
        for name, status in results.items():
            if status.configured:
                configured.append(name)
                logger.info(
                    f"✓ {name}: configured ({status.mode})",
                    extra={"adapter": name, "mode": status.mode}
                )
            else:
                missing.append(name)
                logger.warning(
                    f"✗ {name}: not configured (missing: {', '.join(status.missing)})",
                    extra={
                        "adapter": name,
                        "missing": status.missing,
                        "guidance": status.guidance,
                    }
                )
        
        logger.info(
            f"Adapter summary: {len(configured)} configured, {len(missing)} not configured"
        )
    
    def get_setup_guide(self) -> str:
        """Generate a setup guide for missing configuration."""
        results = self.validate_all()
        
        lines = [
            "# Configuration Setup Guide",
            "",
            "The following adapters need configuration:",
            "",
        ]
        
        for name, status in results.items():
            if not status.configured and status.missing:
                lines.append(f"## {name}")
                lines.append("")
                lines.append("**Missing environment variables:**")
                for var in status.missing:
                    lines.append(f"- `{var}`")
                lines.append("")
                if status.guidance:
                    lines.append(f"**Setup:** {status.guidance}")
                    lines.append("")
        
        return "\n".join(lines)


def check_config_on_startup() -> None:
    """Run configuration check at startup (call from main)."""
    validator = ConfigValidator()
    validator.log_status()
