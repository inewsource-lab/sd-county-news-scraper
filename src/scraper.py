"""Core RSS feed scraping logic."""
import logging
import re
import feedparser
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List, Set, Optional
from time import sleep

from .cache_manager import CacheManager
from .notifier import send_slack_notification

logger = logging.getLogger(__name__)

# Request timeout for feed fetching
FEED_TIMEOUT = 15
# Delay between feed requests to be respectful
FEED_DELAY = 1


def format_pub_date(entry) -> str:
    """
    Format publication date from RSS entry.
    
    Args:
        entry: feedparser entry object
        
    Returns:
        Formatted date string in Pacific Time
    """
    try:
        if getattr(entry, 'published_parsed', None):
            # Build a UTC datetime
            dt_utc = datetime(*entry.published_parsed[:6], tzinfo=ZoneInfo("UTC"))
            # Convert to Pacific Time
            dt_pt = dt_utc.astimezone(ZoneInfo("America/Los_Angeles"))
            # Format with timezone indicator
            return dt_pt.strftime('%Y-%m-%d %H:%M PT')
    except Exception as e:
        logger.debug(f"Error parsing published_parsed: {e}")
    
    # Fall back to raw strings
    return entry.get('published') or entry.get('updated') or 'Unknown date'


def fetch_feed(feed_url: str) -> Optional[feedparser.FeedParserDict]:
    """
    Fetch and parse an RSS feed with error handling.
    
    Args:
        feed_url: URL of the RSS feed
        
    Returns:
        Parsed feed object or None if failed
    """
    try:
        logger.debug(f"Fetching feed: {feed_url}")
        feed = feedparser.parse(feed_url)
        
        if feed.bozo:
            logger.warning(f"Feed parsing issues for {feed_url}: {feed.bozo_exception}")
        
        return feed
        
    except Exception as e:
        logger.error(f"Error fetching feed {feed_url}: {e}")
        return None


def check_entry_matches(
    entry,
    communities: List[str],
    cache: CacheManager
) -> Optional[tuple]:
    """
    Check if an entry matches any community and hasn't been seen.
    
    Args:
        entry: feedparser entry object
        communities: List of community names to match
        cache: CacheManager instance
        
    Returns:
        Tuple of (community, title, pub_date, link) if match found, None otherwise
    """
    link = entry.get('link')
    if not link:
        return None
    
    # Skip if already seen
    if cache.has_seen(link):
        return None
    
    title = entry.get('title', '').strip()
    summary_text = (entry.get('summary', '') or '').strip().lower()
    combined = (title + " " + summary_text).lower()
    
    # Check against each community using word boundary matching
    # This ensures "Vista" matches "Vista" but not "Chula Vista"
    for community in communities:
        # Escape special regex characters and use word boundaries
        pattern = r'\b' + re.escape(community.lower()) + r'\b'
        if re.search(pattern, combined):
            pub_date = format_pub_date(entry)
            return (community, title, pub_date, link)
    
    return None


def scrape_and_notify(
    feed_urls: List[str],
    communities: List[str],
    webhook_url: str,
    cache: CacheManager
) -> int:
    """
    Scrape RSS feeds and send notifications for matching articles.
    
    Args:
        feed_urls: List of RSS feed URLs to check
        communities: List of community names to match
        webhook_url: Slack webhook URL
        cache: CacheManager instance
        
    Returns:
        Number of articles posted
    """
    posted_count = 0
    
    for feed_url in feed_urls:
        feed = fetch_feed(feed_url)
        
        if not feed:
            continue
        
        entry_count = len(feed.entries) if feed.entries else 0
        logger.info(f"Checking {feed_url} → {entry_count} entries")
        
        if entry_count == 0:
            continue
        
        for entry in feed.entries:
            match = check_entry_matches(entry, communities, cache)
            
            if match:
                community, title, pub_date, link = match
                logger.info(f"Match found for {community}: {title}")
                
                if send_slack_notification(webhook_url, community, title, pub_date, link):
                    cache.mark_seen(link)
                    posted_count += 1
        
        # Be respectful - delay between feeds
        if feed_url != feed_urls[-1]:  # Don't delay after last feed
            sleep(FEED_DELAY)
    
    return posted_count
