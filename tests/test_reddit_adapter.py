"""
Tests for the Reddit Adapter.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import os

from src.adapters.reddit import RedditAdapter
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
            enabled_adapters=EnabledAdapters(reddit=True),
            routing=Routing(
                operator_email="test@example.com",
                reddit_targets=["r/test", "r/announcements"],
            ),
        ),
        pointers=Pointers(),
    )


@pytest.fixture
def sample_action():
    """Create a sample action definition."""
    return ActionDefinition(
        id="test_reddit_action",
        adapter="reddit",
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
        template_content="# Status Update\n\nImportant information about the current status.",
    )


class TestRedditAdapter:
    """Tests for RedditAdapter."""
    
    def test_name(self):
        """Test adapter name."""
        adapter = RedditAdapter()
        assert adapter.name == "reddit"
    
    def test_max_title_length(self):
        """Test max title length constant."""
        adapter = RedditAdapter()
        assert adapter.MAX_TITLE_LENGTH == 300
    
    def test_is_enabled_no_credentials(self, execution_context):
        """Test disabled when no Reddit credentials."""
        with patch.dict(os.environ, {}, clear=True):
            adapter = RedditAdapter()
            assert adapter.is_enabled(execution_context) is False
    
    def test_is_enabled_partial_credentials(self, execution_context):
        """Test disabled with only some credentials."""
        with patch.dict(os.environ, {
            "REDDIT_CLIENT_ID": "test_id",
            # Missing other credentials
        }, clear=True):
            adapter = RedditAdapter()
            assert adapter.is_enabled(execution_context) is False
    
    def test_is_configured_all_credentials(self):
        """Test _is_configured returns True with all credentials."""
        with patch.dict(os.environ, {
            "REDDIT_CLIENT_ID": "test_id",
            "REDDIT_CLIENT_SECRET": "test_secret",
            "REDDIT_USERNAME": "test_user",
            "REDDIT_PASSWORD": "test_pass",
        }):
            adapter = RedditAdapter()
            assert adapter._is_configured() is True
    
    def test_validate_no_targets(self, sample_state, sample_action):
        """Test validation fails when no targets configured."""
        sample_state.integrations.routing.reddit_targets = []
        context = ExecutionContext(
            state=sample_state,
            action=sample_action,
            tick_id="T-TEST-001",
            template_content="# Title\nBody",
        )
        
        with patch.dict(os.environ, {
            "REDDIT_CLIENT_ID": "test",
            "REDDIT_CLIENT_SECRET": "test",
            "REDDIT_USERNAME": "test",
            "REDDIT_PASSWORD": "test",
        }):
            adapter = RedditAdapter()
            is_valid, error = adapter.validate(context)
            
            assert is_valid is False
            assert "reddit_targets" in error
    
    def test_validate_valid_configuration(self, execution_context):
        """Test validation passes with valid configuration."""
        with patch.dict(os.environ, {
            "REDDIT_CLIENT_ID": "test",
            "REDDIT_CLIENT_SECRET": "test",
            "REDDIT_USERNAME": "test",
            "REDDIT_PASSWORD": "test",
        }):
            adapter = RedditAdapter()
            is_valid, error = adapter.validate(execution_context)
            
            assert is_valid is True
            assert error is None
    
    def test_build_post_with_template(self, execution_context):
        """Test post building with template content."""
        adapter = RedditAdapter()
        title, body = adapter._build_post(execution_context)
        
        assert title == "Status Update"
        assert "Important information" in body
    
    def test_build_post_default(self, sample_state, sample_action):
        """Test default post when no template."""
        context = ExecutionContext(
            state=sample_state,
            action=sample_action,
            tick_id="T-TEST-001",
            template_content=None,
        )
        
        adapter = RedditAdapter()
        title, body = adapter._build_post(context)
        
        assert "[test-project]" in title
        assert "REMIND_1" in title
        assert "automated" in body.lower()
    
    def test_build_post_overdue(self, sample_state, sample_action):
        """Test overdue post format."""
        sample_state.timer.time_to_deadline_minutes = 0
        sample_state.timer.overdue_minutes = 120
        
        context = ExecutionContext(
            state=sample_state,
            action=sample_action,
            tick_id="T-TEST-001",
            template_content=None,
        )
        
        adapter = RedditAdapter()
        title, body = adapter._build_post(context)
        
        assert "🚨" in title
        assert "OVERDUE" in title
        assert "2 hours" in body
    
    def test_parse_template_extracts_title(self):
        """Test template parsing extracts header as title."""
        adapter = RedditAdapter()
        
        content = "# This Is The Title\n\nThis is the body.\n\nMore content."
        title, body = adapter._parse_template(content)
        
        assert title == "This Is The Title"
        assert "This is the body" in body
        assert "More content" in body
    
    def test_parse_template_no_header(self):
        """Test template parsing with no header uses first line."""
        adapter = RedditAdapter()
        
        content = "First line becomes title\n\nThis is the body."
        title, body = adapter._parse_template(content)
        
        assert title == "First line becomes title"
        assert "This is the body" in body
    
    def test_format_time_minutes(self):
        """Test time formatting for minutes."""
        adapter = RedditAdapter()
        
        assert adapter._format_time(30) == "30 minutes"
        assert adapter._format_time(59) == "59 minutes"
    
    def test_format_time_hours(self):
        """Test time formatting for hours."""
        adapter = RedditAdapter()
        
        assert adapter._format_time(60) == "1 hours"
        assert adapter._format_time(90) == "1h 30m"
        assert adapter._format_time(120) == "2 hours"
    
    def test_format_time_days(self):
        """Test time formatting for days."""
        adapter = RedditAdapter()
        
        assert adapter._format_time(1440) == "1 days"
        assert adapter._format_time(1500) == "1d 1h"
    
    def test_get_targets(self, execution_context):
        """Test getting target subreddits."""
        adapter = RedditAdapter()
        targets = adapter._get_targets(execution_context)
        
        assert targets == ["r/test", "r/announcements"]
    
    @patch("src.adapters.reddit.praw")
    @patch.dict(os.environ, {
        "REDDIT_CLIENT_ID": "test_id",
        "REDDIT_CLIENT_SECRET": "test_secret",
        "REDDIT_USERNAME": "test_user",
        "REDDIT_PASSWORD": "test_pass",
    })
    def test_execute_success(self, mock_praw, execution_context):
        """Test successful Reddit post."""
        # Mock the Reddit client
        mock_reddit = MagicMock()
        mock_subreddit = MagicMock()
        mock_submission = Mock()
        mock_submission.id = "abc123"
        mock_submission.permalink = "/r/test/comments/abc123/title/"
        mock_subreddit.submit.return_value = mock_submission
        mock_reddit.subreddit.return_value = mock_subreddit
        mock_praw.Reddit.return_value = mock_reddit
        
        adapter = RedditAdapter()
        adapter._reddit = mock_reddit
        
        receipt = adapter.execute(execution_context)
        
        assert receipt.status == "ok"
        assert receipt.adapter == "reddit"
        assert "posts" in receipt.details
        # Should have posted to both subreddits
        assert len(receipt.details["posts"]) == 2
    
    @patch("src.adapters.reddit.praw")
    @patch.dict(os.environ, {
        "REDDIT_CLIENT_ID": "test_id",
        "REDDIT_CLIENT_SECRET": "test_secret",
        "REDDIT_USERNAME": "test_user",
        "REDDIT_PASSWORD": "test_pass",
    })
    def test_execute_partial_failure(self, mock_praw, execution_context):
        """Test partial failure when one subreddit fails."""
        mock_reddit = MagicMock()
        mock_submission = Mock()
        mock_submission.id = "abc123"
        mock_submission.permalink = "/r/test/comments/abc123/"
        
        # First subreddit succeeds
        mock_subreddit_success = MagicMock()
        mock_subreddit_success.submit.return_value = mock_submission
        
        # Second subreddit fails
        mock_subreddit_fail = MagicMock()
        mock_subreddit_fail.submit.side_effect = Exception("Permission denied")
        
        def get_subreddit(name):
            if name == "test":
                return mock_subreddit_success
            return mock_subreddit_fail
        
        mock_reddit.subreddit.side_effect = get_subreddit
        mock_praw.Reddit.return_value = mock_reddit
        
        adapter = RedditAdapter()
        adapter._reddit = mock_reddit
        
        receipt = adapter.execute(execution_context)
        
        # Should still be "ok" with partial success
        assert receipt.status == "ok"
        assert receipt.delivery_id == "partial"
        assert "posts" in receipt.details
        assert "errors" in receipt.details
    
    @patch("src.adapters.reddit.praw")
    @patch.dict(os.environ, {
        "REDDIT_CLIENT_ID": "test_id",
        "REDDIT_CLIENT_SECRET": "test_secret",
        "REDDIT_USERNAME": "test_user",
        "REDDIT_PASSWORD": "test_pass",
    })
    def test_execute_all_fail(self, mock_praw, execution_context):
        """Test when all subreddits fail."""
        mock_reddit = MagicMock()
        mock_subreddit = MagicMock()
        mock_subreddit.submit.side_effect = Exception("Rate limited")
        mock_reddit.subreddit.return_value = mock_subreddit
        mock_praw.Reddit.return_value = mock_reddit
        
        adapter = RedditAdapter()
        adapter._reddit = mock_reddit
        
        receipt = adapter.execute(execution_context)
        
        assert receipt.status == "failed"
        assert receipt.error.code == "all_failed"
        assert receipt.error.retryable is True
    
    def test_execute_no_targets(self, sample_state, sample_action):
        """Test execution fails with no targets."""
        sample_state.integrations.routing.reddit_targets = []
        context = ExecutionContext(
            state=sample_state,
            action=sample_action,
            tick_id="T-TEST-001",
            template_content="# Title\nBody",
        )
        
        with patch.dict(os.environ, {
            "REDDIT_CLIENT_ID": "test",
            "REDDIT_CLIENT_SECRET": "test",
            "REDDIT_USERNAME": "test",
            "REDDIT_PASSWORD": "test",
        }):
            adapter = RedditAdapter()
            receipt = adapter.execute(context)
            
            assert receipt.status == "failed"
            assert receipt.error.code == "no_targets"
