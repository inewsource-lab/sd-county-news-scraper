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
# Slack section text hard limit (API allows 3000; leave headroom)
SLACK_SECTION_MAX = 2900


def escape_mrkdwn(text: str) -> str:
    """Escape characters that break Slack mrkdwn (&, <, >)."""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


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
    excerpt_length: int = 250,
    unfurl_links: bool = False,
    urgency: Optional[str] = None
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
        excerpt: Article excerpt/summary (or AI summary when provided)
        match_location: Where match was found ('title', 'summary', or 'ai_relevance')
        is_priority: Whether source is a priority/local source
        excerpt_length: Maximum excerpt length
        unfurl_links: If False, disable Slack link/media unfurling (default: False)
        urgency: Optional 'breaking', 'developing', or 'routine' for label

    Returns:
        True if successful, False otherwise
    """
    communities_text = ', '.join(communities)
    communities_display = f"🏘️ {escape_mrkdwn(communities_text)}"

    source_display = f"📰 {escape_mrkdwn(source)}"
    if is_priority:
        source_display += " (Local)"

    if urgency == 'breaking':
        source_display = "🔴 *Breaking* | " + source_display
    elif urgency == 'developing':
        source_display = "🟡 *Developing* | " + source_display

    relative_time = format_relative_time(pub_datetime)
    if relative_time:
        time_display = f"Published: {relative_time} ({pub_date})"
    else:
        time_display = f"Published: {pub_date}"

    truncated_excerpt = truncate_excerpt(excerpt, excerpt_length) if excerpt else None
    safe_title = escape_mrkdwn(title)

    blocks = []

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"{communities_display} | {source_display}"
        }
    })
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*{safe_title}*"
        }
    })
    match_indicator = (
        "📍 In title" if match_location == 'title'
        else ("📄 In summary" if match_location == 'summary' else "🤖 AI relevance")
    )
    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": f"{escape_mrkdwn(time_display)} • {match_indicator}"}
        ]
    })
    if truncated_excerpt and truncated_excerpt != title:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": escape_mrkdwn(truncated_excerpt)}
        })
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"🔗 <{link}|Read more>"
        }
    })
    blocks.append({"type": "divider"})

    payload = {
        "blocks": blocks,
        "text": f"{communities_text}: {title}"
    }
    if not unfurl_links:
        payload["unfurl_links"] = False
        payload["unfurl_media"] = False

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


def send_grouped_notification(
    webhook_url: str,
    articles: List[dict],
    excerpt_length: int = 250,
    unfurl_links: bool = False,
    group_summary: Optional[str] = None,
    suggested_angle: Optional[str] = None,
) -> bool:
    """
    Send grouped notification to Slack for multiple articles about the same story.

    Args:
        webhook_url: Slack webhook URL
        articles: List of article dictionaries
        excerpt_length: Maximum excerpt length
        unfurl_links: If False, disable Slack link/media unfurling (default: False)
        group_summary: Optional AI-synthesized 1–2 sentence summary for the group
        suggested_angle: Optional AI-suggested follow-up angle for journalists

    Returns:
        True if successful, False otherwise
    """
    if not articles:
        return False

    all_communities = set()
    for article in articles:
        all_communities.update(article.get('communities', []))
    communities_list = sorted(list(all_communities))
    communities_text = ', '.join(communities_list)
    communities_display = f"🏘️ {escape_mrkdwn(communities_text)}"

    main_article = articles[0]

    best_excerpt = group_summary if group_summary else select_best_excerpt(articles)
    truncated_excerpt = truncate_excerpt(best_excerpt, excerpt_length) if best_excerpt else None

    source_count = len(articles)
    sources_display = f"📰 Multiple Sources ({source_count})"

    relative_time = format_relative_time(main_article.get('pub_datetime'))
    if relative_time:
        time_display = f"Published: {relative_time} ({main_article.get('pub_date', 'Unknown date')})"
    else:
        time_display = f"Published: {main_article.get('pub_date', 'Unknown date')}"

    main_title = escape_mrkdwn(main_article.get('title', 'No title'))

    blocks = []

    blocks.append({"type": "divider"})

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"{communities_display} | {sources_display}"
        }
    })
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*{main_title}*"
        }
    })
    if truncated_excerpt and truncated_excerpt != main_article.get('title', ''):
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": escape_mrkdwn(truncated_excerpt)}
        })
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": escape_mrkdwn(time_display)}]
    })
    if suggested_angle:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"💡 *Suggested angle:* {escape_mrkdwn(suggested_angle)}"
            }
        })

    sources_lines = ["📰 *Sources:*"]
    for article in articles:
        source_name = article.get('source', 'Unknown Source')
        if article.get('is_priority'):
            source_name += " (Local)"

        relative_time_article = format_relative_time(article.get('pub_datetime'))
        time_str = relative_time_article if relative_time_article else article.get('pub_date', 'Unknown date')

        link = article.get('link', '#')
        line = f"• *{escape_mrkdwn(source_name)}* - {escape_mrkdwn(str(time_str))} - <{link}|Read>"
        candidate = "\n".join(sources_lines + [line])
        if len(candidate) > SLACK_SECTION_MAX:
            remaining = len(articles) - (len(sources_lines) - 1)
            if remaining > 0:
                sources_lines.append(f"• …and {remaining} more sources")
            break
        sources_lines.append(line)

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "\n".join(sources_lines)
        }
    })
    blocks.append({"type": "divider"})

    payload = {
        "blocks": blocks,
        "text": f"{communities_text}: {main_article.get('title', 'No title')} ({source_count} sources)"
    }
    if not unfurl_links:
        payload["unfurl_links"] = False
        payload["unfurl_media"] = False

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
