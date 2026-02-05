"""
Reddit Adapter — Post to Reddit via PRAW.

This adapter posts to subreddits using the Reddit API via PRAW.
Credentials are expected in environment variables.

## Configuration

- REDDIT_CLIENT_ID: Reddit App Client ID
- REDDIT_CLIENT_SECRET: Reddit App Client Secret
- REDDIT_USERNAME: Reddit account username
- REDDIT_PASSWORD: Reddit account password

## Usage

Posts are made to subreddits specified in state.integrations.routing.reddit_targets.

## Template Support

If a template is resolved, its content is used as the post body.
The first line (if it's a header) is used as the post title.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from .base import Adapter, ExecutionContext
from ..models.receipt import Receipt

logger = logging.getLogger(__name__)

# Optional praw import — graceful degradation
try:
    import praw
    from praw.exceptions import PRAWException
    PRAW_AVAILABLE = True
except ImportError:
    PRAW_AVAILABLE = False
    praw = None
    PRAWException = Exception


class RedditAdapter(Adapter):
    """
    Reddit adapter using PRAW (Python Reddit API Wrapper).
    
    Requires REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME, 
    and REDDIT_PASSWORD environment variables.
    """
    
    MAX_TITLE_LENGTH = 300
    USER_AGENT = "continuity-orchestrator/1.0"
    
    def __init__(self):
        self.client_id = os.environ.get("REDDIT_CLIENT_ID")
        self.client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
        self.username = os.environ.get("REDDIT_USERNAME")
        self.password = os.environ.get("REDDIT_PASSWORD")
        
        self._reddit: Optional[praw.Reddit] = None
        
        if PRAW_AVAILABLE and self._is_configured():
            try:
                self._reddit = praw.Reddit(
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    username=self.username,
                    password=self.password,
                    user_agent=self.USER_AGENT,
                )
            except Exception as e:
                logger.warning(f"Failed to initialize Reddit client: {e}")
    
    @property
    def name(self) -> str:
        return "reddit"
    
    @property
    def reddit(self) -> Optional[praw.Reddit]:
        """Access the Reddit client."""
        return self._reddit
    
    def _is_configured(self) -> bool:
        """Check if all required credentials are present."""
        return all([
            self.client_id,
            self.client_secret,
            self.username,
            self.password,
        ])
    
    def is_enabled(self, context: ExecutionContext) -> bool:
        """Enabled if PRAW is available and credentials are configured."""
        if not PRAW_AVAILABLE:
            logger.warning("praw package not installed, Reddit adapter disabled")
            return False
        
        if not self._is_configured():
            missing = []
            if not self.client_id:
                missing.append("REDDIT_CLIENT_ID")
            if not self.client_secret:
                missing.append("REDDIT_CLIENT_SECRET")
            if not self.username:
                missing.append("REDDIT_USERNAME")
            if not self.password:
                missing.append("REDDIT_PASSWORD")
            logger.warning(f"Reddit adapter disabled, missing: {', '.join(missing)}")
            return False
        
        return context.state.integrations.enabled_adapters.reddit
    
    def validate(self, context: ExecutionContext) -> tuple:
        """Validate post can be made."""
        if not self._is_configured():
            return False, "Reddit API credentials not configured"
        
        # Check for target subreddits
        targets = self._get_targets(context)
        if not targets:
            return False, "No reddit_targets configured in routing"
        
        # Check that we have content to post
        title, _ = self._build_post(context)
        
        if not title or len(title.strip()) == 0:
            return False, "Empty post title"
        
        return True, None
    
    def execute(self, context: ExecutionContext) -> Receipt:
        """Post to Reddit via PRAW."""
        targets = self._get_targets(context)
        
        if not targets:
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code="no_targets",
                error_message="No subreddits configured in routing",
                retryable=False,
            )
        
        # Build post content
        title, body = self._build_post(context)
        
        if not title:
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code="empty_title",
                error_message="No title for Reddit post",
                retryable=False,
            )
        
        # Truncate title if needed
        if len(title) > self.MAX_TITLE_LENGTH:
            title = title[:self.MAX_TITLE_LENGTH - 3] + "..."
            logger.warning(f"Reddit title truncated to {self.MAX_TITLE_LENGTH} chars")
        
        # Post to all target subreddits
        results = []
        errors = []
        
        for target in targets:
            subreddit_name = target.replace("r/", "").strip()
            
            try:
                subreddit = self._reddit.subreddit(subreddit_name)
                
                submission = subreddit.submit(
                    title=title,
                    selftext=body or "",
                )
                
                logger.info(f"Posted to r/{subreddit_name}: {submission.id}")
                results.append({
                    "subreddit": subreddit_name,
                    "submission_id": submission.id,
                    "url": f"https://reddit.com{submission.permalink}",
                })
                
            except PRAWException as e:
                logger.error(f"Failed to post to r/{subreddit_name}: {e}")
                errors.append({
                    "subreddit": subreddit_name,
                    "error": str(e),
                })
            except Exception as e:
                logger.exception(f"Unexpected error posting to r/{subreddit_name}: {e}")
                errors.append({
                    "subreddit": subreddit_name,
                    "error": str(e),
                })
        
        # Determine overall result
        if results and not errors:
            # All posts succeeded
            return Receipt.ok(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                delivery_id=results[0]["submission_id"] if len(results) == 1 else "multiple",
                details={
                    "posts": results,
                    "template": context.action.template,
                },
            )
        elif results and errors:
            # Partial success
            return Receipt.ok(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                delivery_id="partial",
                details={
                    "posts": results,
                    "errors": errors,
                    "template": context.action.template,
                },
            )
        else:
            # All failed
            return Receipt.failed(
                adapter=self.name,
                action_id=context.action.id,
                channel=context.action.channel,
                error_code="all_failed",
                error_message=f"Failed to post to all targets: {errors}",
                retryable=True,
            )
    
    def _get_targets(self, context: ExecutionContext) -> List[str]:
        """Get list of target subreddits."""
        return context.routing.reddit_targets or []
    
    def _build_post(self, context: ExecutionContext) -> tuple:
        """
        Build the Reddit post content.
        
        Returns: (title, body)
        """
        template_content = context.template_content
        
        if template_content:
            return self._parse_template(template_content)
        
        # Default post format
        stage = context.escalation.state
        project = context.meta.project
        minutes = context.timer.time_to_deadline_minutes
        
        if minutes > 0:
            time_str = self._format_time(minutes)
            title = f"[{project}] Status Update: {stage}"
            body = f"**Current Status:** {stage}\n\n"
            body += f"**Time to Deadline:** {time_str}\n\n"
            body += "---\n\n*This is an automated post from Continuity Orchestrator.*"
        else:
            overdue = context.timer.overdue_minutes
            time_str = self._format_time(overdue)
            title = f"🚨 [{project}] OVERDUE - {stage}"
            body = f"**Current Status:** {stage}\n\n"
            body += f"**Overdue By:** {time_str}\n\n"
            body += "---\n\n*This is an automated post from Continuity Orchestrator.*"
        
        return title, body
    
    def _parse_template(self, content: str) -> tuple:
        """
        Parse template content for Reddit post.
        
        Returns: (title, body)
        """
        lines = content.strip().split("\n")
        
        # First header line becomes title
        title = None
        body_lines = []
        
        for line in lines:
            if title is None and line.startswith("#"):
                # Extract header as title
                title = line.lstrip("#").strip()
            else:
                body_lines.append(line)
        
        if title is None:
            # No header found, use first line as title
            if lines:
                title = lines[0][:self.MAX_TITLE_LENGTH]
                body_lines = lines[1:]
        
        body = "\n".join(body_lines).strip()
        
        return title, body
    
    def _format_time(self, minutes: int) -> str:
        """Format minutes as human-readable time."""
        if minutes < 60:
            return f"{minutes} minutes"
        
        hours = minutes // 60
        mins = minutes % 60
        
        if hours < 24:
            if mins:
                return f"{hours}h {mins}m"
            return f"{hours} hours"
        
        days = hours // 24
        hours = hours % 24
        if hours:
            return f"{days}d {hours}h"
        return f"{days} days"
