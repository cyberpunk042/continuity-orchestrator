"""
Tests for the Twilio SMS Adapter.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import os

from src.adapters.sms_twilio import TwilioSMSAdapter
from src.adapters.base import ExecutionContext
from src.models.state import (
    State, Meta, Mode, Timer, Renewal, Security,
    Escalation, Actions, Integrations, EnabledAdapters, Routing, Pointers,
)
from src.policy.models import ActionDefinition


@pytest.fixture
def sample_state():
    """Create a sample state for testing."""
    return State(
        meta=Meta(
            schema_version=1,
            project="test-project",
            state_id="S-TEST-001",
            updated_at_iso="2026-02-04T12:00:00Z",
            policy_version=1,
            plan_id="default",
        ),
        mode=Mode(name="renewable_countdown", armed=True),
        timer=Timer(
            deadline_iso="2026-02-05T12:00:00Z",
            grace_minutes=0,
            now_iso="2026-02-04T12:00:00Z",
            time_to_deadline_minutes=1440,
            overdue_minutes=0,
        ),
        renewal=Renewal(
            last_renewal_iso="2026-02-04T12:00:00Z",
            renewed_this_tick=False,
            renewal_count=0,
        ),
        security=Security(
            failed_attempts=0,
            lockout_active=False,
            lockout_until_iso=None,
            max_failed_attempts=3,
            lockout_minutes=60,
        ),
        escalation=Escalation(
            state="REMIND_1",
            state_entered_at_iso="2026-02-04T12:00:00Z",
            last_transition_rule_id=None,
        ),
        actions=Actions(executed={}, last_tick_actions=[]),
        integrations=Integrations(
            enabled_adapters=EnabledAdapters(sms=True),
            routing=Routing(
                operator_email="test@example.com",
                operator_sms="+15551234567",
            ),
        ),
        pointers=Pointers(),
    )


@pytest.fixture
def sample_action():
    """Create a sample action definition."""
    return ActionDefinition(
        id="test_sms_action",
        adapter="sms",
        channel="operator",
        template="reminder_sms",
    )


@pytest.fixture
def execution_context(sample_state, sample_action):
    """Create an execution context."""
    return ExecutionContext(
        state=sample_state,
        action=sample_action,
        tick_id="T-TEST-001",
        template_content="Deadline approaching in 24 hours. Please renew.",
    )


class TestTwilioSMSAdapter:
    """Tests for TwilioSMSAdapter."""
    
    def test_name(self):
        """Test adapter name."""
        adapter = TwilioSMSAdapter()
        assert adapter.name == "sms"
    
    def test_is_enabled_no_credentials(self, execution_context):
        """Test disabled when no Twilio credentials."""
        with patch.dict(os.environ, {}, clear=True):
            adapter = TwilioSMSAdapter()
            assert adapter.is_enabled(execution_context) is False
    
    def test_is_enabled_partial_credentials(self, execution_context):
        """Test disabled with only some credentials."""
        with patch.dict(os.environ, {
            "TWILIO_ACCOUNT_SID": "ACtest123",
            # Missing AUTH_TOKEN and FROM_NUMBER
        }, clear=True):
            adapter = TwilioSMSAdapter()
            assert adapter.is_enabled(execution_context) is False
    
    @patch.dict(os.environ, {
        "TWILIO_ACCOUNT_SID": "ACtest123",
        "TWILIO_AUTH_TOKEN": "test_token",
        "TWILIO_FROM_NUMBER": "+15550001111",
    })
    def test_validate_valid_number(self, execution_context):
        """Test validation passes with valid E.164 number."""
        adapter = TwilioSMSAdapter()
        is_valid, error = adapter.validate(execution_context)
        
        assert is_valid is True
        assert error is None
    
    def test_validate_no_recipient(self, sample_state, sample_action):
        """Test validation fails when no recipient."""
        # Clear the operator_sms
        sample_state.integrations.routing.operator_sms = None
        context = ExecutionContext(
            state=sample_state,
            action=sample_action,
            tick_id="T-TEST-001",
            template_content=None,
        )
        
        adapter = TwilioSMSAdapter()
        is_valid, error = adapter.validate(context)
        
        assert is_valid is False
        assert "No phone number" in error
    
    def test_validate_invalid_number_format(self, sample_state, sample_action):
        """Test validation fails for non-E.164 number."""
        sample_state.integrations.routing.operator_sms = "5551234567"  # No +
        context = ExecutionContext(
            state=sample_state,
            action=sample_action,
            tick_id="T-TEST-001",
            template_content=None,
        )
        
        adapter = TwilioSMSAdapter()
        is_valid, error = adapter.validate(context)
        
        assert is_valid is False
        assert "E.164" in error
    
    def test_build_message_with_template(self, execution_context):
        """Test message building with template content."""
        adapter = TwilioSMSAdapter()
        message = adapter._build_message(execution_context)
        
        assert "Deadline approaching" in message
        assert "renew" in message.lower()
    
    def test_build_message_default(self, sample_state, sample_action):
        """Test default message when no template."""
        context = ExecutionContext(
            state=sample_state,
            action=sample_action,
            tick_id="T-TEST-001",
            template_content=None,
        )
        
        adapter = TwilioSMSAdapter()
        message = adapter._build_message(context)
        
        assert "[REMIND_1]" in message
        assert "Deadline" in message
    
    def test_build_message_overdue(self, sample_state, sample_action):
        """Test overdue message format."""
        sample_state.timer.time_to_deadline_minutes = 0
        sample_state.timer.overdue_minutes = 60
        
        context = ExecutionContext(
            state=sample_state,
            action=sample_action,
            tick_id="T-TEST-001",
            template_content=None,
        )
        
        adapter = TwilioSMSAdapter()
        message = adapter._build_message(context)
        
        assert "OVERDUE" in message
        assert "1h" in message
    
    def test_message_truncation(self, sample_state, sample_action):
        """Test long messages are truncated."""
        long_content = "X" * 600  # Over MAX_CONCAT_LENGTH
        
        context = ExecutionContext(
            state=sample_state,
            action=sample_action,
            tick_id="T-TEST-001",
            template_content=long_content,
        )
        
        adapter = TwilioSMSAdapter()
        message = adapter._build_message(context)
        
        assert len(message) <= adapter.MAX_CONCAT_LENGTH
        assert message.endswith("...")
    
    def test_strip_headers(self):
        """Test markdown headers are stripped."""
        adapter = TwilioSMSAdapter()
        
        content = "# Header\n## Subheader\nActual content here."
        result = adapter._strip_headers(content)
        
        assert "Actual content here" in result
        assert "#" not in result
    
    def test_format_time_minutes(self):
        """Test time formatting for minutes."""
        adapter = TwilioSMSAdapter()
        
        assert adapter._format_time(30) == "30m"
        assert adapter._format_time(59) == "59m"
    
    def test_format_time_hours(self):
        """Test time formatting for hours."""
        adapter = TwilioSMSAdapter()
        
        assert adapter._format_time(60) == "1h"
        assert adapter._format_time(90) == "1h 30m"
        assert adapter._format_time(120) == "2h"
    
    def test_format_time_days(self):
        """Test time formatting for days."""
        adapter = TwilioSMSAdapter()
        
        assert adapter._format_time(1440) == "1d"
        assert adapter._format_time(1500) == "1d 1h"
        assert adapter._format_time(2880) == "2d"
    
    def test_count_segments(self):
        """Test SMS segment counting."""
        adapter = TwilioSMSAdapter()
        
        assert adapter._count_segments("X" * 100) == 1
        assert adapter._count_segments("X" * 160) == 1
        assert adapter._count_segments("X" * 161) == 2
        assert adapter._count_segments("X" * 306) == 2
        assert adapter._count_segments("X" * 307) == 3
    
    @patch("src.adapters.sms_twilio.TwilioClient")
    @patch.dict(os.environ, {
        "TWILIO_ACCOUNT_SID": "ACtest123",
        "TWILIO_AUTH_TOKEN": "test_token",
        "TWILIO_FROM_NUMBER": "+15550001111",
    })
    def test_execute_success(self, mock_client_class, execution_context):
        """Test successful SMS sending."""
        # Mock the Twilio client and message
        mock_client = MagicMock()
        mock_message = Mock()
        mock_message.sid = "SM123456789"
        mock_message.status = "queued"
        mock_client.messages.create.return_value = mock_message
        mock_client_class.return_value = mock_client
        
        # Need to reimport to get the patched version
        from src.adapters.sms_twilio import TwilioSMSAdapter
        adapter = TwilioSMSAdapter()
        adapter._client = mock_client
        
        receipt = adapter.execute(execution_context)
        
        assert receipt.status == "ok"
        assert receipt.delivery_id == "SM123456789"
        assert receipt.adapter == "sms"
        mock_client.messages.create.assert_called_once()
    
    @patch("src.adapters.sms_twilio.TwilioClient")
    @patch.dict(os.environ, {
        "TWILIO_ACCOUNT_SID": "ACtest123",
        "TWILIO_AUTH_TOKEN": "test_token",
        "TWILIO_FROM_NUMBER": "+15550001111",
    })
    def test_execute_failure(self, mock_client_class, execution_context):
        """Test failed SMS sending."""
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("Network error")
        mock_client_class.return_value = mock_client
        
        from src.adapters.sms_twilio import TwilioSMSAdapter
        adapter = TwilioSMSAdapter()
        adapter._client = mock_client
        
        receipt = adapter.execute(execution_context)
        
        assert receipt.status == "failed"
        assert "Network error" in receipt.error.message
        # Generic exceptions without rate-limit keyword are not retryable
        assert receipt.error.retryable is False
