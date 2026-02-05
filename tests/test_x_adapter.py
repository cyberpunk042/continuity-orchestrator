"""
Tests for the X (Twitter) Adapter.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import os

from src.adapters.x_twitter import XAdapter
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
            enabled_adapters=EnabledAdapters(x=True),
            routing=Routing(
                operator_email="test@example.com",
            ),
        ),
        pointers=Pointers(),
    )


@pytest.fixture
def sample_action():
    """Create a sample action definition."""
    return ActionDefinition(
        id="test_tweet_action",
        adapter="x",
        channel="public",
        template="status_update",
    )


@pytest.fixture
def execution_context(sample_state, sample_action):
    """Create an execution context."""
    return ExecutionContext(
        state=sample_state,
        action=sample_action,
        tick_id="T-TEST-001",
        template_content="Important update: The system is operating normally. #status",
    )


class TestXAdapter:
    """Tests for XAdapter."""
    
    def test_name(self):
        """Test adapter name."""
        adapter = XAdapter()
        assert adapter.name == "x"
    
    def test_max_tweet_length(self):
        """Test max tweet length constant."""
        adapter = XAdapter()
        assert adapter.MAX_TWEET_LENGTH == 280
    
    def test_is_enabled_no_credentials(self, execution_context):
        """Test disabled when no X credentials."""
        with patch.dict(os.environ, {}, clear=True):
            adapter = XAdapter()
            assert adapter.is_enabled(execution_context) is False
    
    def test_is_enabled_partial_credentials(self, execution_context):
        """Test disabled with only some credentials."""
        with patch.dict(os.environ, {
            "X_API_KEY": "test_key",
            # Missing other credentials
        }, clear=True):
            adapter = XAdapter()
            assert adapter.is_enabled(execution_context) is False
    
    def test_is_configured_all_credentials(self):
        """Test _is_configured returns True with all credentials."""
        with patch.dict(os.environ, {
            "X_API_KEY": "test_key",
            "X_API_SECRET": "test_secret",
            "X_ACCESS_TOKEN": "test_token",
            "X_ACCESS_SECRET": "test_token_secret",
        }):
            adapter = XAdapter()
            assert adapter._is_configured() is True
    
    def test_validate_empty_template_generates_default(self, sample_state, sample_action):
        """Test that empty template still generates valid default content."""
        context = ExecutionContext(
            state=sample_state,
            action=sample_action,
            tick_id="T-TEST-001",
            template_content="",
        )
        
        # Mock credentials
        with patch.dict(os.environ, {
            "X_API_KEY": "test",
            "X_API_SECRET": "test",
            "X_ACCESS_TOKEN": "test",
            "X_ACCESS_SECRET": "test",
        }):
            adapter = XAdapter()
            # Empty template still generates default tweet, so validation passes
            is_valid, error = adapter.validate(context)
            
            assert is_valid is True  # Default tweet is generated
    
    def test_validate_valid_content(self, execution_context):
        """Test validation passes with valid content."""
        with patch.dict(os.environ, {
            "X_API_KEY": "test",
            "X_API_SECRET": "test",
            "X_ACCESS_TOKEN": "test",
            "X_ACCESS_SECRET": "test",
        }):
            adapter = XAdapter()
            is_valid, error = adapter.validate(execution_context)
            
            assert is_valid is True
            assert error is None
    
    def test_build_tweet_with_template(self, execution_context):
        """Test tweet building with template content."""
        adapter = XAdapter()
        tweet = adapter._build_tweet(execution_context)
        
        assert "Important update" in tweet
        assert "#status" in tweet
    
    def test_build_tweet_default(self, sample_state, sample_action):
        """Test default tweet when no template."""
        context = ExecutionContext(
            state=sample_state,
            action=sample_action,
            tick_id="T-TEST-001",
            template_content=None,
        )
        
        adapter = XAdapter()
        tweet = adapter._build_tweet(context)
        
        assert "[test-project]" in tweet
        assert "REMIND_1" in tweet
        assert "#continuity" in tweet
    
    def test_build_tweet_overdue(self, sample_state, sample_action):
        """Test overdue tweet format."""
        sample_state.timer.time_to_deadline_minutes = 0
        sample_state.timer.overdue_minutes = 120
        
        context = ExecutionContext(
            state=sample_state,
            action=sample_action,
            tick_id="T-TEST-001",
            template_content=None,
        )
        
        adapter = XAdapter()
        tweet = adapter._build_tweet(context)
        
        assert "🚨" in tweet
        assert "OVERDUE" in tweet
    
    def test_parse_template_strips_headers(self):
        """Test markdown headers are stripped from template."""
        adapter = XAdapter()
        
        content = "# Header\n## Subheader\nActual tweet content here."
        result = adapter._parse_template(content)
        
        assert "Actual tweet content" in result
        assert "#" not in result or result.index("#") > 0  # Hashtags are ok
    
    def test_format_time_minutes(self):
        """Test time formatting for minutes."""
        adapter = XAdapter()
        
        assert adapter._format_time(30) == "30m"
        assert adapter._format_time(59) == "59m"
    
    def test_format_time_hours(self):
        """Test time formatting for hours."""
        adapter = XAdapter()
        
        assert adapter._format_time(60) == "1h"
        assert adapter._format_time(90) == "1h 30m"
    
    def test_format_time_days(self):
        """Test time formatting for days."""
        adapter = XAdapter()
        
        assert adapter._format_time(1440) == "1d"
        assert adapter._format_time(1500) == "1d 1h"
    
    def test_extract_error_message_detail(self):
        """Test error extraction with detail field."""
        adapter = XAdapter()
        
        error_data = {"detail": "Rate limit exceeded"}
        result = adapter._extract_error_message(error_data, 429)
        
        assert result == "Rate limit exceeded"
    
    def test_extract_error_message_errors_array(self):
        """Test error extraction with errors array."""
        adapter = XAdapter()
        
        error_data = {"errors": [{"message": "Invalid request"}]}
        result = adapter._extract_error_message(error_data, 400)
        
        assert result == "Invalid request"
    
    def test_extract_error_message_fallback(self):
        """Test error extraction falls back to status code."""
        adapter = XAdapter()
        
        result = adapter._extract_error_message({}, 403)
        
        assert "Forbidden" in result
    
    def test_is_retryable_status(self):
        """Test retryable status codes."""
        adapter = XAdapter()
        
        # These should be retryable
        assert adapter._is_retryable_status(429) is True
        assert adapter._is_retryable_status(500) is True
        assert adapter._is_retryable_status(503) is True
        
        # These should not be retryable
        assert adapter._is_retryable_status(400) is False
        assert adapter._is_retryable_status(401) is False
        assert adapter._is_retryable_status(403) is False
    
    @patch("src.adapters.x_twitter.httpx")
    @patch.dict(os.environ, {
        "X_API_KEY": "test_key",
        "X_API_SECRET": "test_secret",
        "X_ACCESS_TOKEN": "test_token",
        "X_ACCESS_SECRET": "test_token_secret",
    })
    def test_execute_success(self, mock_httpx, execution_context):
        """Test successful tweet posting."""
        # Mock the HTTP client
        mock_client = MagicMock()
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "data": {"id": "1234567890123456789"}
        }
        mock_client.post.return_value = mock_response
        mock_httpx.Client.return_value = mock_client
        
        adapter = XAdapter()
        adapter._client = mock_client
        
        receipt = adapter.execute(execution_context)
        
        assert receipt.status == "ok"
        assert receipt.delivery_id == "1234567890123456789"
        assert receipt.adapter == "x"
        mock_client.post.assert_called_once()
    
    @patch("src.adapters.x_twitter.httpx")
    @patch.dict(os.environ, {
        "X_API_KEY": "test_key",
        "X_API_SECRET": "test_secret",
        "X_ACCESS_TOKEN": "test_token",
        "X_ACCESS_SECRET": "test_token_secret",
    })
    def test_execute_rate_limit(self, mock_httpx, execution_context):
        """Test rate limit error handling."""
        mock_client = MagicMock()
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.content = b'{"detail": "Rate limit exceeded"}'
        mock_response.json.return_value = {"detail": "Rate limit exceeded"}
        mock_client.post.return_value = mock_response
        mock_httpx.Client.return_value = mock_client
        
        adapter = XAdapter()
        adapter._client = mock_client
        
        receipt = adapter.execute(execution_context)
        
        assert receipt.status == "failed"
        assert receipt.error.code == "twitter_429"
        assert receipt.error.retryable is True
    
    @patch("src.adapters.x_twitter.httpx")
    @patch.dict(os.environ, {
        "X_API_KEY": "test_key",
        "X_API_SECRET": "test_secret",
        "X_ACCESS_TOKEN": "test_token",
        "X_ACCESS_SECRET": "test_token_secret",
    })
    def test_execute_auth_error(self, mock_httpx, execution_context):
        """Test authentication error handling."""
        mock_client = MagicMock()
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.content = b'{"detail": "Unauthorized"}'
        mock_response.json.return_value = {"detail": "Unauthorized"}
        mock_client.post.return_value = mock_response
        mock_httpx.Client.return_value = mock_client
        
        adapter = XAdapter()
        adapter._client = mock_client
        
        receipt = adapter.execute(execution_context)
        
        assert receipt.status == "failed"
        assert receipt.error.code == "twitter_401"
        assert receipt.error.retryable is False
    
    def test_oauth_header_format(self):
        """Test OAuth header has correct format."""
        with patch.dict(os.environ, {
            "X_API_KEY": "test_key",
            "X_API_SECRET": "test_secret",
            "X_ACCESS_TOKEN": "test_token",
            "X_ACCESS_SECRET": "test_token_secret",
        }):
            adapter = XAdapter()
            header = adapter._build_oauth_header(
                "POST",
                "https://api.twitter.com/2/tweets"
            )
            
            assert header.startswith("OAuth ")
            assert "oauth_consumer_key" in header
            assert "oauth_signature" in header
            assert "oauth_token" in header
            assert "oauth_nonce" in header
            assert "oauth_timestamp" in header
