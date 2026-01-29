"""Slack notification handling."""
import logging
import requests
from typing import Optional, List
from time import sleep
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Request timeout in seconds
REQUEST_TIMEOUT = 10
# Maximum retry attempts
MAX_RETRIES = 3
# Base delay for exponential backoff (seconds)
RETRY_DELAY_BASE = 2


def format_relative_time(pub_datetime: Optional[datetime]) -> Optional[str]:
    """
    Format relative time (e.g., "2 hours ago").
    
    Args:
        pub_datetime: Publication datetime object
        
    Returns:
        Relative time string or None if datetime unavailable
    """
    if not pub_datetime:
        return None
    
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    delta = now - pub_datetime
    
    if delta.total_seconds() < 60:
        return "just now"
    elif delta.total_seconds() < 3600:
        minutes = int(delta.total_seconds() / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif delta.total_seconds() < 86400:
        hours = int(delta.total_seconds() / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif delta.days < 7:
        days = delta.days
        return f"{days} day{'s' if days != 1 else ''} ago"
    else:
        weeks = delta.days // 7
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"


def truncate_excerpt(text: str, max_length: int) -> str:
    """
    Truncate text to max_length, adding ellipsis if truncated.
    
    Args:
        text: Text to truncate
        max_length: Maximum length
        
    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text
    
    # Try to truncate at word boundary
    truncated = text[:max_length].rsplit(' ', 1)[0]
    return truncated + '...'


def send_slack_notification(
    webhook_url: str,
    communities: List[str],
    title: str,
    pub_date: str,
    pub_datetime: Optional[datetime],
    link: str,
    source: str,
    excerpt: str,
    match_location: str,
    is_priority: bool,
    excerpt_length: int = 250
) -> bool:
    """
    Send notification to Slack webhook using Block Kit format.
    
    Args:
        webhook_url: Slack webhook URL
        communities: List of matching community names
        title: Article title
        pub_date: Publication date string
        pub_datetime: Publication datetime object (for relative time)
        link: Article URL
        source: Source name
        excerpt: Article excerpt/summary
        match_location: Where match was found ('title' or 'summary')
        is_priority: Whether source is a priority/local source
        excerpt_length: Maximum excerpt length
        
    Returns:
        True if successful, False otherwise
    """
    # Format communities
    communities_text = ', '.join(communities)
    if len(communities) > 1:
        communities_display = f"🏘️ {communities_text}"
    else:
        communities_display = f"🏘️ {communities_text}"
    
    # Format source with priority indicator
    source_display = f"📰 {source}"
    if is_priority:
        source_display += " (Local)"
    
    # Format relative time
    relative_time = format_relative_time(pub_datetime)
    if relative_time:
        time_display = f"Published: {relative_time} ({pub_date})"
    else:
        time_display = f"Published: {pub_date}"
    
    # Truncate excerpt
    truncated_excerpt = truncate_excerpt(excerpt, excerpt_length) if excerpt else None
    
    # Build Slack Block Kit payload
    blocks = []
    
    # Header block with communities and source
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"{communities_display} | {source_display}"
        }
    })
    
    # Divider
    blocks.append({"type": "divider"})
    
    # Title block
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*{title}*"
        }
    })
    
    # Divider
    blocks.append({"type": "divider"})
    
    # Publication info
    match_indicator = "📍 In title" if match_location == 'title' else "📄 In summary"
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"{time_display} • {match_indicator}"
            }
        ]
    })
    
    # Excerpt block (if available)
    if truncated_excerpt and truncated_excerpt != title:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": truncated_excerpt
            }
        })
    
    # Link block
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"🔗 <{link}|Read more>"
        }
    })
    
    payload = {
        "blocks": blocks,
        "text": f"{communities_text}: {title}"  # Fallback text for notifications
    }
    
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                webhook_url,
                json=payload,
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            logger.info(f"Posted to Slack: {communities_text} - {title}")
            return True
            
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout posting to Slack (attempt {attempt + 1}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES - 1:
                sleep(RETRY_DELAY_BASE ** attempt)
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error posting to Slack (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                sleep(RETRY_DELAY_BASE ** attempt)
            else:
                logger.error(f"Failed to post to Slack after {MAX_RETRIES} attempts")
                return False
    
    return False
