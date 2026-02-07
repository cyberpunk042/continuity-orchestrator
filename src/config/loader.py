"""
Config Loader — Load configuration from master key or individual env vars.

Supports two modes:
1. Master JSON key: Single CONTINUITY_CONFIG env var with all credentials
2. Individual keys: Separate env vars for each adapter (fallback)

## Usage

    # Option 1: Master config (one GitHub secret)
    export CONTINUITY_CONFIG='{"resend_api_key": "re_xxx", "twilio_account_sid": "ACxxx", ...}'
    
    # Option 2: Individual keys (multiple GitHub secrets)
    export RESEND_API_KEY="re_xxx"
    export TWILIO_ACCOUNT_SID="ACxxx"

The loader tries master config first, then falls back to individual keys.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class AdapterCredentials:
    """All adapter credentials in one place."""
    
    # Email (Resend)
    resend_api_key: Optional[str] = None
    resend_from_email: Optional[str] = None
    
    # SMS (Twilio)
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_from_number: Optional[str] = None
    
    # X (Twitter)
    x_api_key: Optional[str] = None
    x_api_secret: Optional[str] = None
    x_access_token: Optional[str] = None
    x_access_secret: Optional[str] = None
    
    # Reddit
    reddit_client_id: Optional[str] = None
    reddit_client_secret: Optional[str] = None
    reddit_username: Optional[str] = None
    reddit_password: Optional[str] = None
    
    # GitHub
    github_token: Optional[str] = None
    github_repository: Optional[str] = None
    
    # Persistence API
    persistence_api_url: Optional[str] = None
    persistence_api_key: Optional[str] = None
    
    # Renewal
    renewal_secret: Optional[str] = None
    
    # Project config (not adapter credentials, but needed in CI via master secret)
    project_name: Optional[str] = None
    operator_email: Optional[str] = None
    operator_sms: Optional[str] = None
    
    def has_email(self) -> bool:
        return bool(self.resend_api_key)
    
    def has_sms(self) -> bool:
        return all([
            self.twilio_account_sid,
            self.twilio_auth_token,
            self.twilio_from_number,
        ])
    
    def has_x(self) -> bool:
        return all([
            self.x_api_key,
            self.x_api_secret,
            self.x_access_token,
            self.x_access_secret,
        ])
    
    def has_reddit(self) -> bool:
        return all([
            self.reddit_client_id,
            self.reddit_client_secret,
            self.reddit_username,
            self.reddit_password,
        ])
    
    def has_github(self) -> bool:
        return bool(self.github_token)
    
    def has_persistence(self) -> bool:
        return bool(self.persistence_api_url)
    
    def to_env_dict(self) -> Dict[str, str]:
        """Convert to environment variable format."""
        mapping = {
            "RESEND_API_KEY": self.resend_api_key,
            "RESEND_FROM_EMAIL": self.resend_from_email,
            "TWILIO_ACCOUNT_SID": self.twilio_account_sid,
            "TWILIO_AUTH_TOKEN": self.twilio_auth_token,
            "TWILIO_FROM_NUMBER": self.twilio_from_number,
            "X_API_KEY": self.x_api_key,
            "X_API_SECRET": self.x_api_secret,
            "X_ACCESS_TOKEN": self.x_access_token,
            "X_ACCESS_SECRET": self.x_access_secret,
            "REDDIT_CLIENT_ID": self.reddit_client_id,
            "REDDIT_CLIENT_SECRET": self.reddit_client_secret,
            "REDDIT_USERNAME": self.reddit_username,
            "REDDIT_PASSWORD": self.reddit_password,
            "GITHUB_TOKEN": self.github_token,
            "GITHUB_REPOSITORY": self.github_repository,
            "PERSISTENCE_API_URL": self.persistence_api_url,
            "PERSISTENCE_API_KEY": self.persistence_api_key,
            "RENEWAL_SECRET": self.renewal_secret,
            "PROJECT_NAME": self.project_name,
            "OPERATOR_EMAIL": self.operator_email,
            "OPERATOR_SMS": self.operator_sms,
        }
        return {k: v for k, v in mapping.items() if v}
    
    def apply_to_env(self) -> None:
        """
        Apply credentials to os.environ.
        
        This allows adapters to read from standard env vars
        even when loaded from master config.
        """
        for key, value in self.to_env_dict().items():
            if value and not os.environ.get(key):
                os.environ[key] = value


def load_config() -> AdapterCredentials:
    """
    Load configuration from master key or individual env vars.
    
    Priority:
    1. CONTINUITY_CONFIG (master JSON)
    2. Individual environment variables
    
    Returns:
        AdapterCredentials with all available credentials
    """
    creds = AdapterCredentials()
    
    # Try master config first
    master_config = os.environ.get("CONTINUITY_CONFIG")
    if master_config:
        try:
            data = json.loads(master_config)
            creds = _parse_master_config(data)
            logger.info("Loaded configuration from CONTINUITY_CONFIG")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid CONTINUITY_CONFIG JSON: {e}")
        except Exception as e:
            logger.error(f"Failed to parse CONTINUITY_CONFIG: {e}")
    
    # Fall back to / override with individual env vars
    creds = _load_individual_vars(creds)
    
    return creds


def _parse_master_config(data: Dict[str, Any]) -> AdapterCredentials:
    """Parse master config JSON into credentials."""
    return AdapterCredentials(
        # Email
        resend_api_key=data.get("resend_api_key") or data.get("RESEND_API_KEY"),
        resend_from_email=data.get("resend_from_email") or data.get("RESEND_FROM_EMAIL"),
        
        # SMS
        twilio_account_sid=data.get("twilio_account_sid") or data.get("TWILIO_ACCOUNT_SID"),
        twilio_auth_token=data.get("twilio_auth_token") or data.get("TWILIO_AUTH_TOKEN"),
        twilio_from_number=data.get("twilio_from_number") or data.get("TWILIO_FROM_NUMBER"),
        
        # X
        x_api_key=data.get("x_api_key") or data.get("X_API_KEY"),
        x_api_secret=data.get("x_api_secret") or data.get("X_API_SECRET"),
        x_access_token=data.get("x_access_token") or data.get("X_ACCESS_TOKEN"),
        x_access_secret=data.get("x_access_secret") or data.get("X_ACCESS_SECRET"),
        
        # Reddit
        reddit_client_id=data.get("reddit_client_id") or data.get("REDDIT_CLIENT_ID"),
        reddit_client_secret=data.get("reddit_client_secret") or data.get("REDDIT_CLIENT_SECRET"),
        reddit_username=data.get("reddit_username") or data.get("REDDIT_USERNAME"),
        reddit_password=data.get("reddit_password") or data.get("REDDIT_PASSWORD"),
        
        # GitHub
        github_token=data.get("github_token") or data.get("GITHUB_TOKEN"),
        github_repository=data.get("github_repository") or data.get("GITHUB_REPOSITORY"),
        
        # Persistence
        persistence_api_url=data.get("persistence_api_url") or data.get("PERSISTENCE_API_URL"),
        persistence_api_key=data.get("persistence_api_key") or data.get("PERSISTENCE_API_KEY"),
        
        # Renewal
        renewal_secret=data.get("renewal_secret") or data.get("RENEWAL_SECRET"),
        
        # Project config
        project_name=data.get("project_name") or data.get("PROJECT_NAME"),
        operator_email=data.get("operator_email") or data.get("OPERATOR_EMAIL"),
        operator_sms=data.get("operator_sms") or data.get("OPERATOR_SMS"),
    )


def _load_individual_vars(existing: AdapterCredentials) -> AdapterCredentials:
    """Load from individual env vars, filling in missing values."""
    return AdapterCredentials(
        resend_api_key=existing.resend_api_key or os.environ.get("RESEND_API_KEY"),
        resend_from_email=existing.resend_from_email or os.environ.get("RESEND_FROM_EMAIL"),
        twilio_account_sid=existing.twilio_account_sid or os.environ.get("TWILIO_ACCOUNT_SID"),
        twilio_auth_token=existing.twilio_auth_token or os.environ.get("TWILIO_AUTH_TOKEN"),
        twilio_from_number=existing.twilio_from_number or os.environ.get("TWILIO_FROM_NUMBER"),
        x_api_key=existing.x_api_key or os.environ.get("X_API_KEY"),
        x_api_secret=existing.x_api_secret or os.environ.get("X_API_SECRET"),
        x_access_token=existing.x_access_token or os.environ.get("X_ACCESS_TOKEN"),
        x_access_secret=existing.x_access_secret or os.environ.get("X_ACCESS_SECRET"),
        reddit_client_id=existing.reddit_client_id or os.environ.get("REDDIT_CLIENT_ID"),
        reddit_client_secret=existing.reddit_client_secret or os.environ.get("REDDIT_CLIENT_SECRET"),
        reddit_username=existing.reddit_username or os.environ.get("REDDIT_USERNAME"),
        reddit_password=existing.reddit_password or os.environ.get("REDDIT_PASSWORD"),
        github_token=existing.github_token or os.environ.get("GITHUB_TOKEN"),
        github_repository=existing.github_repository or os.environ.get("GITHUB_REPOSITORY"),
        persistence_api_url=existing.persistence_api_url or os.environ.get("PERSISTENCE_API_URL"),
        persistence_api_key=existing.persistence_api_key or os.environ.get("PERSISTENCE_API_KEY"),
        renewal_secret=existing.renewal_secret or os.environ.get("RENEWAL_SECRET"),
        project_name=existing.project_name or os.environ.get("PROJECT_NAME"),
        operator_email=existing.operator_email or os.environ.get("OPERATOR_EMAIL"),
        operator_sms=existing.operator_sms or os.environ.get("OPERATOR_SMS"),
    )


def generate_master_config_template() -> str:
    """Generate a template for CONTINUITY_CONFIG."""
    template = {
        "# Email (Resend) - https://resend.com/api-keys": "",
        "resend_api_key": "re_xxxxx",
        "resend_from_email": "noreply@yourdomain.com",
        
        "# SMS (Twilio) - https://console.twilio.com": "",
        "twilio_account_sid": "ACxxxxx",
        "twilio_auth_token": "xxxxx",
        "twilio_from_number": "+15551234567",
        
        "# X (Twitter) - https://developer.twitter.com": "",
        "x_api_key": "xxxxx",
        "x_api_secret": "xxxxx",
        "x_access_token": "xxxxx",
        "x_access_secret": "xxxxx",
        
        "# Reddit - https://www.reddit.com/prefs/apps": "",
        "reddit_client_id": "xxxxx",
        "reddit_client_secret": "xxxxx",
        "reddit_username": "xxxxx",
        "reddit_password": "xxxxx",
        
        "# GitHub - https://github.com/settings/tokens": "",
        "github_token": "ghp_xxxxx",
        "github_repository": "owner/repo",
        
        "# Persistence API (optional)": "",
        "persistence_api_url": "",
        "persistence_api_key": "",
        
        "# Renewal": "",
        "renewal_secret": "your-secret-renewal-code",
    }
    
    # Clean template (remove comments for actual JSON)
    clean = {k: v for k, v in template.items() if not k.startswith("#")}
    return json.dumps(clean, indent=2)


# Global config instance (loaded on first access)
_config: Optional[AdapterCredentials] = None


def get_config() -> AdapterCredentials:
    """Get the global configuration (loads on first access)."""
    global _config
    if _config is None:
        _config = load_config()
        _config.apply_to_env()
    return _config


def init_config() -> AdapterCredentials:
    """Initialize and apply configuration early."""
    return get_config()
