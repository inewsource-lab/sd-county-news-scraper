"""Core RSS feed scraping logic."""
import logging
import re
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Set, Optional, Tuple, Dict
from time import sleep
from urllib.parse import urlparse

from .cache_manager import CacheManager
from .notifier import send_slack_notification, send_grouped_notification
from .story_grouper import StoryGrouper

logger = logging.getLogger(__name__)

# Request timeout for feed fetching
FEED_TIMEOUT = 15
# Delay between feed requests to be respectful
FEED_DELAY = 1


def get_pub_datetime(entry) -> Optional[datetime]:
    """
    Get publication datetime object from RSS entry.
    
    Args:
        entry: feedparser entry object
        
    Returns:
        datetime object in Pacific Time, or None if unavailable
    """
    try:
        if getattr(entry, 'published_parsed', None):
            # Build a UTC datetime
            dt_utc = datetime(*entry.published_parsed[:6], tzinfo=ZoneInfo("UTC"))
            # Convert to Pacific Time
            return dt_utc.astimezone(ZoneInfo("America/Los_Angeles"))
    except Exception as e:
        logger.debug(f"Error parsing published_parsed: {e}")
    
    return None


def format_pub_date(entry) -> str:
    """
    Format publication date from RSS entry.
    
    Args:
        entry: feedparser entry object
        
    Returns:
        Formatted date string in Pacific Time
    """
    dt_pt = get_pub_datetime(entry)
    if dt_pt:
        return dt_pt.strftime('%Y-%m-%d %H:%M PT')
    
    # Fall back to raw strings
    return entry.get('published') or entry.get('updated') or 'Unknown date'


def extract_source_name(feed_url: str) -> str:
    """
    Extract a readable source name from feed URL.
    
    Args:
        feed_url: RSS feed URL
        
    Returns:
        Source name (e.g., "The Coast News", "San Diego Union-Tribune")
    """
    try:
        parsed = urlparse(feed_url)
        domain = parsed.netloc.lower()
        
        # Remove common prefixes
        domain = domain.replace('www.', '').replace('feeds.', '')
        
        # Handle special cases
        source_map = {
            'thecoastnews.com': 'The Coast News',
            'northcoastcurrent.com': 'North Coast Current',
            'timesofsandiego.com': 'Times of San Diego',
            'voiceofsandiego.org': 'Voice of San Diego',
            'sandiegouniontribune.com': 'San Diego Union-Tribune',
            'nbcsandiego.com': 'NBC San Diego',
            'cbs8.com': 'CBS 8',
            'fox5sandiego.com': 'FOX 5 San Diego',
            'kpbs.org': 'KPBS',
            'countynewscenter.com': 'County News Center',
            'sdnews.com': 'SD News',
            'lgbtqsd.news': 'LGBTQ San Diego',
            'gay-sd.com': 'Gay San Diego',
            'delmartimes.net': 'Del Mar Times',
            'sandiegonewsdesk.com': 'San Diego News Desk',
            'chulavistatoday.com': 'Chula Vista Today',
            'triton.news': 'Triton News',
            'sandiegoreader.com': 'San Diego Reader',
            'jewishjournal.com': 'Jewish Journal',
            'ranchosfnews.com': 'Rancho Santa Fe News',
            'valleycenter.com': 'Valley Center News',
            'escondidotimes-advocate.com': 'Escondido Times-Advocate',
            'myvalleynews.com': 'My Valley News',
            'villagenews.com': 'Village News',
            'ramonasentinel.com': 'Ramona Sentinel',
            'powaynewschieftain.com': 'Poway News Chieftain',
            'sandiegobusiness.com': 'San Diego Business Journal',
            'patch.com': 'Patch',
            'coronadotimes.com': 'Coronado Times',
            'sdcitytimes.com': 'SD City Times',
            'laprensa.org': 'La Prensa',
            'clairemonttimes.com': 'Clairemont Times',
            'thecoronadonews.com': 'The Coronado News',
            'mesapress.com': 'Mesa Press',
        }
        
        if domain in source_map:
            return source_map[domain]
        
        # For patch.com, try to extract location from path
        if 'patch.com' in domain:
            path_parts = parsed.path.split('/')
            if len(path_parts) > 2:
                location = path_parts[-2].replace('-', ' ').title()
                return f'Patch ({location})'
        
        # Default: capitalize domain name
        return domain.split('.')[0].replace('-', ' ').title()
        
    except Exception as e:
        logger.debug(f"Error extracting source name from {feed_url}: {e}")
        return "Unknown Source"


def is_priority_source(feed_url: str, priority_sources: Optional[List[str]] = None) -> bool:
    """
    Check if a feed URL is a priority/local source.
    
    Args:
        feed_url: RSS feed URL
        priority_sources: Optional list of priority source URLs/patterns
        
    Returns:
        True if source is priority/local
    """
    if not priority_sources:
        return False
    
    feed_url_lower = feed_url.lower()
    for priority in priority_sources:
        if priority.lower() in feed_url_lower:
            return True
    
    return False


