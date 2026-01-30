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


def select_best_excerpt(articles: List[dict]) -> str:
    """
    Select the best excerpt from a group of articles.
    
    Priority:
    1. Excerpts from priority/local sources (longest preferred)
    2. Longest excerpt from any source
    3. Title from priority source or first article
    
    Args:
        articles: List of article dictionaries with 'excerpt', 'title', 'is_priority' keys
        
    Returns:
        Best excerpt or title to display
    """
    # Priority 1: Excerpts from priority sources
    priority_excerpts = [a.get('excerpt', '') for a in articles if a.get('is_priority') and a.get('excerpt')]
    if priority_excerpts:
        # Return longest priority excerpt
        best = max(priority_excerpts, key=len)
        if best and best.strip():
            return best
    
    # Priority 2: Longest excerpt from any source
    all_excerpts = [a.get('excerpt', '') for a in articles if a.get('excerpt')]
    if all_excerpts:
        best = max(all_excerpts, key=len)
        if best and best.strip():
            return best
    
    # Fallback: Use title from priority source or first article
    priority_titles = [a.get('title', '') for a in articles if a.get('is_priority') and a.get('title')]
    if priority_titles:
        return priority_titles[0]
    
    return articles[0].get('title', '') if articles else ''


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
    
    # Leading divider for clear break from previous message
    blocks.append({"type": "divider"})
    
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
    
    # Trailing divider for clear break to next message
    blocks.append({"type": "divider"})
    
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


def select_best_excerpt(articles: List[dict]) -> str:
    """
    Select the best excerpt from a group of articles.
    
    Priority:
    1. Excerpts from priority/local sources (longest preferred)
    2. Longest excerpt from any source
    3. Title from priority source or first article
    
    Args:
        articles: List of article dictionaries with 'excerpt', 'title', 'is_priority' keys
        
    Returns:
        Best excerpt or title to display
    """
    # Priority 1: Excerpts from priority sources
    priority_excerpts = [a.get('excerpt', '') for a in articles if a.get('is_priority') and a.get('excerpt')]
    if priority_excerpts:
        # Return longest priority excerpt
        best = max(priority_excerpts, key=len)
        if best and best.strip():
            return best
    
    # Priority 2: Longest excerpt from any source
    all_excerpts = [a.get('excerpt', '') for a in articles if a.get('excerpt')]
    if all_excerpts:
        best = max(all_excerpts, key=len)
        if best and best.strip():
            return best
    
    # Fallback: Use title from priority source or first article
    priority_titles = [a.get('title', '') for a in articles if a.get('is_priority') and a.get('title')]
    if priority_titles:
        return priority_titles[0]
    
    return articles[0].get('title', '') if articles else ''


def send_grouped_notification(
    webhook_url: str,
    articles: List[dict],
    excerpt_length: int = 250
) -> bool:
    """
    Send grouped notification to Slack for multiple articles about the same story.
    
    Args:
        webhook_url: Slack webhook URL
        articles: List of article dictionaries (each with same structure as individual notifications)
        excerpt_length: Maximum excerpt length
        
    Returns:
        True if successful, False otherwise
    """
    if not articles:
        return False
    
    # Get all unique communities from all articles
    all_communities = set()
    for article in articles:
        all_communities.update(article.get('communities', []))
    communities_list = sorted(list(all_communities))
    communities_text = ', '.join(communities_list)
    communities_display = f"🏘️ {communities_text}"
    
    # Select best article for main display (priority source first, then most recent)
    main_article = articles[0]  # Already sorted by priority/time in grouper
    
    # Select best excerpt
    best_excerpt = select_best_excerpt(articles)
    truncated_excerpt = truncate_excerpt(best_excerpt, excerpt_length) if best_excerpt else None
    
    # Format source count
    source_count = len(articles)
    sources_display = f"📰 Multiple Sources ({source_count})"
    
    # Format relative time for main article
    relative_time = format_relative_time(main_article.get('pub_datetime'))
    if relative_time:
        time_display = f"Published: {relative_time} ({main_article.get('pub_date', 'Unknown date')})"
    else:
        time_display = f"Published: {main_article.get('pub_date', 'Unknown date')}"
    
    # Build Slack Block Kit payload
    blocks = []
    
    # Leading divider for clear break from previous message
    blocks.append({"type": "divider"})
    
    # Header block with communities and source count
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"{communities_display} | {sources_display}"
        }
    })
    
    # Divider
    blocks.append({"type": "divider"})
    
    # Title block
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*{main_article.get('title', 'No title')}*"
        }
    })
    
    # Best excerpt block (if available and different from title)
    if truncated_excerpt and truncated_excerpt != main_article.get('title', ''):
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": truncated_excerpt
            }
        })
    
    # Divider
    blocks.append({"type": "divider"})
    
    # Publication info
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": time_display
            }
        ]
    })
    
    # Sources section
    sources_text = "📰 *Sources:*\n"
    for article in articles:
        source_name = article.get('source', 'Unknown Source')
        if article.get('is_priority'):
            source_name += " (Local)"
        
        relative_time_article = format_relative_time(article.get('pub_datetime'))
        time_str = relative_time_article if relative_time_article else article.get('pub_date', 'Unknown date')
        
        link = article.get('link', '#')
        sources_text += f"• *{source_name}* - {time_str} - <{link}|Read>\n"
    
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": sources_text.strip()
        }
    })
    
    # Trailing divider for clear break to next message
    blocks.append({"type": "divider"})
    
    payload = {
        "blocks": blocks,
        "text": f"{communities_text}: {main_article.get('title', 'No title')} ({source_count} sources)"  # Fallback text
    }
    
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                webhook_url,
                json=payload,
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            logger.info(f"Posted grouped notification to Slack: {communities_text} - {source_count} sources")
            return True
            
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout posting grouped notification to Slack (attempt {attempt + 1}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES - 1:
                sleep(RETRY_DELAY_BASE ** attempt)
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error posting grouped notification to Slack (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                sleep(RETRY_DELAY_BASE ** attempt)
            else:
                logger.error(f"Failed to post grouped notification to Slack after {MAX_RETRIES} attempts")
                return False
    
    return False
