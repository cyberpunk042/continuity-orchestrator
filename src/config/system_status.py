"""
System Status — Comprehensive system and configuration status.

This module provides a unified view of:
- Adapter configuration status
- Tool availability (gh, docker)
- System state (stage, deadline)
- Secrets status (set/unset, masked values)

Used by:
- CLI: `python -m src.main config-status`
- Web Admin: GET /api/status
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _lazy_read_env(env_path: Path) -> Dict[str, str]:
    """Read .env file lazily at request time (vault may unlock after startup)."""
    result: Dict[str, str] = {}
    if not env_path.exists():
        return result
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip().strip("'\"")
    except Exception:
        pass
    return result


@dataclass
class SecretStatus:
    """Status of a single secret/environment variable."""
    name: str
    set: bool
    masked: Optional[str] = None
    required_for: List[str] = field(default_factory=list)
    guidance: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "set": self.set,
            "masked": self.masked,
            "required_for": self.required_for,
            "guidance": self.guidance,
        }


@dataclass
class ToolStatus:
    """Status of an external tool."""
    name: str
    installed: bool
    version: Optional[str] = None
    path: Optional[str] = None
    install_hint: Optional[str] = None
    authenticated: Optional[bool] = None
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "installed": self.installed,
            "version": self.version,
            "path": self.path,
            "install_hint": self.install_hint,
            "authenticated": self.authenticated,
        }


@dataclass
class AdapterStatus:
    """Status of an adapter."""
    name: str
    configured: bool
    mode: str  # "real", "mock", "disabled"
    missing: List[str] = field(default_factory=list)
    last_test: Optional[str] = None
    last_test_success: Optional[bool] = None
    guidance: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "configured": self.configured,
            "mode": self.mode,
            "missing": self.missing,
            "last_test": self.last_test,
            "last_test_success": self.last_test_success,
            "guidance": self.guidance,
        }


@dataclass
class SystemStatus:
    """Complete system status."""
    timestamp: str
    
    # State
    stage: str = "UNKNOWN"
    deadline: Optional[str] = None
    time_to_deadline_minutes: Optional[int] = None
    renewal_count: int = 0
    last_tick: Optional[str] = None
    
    # Release / shadow mode
    release_triggered: bool = False
    release_target_stage: Optional[str] = None
    release_delay_minutes: int = 0
    release_execute_after: Optional[str] = None
    
    # Config
    project_name: str = ""
    operator_email: str = ""
    mock_mode: bool = True
    vault_locked: bool = False
    
    # Components
    adapters: List[AdapterStatus] = field(default_factory=list)
    secrets: List[SecretStatus] = field(default_factory=list)
    tools: List[ToolStatus] = field(default_factory=list)
    
    # Health
    state_file_exists: bool = False
    policy_valid: bool = False
    
    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "state": {
                "stage": self.stage,
                "deadline": self.deadline,
                "time_to_deadline_minutes": self.time_to_deadline_minutes,
                "renewal_count": self.renewal_count,
                "last_tick": self.last_tick,
                "release_triggered": self.release_triggered,
                "release_target_stage": self.release_target_stage,
                "release_delay_minutes": self.release_delay_minutes,
                "release_execute_after": self.release_execute_after,
            },
            "config": {
                "project_name": self.project_name,
                "operator_email": self.operator_email,
                "mock_mode": self.mock_mode,
                "vault_locked": self.vault_locked,
            },
            "adapters": [a.to_dict() for a in self.adapters],
            "secrets": [s.to_dict() for s in self.secrets],
            "tools": [t.to_dict() for t in self.tools],
            "health": {
                "state_file_exists": self.state_file_exists,
                "policy_valid": self.policy_valid,
            },
        }


# Secret definitions with metadata
SECRET_DEFINITIONS = {
    # Core
    "PROJECT_NAME": {"required_for": [], "guidance": "Your project name"},
    "OPERATOR_EMAIL": {"required_for": [], "guidance": "Your email for notifications"},
    "ADAPTER_MOCK_MODE": {"required_for": [], "guidance": "Set to 'false' for production"},
    
    # Renewal
    "RENEWAL_SECRET": {"required_for": ["renewal"], "guidance": "Code to extend deadline"},
    "RELEASE_SECRET": {"required_for": ["release"], "guidance": "Code to trigger disclosure"},
    "RENEWAL_TRIGGER_TOKEN": {"required_for": ["web_renewal"], "guidance": "GitHub PAT for one-click renewal"},
    "CONTENT_ENCRYPTION_KEY": {"required_for": ["content_encryption"], "guidance": "Passphrase for encrypting article content (run content-keygen)"},
    
    # Email
    "RESEND_API_KEY": {"required_for": ["email"], "guidance": "Get from https://resend.com/api-keys"},
    "RESEND_FROM_EMAIL": {"required_for": [], "guidance": "Sender email address"},
    
    # SMS
    "TWILIO_ACCOUNT_SID": {"required_for": ["sms"], "guidance": "Get from https://console.twilio.com"},
    "TWILIO_AUTH_TOKEN": {"required_for": ["sms"], "guidance": "Get from https://console.twilio.com"},
    "TWILIO_FROM_NUMBER": {"required_for": ["sms"], "guidance": "Your Twilio phone number"},
    "OPERATOR_SMS": {"required_for": [], "guidance": "Your phone number for SMS alerts"},
    
    # GitHub
    "GITHUB_TOKEN": {"required_for": ["github"], "guidance": "Get from https://github.com/settings/tokens"},
    "GITHUB_REPOSITORY": {"required_for": [], "guidance": "Format: owner/repo"},
    
    # Social
    "X_API_KEY": {"required_for": ["x"], "guidance": "Get from https://developer.twitter.com"},
    "X_API_SECRET": {"required_for": ["x"], "guidance": "Get from https://developer.twitter.com"},
    "X_ACCESS_TOKEN": {"required_for": ["x"], "guidance": "Get from https://developer.twitter.com"},
    "X_ACCESS_SECRET": {"required_for": ["x"], "guidance": "Get from https://developer.twitter.com"},
    
    "REDDIT_CLIENT_ID": {"required_for": ["reddit"], "guidance": "Get from https://www.reddit.com/prefs/apps"},
    "REDDIT_CLIENT_SECRET": {"required_for": ["reddit"], "guidance": "Get from https://www.reddit.com/prefs/apps"},
    "REDDIT_USERNAME": {"required_for": ["reddit"], "guidance": "Your Reddit username"},
    "REDDIT_PASSWORD": {"required_for": ["reddit"], "guidance": "Your Reddit password"},
    
    # Archive (Internet Archive / Wayback Machine)
    "ARCHIVE_ENABLED": {"required_for": [], "guidance": "Enable auto-archiving to archive.org after publish"},
    "ARCHIVE_URL": {"required_for": [], "guidance": "Custom URL for Docker/Cloudflare (optional, defaults to GitHub Pages)"},
    
    # Repo Mirror
    "MIRROR_ENABLED": {"required_for": [], "guidance": "Set to 'true' to enable repo mirroring"},
    "MIRROR_1_REPO": {"required_for": [], "guidance": "Backup repo: backup-user/repo-name"},
    "MIRROR_1_TOKEN": {"required_for": ["mirror"], "guidance": "PAT from backup GitHub account (repo + workflow scopes)"},
    "MIRROR_1_RENEWAL_TRIGGER_TOKEN": {"required_for": [], "guidance": "PAT from backup account with Actions scope (for one-click renewal on mirror)"},
    "MIRROR_RESET_MODE": {"required_for": [], "guidance": "Factory reset cross-repo behavior: leader (default — propagate reset), isolated (protect mirrors), or follower"},

    # Docker Deployment
    "DEPLOY_MODE": {"required_for": [], "guidance": "Deployment method: 'github-pages' (default) or 'docker' (self-hosted with git-sync)"},

    # Docker Git Sync
    "DOCKER_GIT_SYNC_ALPHA": {"required_for": [], "guidance": "Docker sync dominance: 'true' = this Docker is the authority (overrides remote on conflict), 'false' = remote is the authority (default)"},
    "DOCKER_GIT_SYNC_TICK_INTERVAL": {"required_for": [], "guidance": "Seconds between tick runs in Docker git-sync mode (default: 900 = 15min)"},
    "DOCKER_GIT_SYNC_SYNC_INTERVAL": {"required_for": [], "guidance": "Seconds between remote sync checks in Docker git-sync mode (default: 30)"},

    # Cloudflare Tunnel
    "CLOUDFLARE_TUNNEL_TOKEN": {"required_for": ["tunnel"], "guidance": "Token from Cloudflare Zero Trust → Networks → Tunnels. Required for --profile tunnel."},
}


def mask_secret(value: str, show_chars: int = 4) -> str:
    """Mask a secret value, showing only first and last few chars."""
    if not value:
        return ""
    if len(value) <= show_chars * 2:
        return "****"
    return f"{value[:show_chars]}...{value[-show_chars:]}"


def check_tool(name: str) -> ToolStatus:
    """Check if a tool is installed and get its version."""
    
    install_hints = {
        "gh": "Install: https://cli.github.com/",
        "docker": "Install: https://docs.docker.com/get-docker/",
        "git": "Install: https://git-scm.com/downloads",
    }
    
    path = shutil.which(name)
    if not path:
        return ToolStatus(
            name=name,
            installed=False,
            install_hint=install_hints.get(name),
        )
    
    # Get version
    version = None
    try:
        result = subprocess.run(
            [name, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            # Take first line, clean up
            version = result.stdout.strip().split("\n")[0]
    except Exception:
        pass
    
    # Check authentication for gh
    authenticated = None
    if name == "gh":
        try:
            result = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            authenticated = result.returncode == 0
        except Exception:
            authenticated = False
    
    return ToolStatus(
        name=name,
        installed=True,
        version=version,
        path=path,
        authenticated=authenticated,
    )


def get_system_status(
    state_file: Optional[Path] = None,
    policy_dir: Optional[Path] = None,
) -> SystemStatus:
    """
    Gather comprehensive system status.
    
    Args:
        state_file: Path to state file (default: state/current.json)
        policy_dir: Path to policy directory (default: policy/)
    
    Returns:
        SystemStatus with all information
    """
    from .validator import ConfigValidator
    
    # Defaults
    if state_file is None:
        state_file = Path("state/current.json")
    if policy_dir is None:
        policy_dir = Path("policy")
    
    status = SystemStatus(
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    
    # Load state if exists
    state_data: Dict[str, Any] = {}
    if state_file.exists():
        status.state_file_exists = True
        try:
            with open(state_file) as f:
                state_data = json.load(f)
            
            # Read from nested structure (updated state schema)
            escalation = state_data.get("escalation", {})
            timer = state_data.get("timer", {})
            renewal = state_data.get("renewal", {})
            meta = state_data.get("meta", {})
            release = state_data.get("release", {})
            
            status.stage = escalation.get("state", "UNKNOWN")
            status.deadline = timer.get("deadline_iso")
            status.renewal_count = renewal.get("renewal_count", 0)
            status.last_tick = meta.get("updated_at_iso")
            
            # Release / shadow mode info
            status.release_triggered = release.get("triggered", False)
            status.release_target_stage = release.get("target_stage")
            status.release_delay_minutes = release.get("delay_minutes", 0)
            status.release_execute_after = release.get("execute_after_iso")
            
            # Calculate TTD
            if status.deadline:
                try:
                    deadline_dt = datetime.fromisoformat(status.deadline.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)
                    delta = deadline_dt - now
                    status.time_to_deadline_minutes = int(delta.total_seconds() / 60)
                except Exception:
                    pass
            
        except Exception as e:
            logger.warning(f"Failed to load state: {e}")
    
    # Check policy
    rules_file = policy_dir / "rules.yaml"
    status.policy_valid = rules_file.exists()
    
    # Config from env — try lazy .env read when vault is unlocked
    # (When vault is locked, .env doesn't exist, so we fall back gracefully)
    _env_file = state_file.parent.parent / ".env"
    _vault_file = state_file.parent.parent / ".env.vault"
    _env_vars = _lazy_read_env(_env_file)
    status.vault_locked = not _env_file.exists() and _vault_file.exists()
    
    status.project_name = (
        os.environ.get("PROJECT_NAME")
        or _env_vars.get("PROJECT_NAME")
        or (state_data.get("meta", {}).get("project", "") if state_file.exists() else "")
    )
    status.operator_email = (
        os.environ.get("OPERATOR_EMAIL")
        or _env_vars.get("OPERATOR_EMAIL", "")
    )
    _mock_raw = (
        os.environ.get("ADAPTER_MOCK_MODE")
        or _env_vars.get("ADAPTER_MOCK_MODE", "true")
    )
    status.mock_mode = _mock_raw.lower() == "true"
    
    # Check all secrets
    for name, meta in SECRET_DEFINITIONS.items():
        value = os.environ.get(name, "") or _env_vars.get(name, "")
        status.secrets.append(SecretStatus(
            name=name,
            set=bool(value),
            masked=mask_secret(value) if value else None,
            required_for=meta.get("required_for", []),
            guidance=meta.get("guidance"),
        ))
    
    # Check adapters
    validator = ConfigValidator()
    adapter_results = validator.validate_all()
    for name, result in adapter_results.items():
        status.adapters.append(AdapterStatus(
            name=name,
            configured=result.configured,
            mode=result.mode,
            missing=result.missing,
            guidance=result.guidance,
        ))
    
    # Check tools
    for tool in ["gh", "docker", "git"]:
        status.tools.append(check_tool(tool))
    
    return status


def format_status_cli(status: SystemStatus) -> str:
    """Format status for CLI display."""
    lines = []
    
    # Header
    lines.append("")
    lines.append("═" * 60)
    lines.append("              CONTINUITY ORCHESTRATOR STATUS")
    lines.append("═" * 60)
    lines.append("")
    
    # State section
    lines.append("┌─ SYSTEM STATE " + "─" * 44 + "┐")
    
    stage_icon = {"OK": "🟢", "WARNING": "🟡", "CRITICAL": "🟠", "FINAL": "🔴"}.get(status.stage, "⚪")
    lines.append(f"│  Stage: {stage_icon} {status.stage}")
    
    if status.deadline:
        if status.time_to_deadline_minutes is not None:
            if status.time_to_deadline_minutes > 0:
                hours = status.time_to_deadline_minutes // 60
                mins = status.time_to_deadline_minutes % 60
                lines.append(f"│  Deadline: {hours}h {mins}m remaining")
            else:
                lines.append(f"│  Deadline: ⚠️ PASSED")
        else:
            lines.append(f"│  Deadline: {status.deadline}")
    
    if status.last_tick:
        lines.append(f"│  Last tick: {status.last_tick[:19]}")
    
    lines.append(f"│  Mock mode: {'✅ ON (safe)' if status.mock_mode else '⚠️ OFF (live)'}")
    lines.append("└" + "─" * 59 + "┘")
    lines.append("")
    
    # Adapters section
    lines.append("┌─ ADAPTERS " + "─" * 48 + "┐")
    for adapter in status.adapters:
        if adapter.configured:
            if adapter.mode == "real":
                lines.append(f"│  ✅ {adapter.name:<20} ready (live)")
            else:
                lines.append(f"│  ⚠️  {adapter.name:<20} configured (mock)")
        else:
            missing = ", ".join(adapter.missing[:2])
            if len(adapter.missing) > 2:
                missing += "..."
            lines.append(f"│  ❌ {adapter.name:<20} missing: {missing}")
    lines.append("└" + "─" * 59 + "┘")
    lines.append("")
    
    # Secrets section
    lines.append("┌─ SECRETS " + "─" * 49 + "┐")
    set_secrets = [s for s in status.secrets if s.set]
    unset_secrets = [s for s in status.secrets if not s.set and s.required_for]
    
    lines.append(f"│  {len(set_secrets)} set, {len(unset_secrets)} required but missing")
    
    if unset_secrets:
        lines.append("│")
        lines.append("│  Missing required:")
        for secret in unset_secrets[:5]:
            lines.append(f"│    ❌ {secret.name}")
        if len(unset_secrets) > 5:
            lines.append(f"│    ... and {len(unset_secrets) - 5} more")
    
    lines.append("└" + "─" * 59 + "┘")
    lines.append("")
    
    # Tools section
    lines.append("┌─ TOOLS " + "─" * 51 + "┐")
    for tool in status.tools:
        if tool.installed:
            auth_note = ""
            if tool.authenticated is not None:
                auth_note = " (authenticated)" if tool.authenticated else " (not authenticated)"
            lines.append(f"│  ✅ {tool.name:<10} installed{auth_note}")
        else:
            lines.append(f"│  ❌ {tool.name:<10} not installed")
            if tool.install_hint:
                lines.append(f"│     → {tool.install_hint}")
    lines.append("└" + "─" * 59 + "┘")
    lines.append("")
    
    # Footer
    lines.append("─" * 60)
    lines.append("Run './manage.sh' for interactive management")
    lines.append("Run 'python -m src.main config-status --json' for API output")
    lines.append("")
    
    return "\n".join(lines)