def strip_html(html_str: str) -> str:
    """
    Remove HTML tags and return plain text.
    
    Args:
        html_str: Raw HTML string (e.g. RSS summary)
        
    Returns:
        Plain text with tags removed, whitespace collapsed
    """
    if not html_str or not html_str.strip():
        return ''
    soup = BeautifulSoup(html_str, 'html.parser')
    return soup.get_text(separator=' ', strip=True)


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
    cache: CacheManager,
    feed_url: str,
    max_age_hours: Optional[int] = None,
    priority_sources: Optional[List[str]] = None
) -> Optional[Dict]:
    """
    Check if an entry matches any community and hasn't been seen.
    
    Args:
        entry: feedparser entry object
        communities: List of community names to match
        cache: CacheManager instance
        feed_url: URL of the feed this entry came from
        max_age_hours: Optional maximum age in hours (None = no filtering)
        priority_sources: Optional list of priority source URLs
        
    Returns:
        Dictionary with match data if found, None otherwise:
        {
            'communities': List[str],  # All matching communities
            'title': str,
            'pub_date': str,
            'pub_datetime': datetime,  # For relative time calculation
            'link': str,
            'source': str,
            'excerpt': str,
            'match_location': str,  # 'title' or 'summary'
            'is_priority': bool
        }
    """
    link = entry.get('link')
    if not link:
        return None
    
    # Skip if already seen
    if cache.has_seen(link):
        return None
    
    # Check recency filter
    pub_datetime = get_pub_datetime(entry)
    if max_age_hours and pub_datetime:
        age = datetime.now(ZoneInfo("America/Los_Angeles")) - pub_datetime
        if age > timedelta(hours=max_age_hours):
            logger.debug(f"Skipping article older than {max_age_hours} hours: {link}")
            return None
    
    title = entry.get('title', '').strip()
    summary_raw = (entry.get('summary', '') or '').strip()
    summary_plain = strip_html(summary_raw).strip()
    title_lower = title.lower()
    summary_lower = summary_plain.lower()
    combined = (title + " " + summary_plain).lower()
    
    # Find all matching communities
    matching_communities = []
    match_location = None
    
    for community in communities:
        # Escape special regex characters and use word boundaries
        pattern = r'\b' + re.escape(community.lower()) + r'\b'
        if re.search(pattern, combined):
            matching_communities.append(community)
            # Determine if match is in title (more relevant) or summary
            if not match_location and re.search(pattern, title_lower):
                match_location = 'title'
            elif not match_location:
                match_location = 'summary'
    
    if not matching_communities:
        return None
    
    # Extract excerpt (plain-text summary, or title if no summary)
    excerpt = summary_plain if summary_plain else title
    # Will be truncated in notifier based on config
    
    pub_date = format_pub_date(entry)
    source = extract_source_name(feed_url)
    is_priority = is_priority_source(feed_url, priority_sources)
    
    return {
        'communities': matching_communities,
        'title': title,
        'pub_date': pub_date,
        'pub_datetime': pub_datetime,
        'link': link,
        'source': source,
        'excerpt': excerpt,
        'match_location': match_location or 'summary',
        'is_priority': is_priority
    }


def scrape_and_notify(
    feed_urls: List[str],
    communities: List[str],
    webhook_url: str,
    cache: CacheManager,
    max_age_hours: Optional[int] = None,
    priority_sources: Optional[List[str]] = None,
    excerpt_length: int = 250,
    group_stories: bool = True,
    similarity_threshold: float = 0.6
) -> int:
    """
    Scrape RSS feeds and send notifications for matching articles.
    
    Args:
        feed_urls: List of RSS feed URLs to check
        communities: List of community names to match
        webhook_url: Slack webhook URL
        cache: CacheManager instance
        max_age_hours: Optional maximum age in hours for articles
        priority_sources: Optional list of priority source URLs
        excerpt_length: Maximum length for article excerpts (default: 250)
        group_stories: Whether to group similar stories (default: True)
        similarity_threshold: Minimum similarity to group stories (default: 0.6)
        
    Returns:
        Number of articles posted
    """
    # Collect all matches first
    all_matches: List[Dict] = []
    
    for feed_url in feed_urls:
        feed = fetch_feed(feed_url)
        
        if not feed:
            continue
        
        entry_count = len(feed.entries) if feed.entries else 0
        logger.info(f"Checking {feed_url} → {entry_count} entries")
        
        if entry_count == 0:
            continue
        
        for entry in feed.entries:
            match = check_entry_matches(
                entry, 
                communities, 
                cache, 
                feed_url,
                max_age_hours=max_age_hours,
                priority_sources=priority_sources
            )
            
            if match:
                communities_str = ', '.join(match['communities'])
                logger.info(f"Match found for {communities_str}: {match['title']}")
                all_matches.append(match)
        
        # Be respectful - delay between feeds
        if feed_url != feed_urls[-1]:  # Don't delay after last feed
            sleep(FEED_DELAY)
    
    if not all_matches:
        logger.info("No matching articles found")
        return 0
    
    posted_count = 0
    
    # Group stories if enabled
    if group_stories and len(all_matches) > 1:
        grouper = StoryGrouper(similarity_threshold=similarity_threshold)
        groups = grouper.group_stories(all_matches)
        
        for group in groups:
            if len(group) > 1:
                # Send grouped notification for multiple articles
                if send_grouped_notification(
                    webhook_url,
                    group,
                    excerpt_length
                ):
                    # Mark all URLs in group as seen
                    for article in group:
                        cache.mark_seen(article['link'])
                    posted_count += len(group)
                    logger.info(f"Posted grouped notification for {len(group)} articles")
            else:
                # Single article - send individual notification
                article = group[0]
                if send_slack_notification(
                    webhook_url,
                    article['communities'],
                    article['title'],
                    article['pub_date'],
                    article['pub_datetime'],
                    article['link'],
                    article['source'],
                    article['excerpt'],
                    article['match_location'],
                    article['is_priority'],
                    excerpt_length
                ):
                    cache.mark_seen(article['link'])
                    posted_count += 1
    else:
        # Grouping disabled or only one match - send individual notifications
        for match in all_matches:
            if send_slack_notification(
                webhook_url,
                match['communities'],
                match['title'],
                match['pub_date'],
                match['pub_datetime'],
                match['link'],
                match['source'],
                match['excerpt'],
                match['match_location'],
                match['is_priority'],
                excerpt_length
            ):
                cache.mark_seen(match['link'])
                posted_count += 1
    
    return posted_count
