"""
Tests for the Configuration Validator.
"""

import pytest
from unittest.mock import patch
import os

from src.config.validator import (
    ConfigValidator,
    ConfigStatus,
    ADAPTER_REQUIREMENTS,
    check_config_on_startup,
)


class TestConfigStatus:
    """Tests for ConfigStatus dataclass."""
    
    def test_status_creation(self):
        """Test creating a ConfigStatus."""
        status = ConfigStatus(
            adapter="email",
            configured=True,
            mode="real",
        )
        assert status.adapter == "email"
        assert status.configured is True
        assert status.mode == "real"
    
    def test_status_with_missing(self):
        """Test status with missing variables."""
        status = ConfigStatus(
            adapter="sms",
            configured=False,
            missing=["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"],
            mode="disabled",
            guidance="Get credentials from Twilio",
        )
        assert len(status.missing) == 2
        assert "TWILIO_ACCOUNT_SID" in status.missing
    
    def test_to_dict(self):
        """Test converting status to dictionary."""
        status = ConfigStatus(
            adapter="email",
            configured=True,
            present=["RESEND_API_KEY"],
            mode="real",
        )
        d = status.to_dict()
        
        assert d["adapter"] == "email"
        assert d["configured"] is True
        assert d["mode"] == "real"


class TestAdapterRequirements:
    """Tests for ADAPTER_REQUIREMENTS configuration."""
    
    def test_all_adapters_defined(self):
        """Test all expected adapters have requirements."""
        expected = ["email", "sms", "webhook", "github_surface", 
                    "persistence_api", "article_publish", "x", "reddit"]
        for adapter in expected:
            assert adapter in ADAPTER_REQUIREMENTS
    
    def test_email_requirements(self):
        """Test email adapter requirements."""
        reqs = ADAPTER_REQUIREMENTS["email"]
        assert "RESEND_API_KEY" in reqs["required"]
        assert "guidance" in reqs
    
    def test_sms_requirements(self):
        """Test SMS adapter requirements."""
        reqs = ADAPTER_REQUIREMENTS["sms"]
        assert "TWILIO_ACCOUNT_SID" in reqs["required"]
        assert "TWILIO_AUTH_TOKEN" in reqs["required"]
        assert "TWILIO_FROM_NUMBER" in reqs["required"]
    
    def test_x_requirements(self):
        """Test X adapter requirements."""
        reqs = ADAPTER_REQUIREMENTS["x"]
        assert "X_API_KEY" in reqs["required"]
        assert "X_API_SECRET" in reqs["required"]
        assert "X_ACCESS_TOKEN" in reqs["required"]
        assert "X_ACCESS_SECRET" in reqs["required"]
    
    def test_reddit_requirements(self):
        """Test Reddit adapter requirements."""
        reqs = ADAPTER_REQUIREMENTS["reddit"]
        assert "REDDIT_CLIENT_ID" in reqs["required"]
        assert "REDDIT_CLIENT_SECRET" in reqs["required"]
        assert "REDDIT_USERNAME" in reqs["required"]
        assert "REDDIT_PASSWORD" in reqs["required"]
    
    def test_webhook_no_required(self):
        """Test webhook has no required vars (URLs from state)."""
        reqs = ADAPTER_REQUIREMENTS["webhook"]
        assert reqs["required"] == []
    
    def test_article_publish_no_required(self):
        """Test article_publish has no required vars."""
        reqs = ADAPTER_REQUIREMENTS["article_publish"]
        assert reqs["required"] == []


class TestConfigValidator:
    """Tests for ConfigValidator."""
    
    def test_validate_unknown_adapter(self):
        """Test validating unknown adapter."""
        validator = ConfigValidator()
        status = validator.validate_adapter("unknown_adapter")
        
        assert status.configured is False
        assert status.mode == "unknown"
        assert "Unknown adapter" in status.guidance
    
    def test_validate_adapter_all_present(self):
        """Test adapter with all required vars present."""
        with patch.dict(os.environ, {
            "RESEND_API_KEY": "test_key",
            "ADAPTER_MOCK_MODE": "false",
        }, clear=True):
            validator = ConfigValidator()
            status = validator.validate_adapter("email")
            
            assert status.configured is True
            assert status.mode == "real"
            assert "RESEND_API_KEY" in status.present
    
    def test_validate_adapter_missing_required(self):
        """Test adapter with missing required vars."""
        with patch.dict(os.environ, {}, clear=True):
            validator = ConfigValidator()
            status = validator.validate_adapter("email")
            
            assert status.configured is False
            assert "RESEND_API_KEY" in status.missing
    
    def test_validate_adapter_mock_mode(self):
        """Test adapter in mock mode."""
        with patch.dict(os.environ, {
            "RESEND_API_KEY": "test_key",
            "ADAPTER_MOCK_MODE": "true",
        }):
            validator = ConfigValidator()
            status = validator.validate_adapter("email")
            
            assert status.configured is True
            assert status.mode == "mock"
    
    def test_validate_adapter_optional_present(self):
        """Test optional vars are tracked."""
        with patch.dict(os.environ, {
            "RESEND_API_KEY": "test_key",
            "RESEND_FROM_EMAIL": "test@example.com",
        }, clear=True):
            validator = ConfigValidator()
            status = validator.validate_adapter("email")
            
            assert "RESEND_API_KEY" in status.present
            assert "RESEND_FROM_EMAIL" in status.present
    
    def test_validate_adapter_no_required(self):
        """Test adapter with no required vars is configured."""
        with patch.dict(os.environ, {"ADAPTER_MOCK_MODE": "false"}, clear=True):
            validator = ConfigValidator()
            status = validator.validate_adapter("webhook")
            
            assert status.configured is True
            assert status.mode == "real"
    
    def test_validate_all(self):
        """Test validate_all returns all adapters."""
        validator = ConfigValidator()
        results = validator.validate_all()
        
        assert len(results) == len(ADAPTER_REQUIREMENTS)
        assert "email" in results
        assert "sms" in results
        assert "x" in results
    
    def test_validate_sms_partial(self):
        """Test SMS with partial credentials."""
        with patch.dict(os.environ, {
            "TWILIO_ACCOUNT_SID": "ACtest",
            # Missing AUTH_TOKEN and FROM_NUMBER
        }, clear=True):
            validator = ConfigValidator()
            status = validator.validate_adapter("sms")
            
            assert status.configured is False
            assert "TWILIO_AUTH_TOKEN" in status.missing
            assert "TWILIO_FROM_NUMBER" in status.missing
            assert "TWILIO_ACCOUNT_SID" in status.present
    
    def test_validate_x_complete(self):
        """Test X adapter with complete credentials."""
        with patch.dict(os.environ, {
            "X_API_KEY": "key",
            "X_API_SECRET": "secret",
            "X_ACCESS_TOKEN": "token",
            "X_ACCESS_SECRET": "secret",
            "ADAPTER_MOCK_MODE": "false",
        }, clear=True):
            validator = ConfigValidator()
            status = validator.validate_adapter("x")
            
            assert status.configured is True
            assert status.mode == "real"
            assert len(status.missing) == 0


class TestSetupGuide:
    """Tests for setup guide generation."""
    
    def test_get_setup_guide_structure(self):
        """Test setup guide has correct structure."""
        with patch.dict(os.environ, {}, clear=True):
            validator = ConfigValidator()
            guide = validator.get_setup_guide()
            
            assert "# Configuration Setup Guide" in guide
            assert "**Missing environment variables:**" in guide
    
    def test_get_setup_guide_includes_missing(self):
        """Test setup guide includes missing adapters."""
        with patch.dict(os.environ, {
            "RESEND_API_KEY": "test",  # Email configured
            # SMS not configured
        }, clear=True):
            validator = ConfigValidator()
            guide = validator.get_setup_guide()
            
            assert "## sms" in guide
            assert "TWILIO_ACCOUNT_SID" in guide
    
    def test_get_setup_guide_includes_guidance(self):
        """Test setup guide includes guidance links."""
        with patch.dict(os.environ, {}, clear=True):
            validator = ConfigValidator()
            guide = validator.get_setup_guide()
            
            assert "https://resend.com" in guide or "resend.com" in guide.lower()


class TestStartupCheck:
    """Tests for startup configuration check."""
    
    def test_check_config_on_startup_runs(self):
        """Test startup check doesn't crash."""
        # Just verify it runs without exception
        with patch.dict(os.environ, {}, clear=True):
            check_config_on_startup()
    
    def test_log_status_runs(self):
        """Test log_status doesn't crash."""
        with patch.dict(os.environ, {
            "RESEND_API_KEY": "test",
        }, clear=True):
            validator = ConfigValidator()
            validator.log_status()  # Should not raise
