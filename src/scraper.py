"""Core RSS feed scraping logic."""
import logging
import re
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Set, Optional, Tuple, Dict, Any
from time import sleep
from urllib.parse import urlparse

from .cache_manager import CacheManager
from .notifier import send_slack_notification, send_grouped_notification
from .story_grouper import StoryGrouper
from . import llm
from . import ai_helpers

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


def is_syndicated_from(entry, exclude_list: Optional[List[str]]) -> bool:
    """
    Return True if the entry appears to be syndicated from one of the excluded sources.
    Checks author field and start of summary/title for byline phrases (e.g. AP, CalMatters).
    """
    if not exclude_list:
        return False
    author = (entry.get('author') or '').strip().lower()
    title = (entry.get('title') or '').strip()
    summary_raw = (entry.get('summary') or '').strip()
    summary_plain = strip_html(summary_raw).strip()
    # Check first ~200 chars of summary (byline often at start) and full title
    byline_zone = (summary_plain[:200] + ' ' + title).lower()
    for phrase in exclude_list:
        if not phrase or not phrase.strip():
            continue
        p = phrase.strip().lower()
        if p in author:
            return True
        if p in byline_zone:
            return True
    return False


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
    priority_sources: Optional[List[str]] = None,
    community_exclusions: Optional[Dict[str, List[str]]] = None,
    exclude_syndicated_from: Optional[List[str]] = None,
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
        community_exclusions: Optional map community -> list of phrases; if any phrase
            appears in the text, do not count that community (e.g. Vista -> ["Chula Vista"])
        exclude_syndicated_from: Optional list of syndication source names (e.g. AP, CalMatters);
            entries with author/byline matching any are excluded.
        
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
    
    # Skip syndicated content (e.g. AP, CalMatters) when excluded
    if exclude_syndicated_from and is_syndicated_from(entry, exclude_syndicated_from):
        logger.debug(f"Skipping syndicated article: {entry.get('title', '')[:50]}")
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
            # Apply exclusions: e.g. don't match "Vista" when "Chula Vista" appears
            if community_exclusions and community in community_exclusions:
                skip = False
                for phrase in community_exclusions[community]:
                    if re.search(r'\b' + re.escape(phrase.lower()) + r'\b', combined):
                        skip = True
                        break
                if skip:
                    continue
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


def _build_match_from_entry(entry, feed_url: str, matching_communities: List[str], match_location: str, priority_sources: Optional[List[str]] = None) -> Dict:
    """Build a match dict from an entry and given communities (e.g. from AI relevance)."""
    title = entry.get('title', '').strip()
    summary_raw = (entry.get('summary', '') or '').strip()
    summary_plain = strip_html(summary_raw).strip()
    excerpt = summary_plain if summary_plain else title
    pub_datetime = get_pub_datetime(entry)
    return {
        'communities': matching_communities,
        'title': title,
        'pub_date': format_pub_date(entry),
        'pub_datetime': pub_datetime,
        'link': entry.get('link', ''),
        'source': extract_source_name(feed_url),
        'excerpt': excerpt,
        'match_location': match_location,
        'is_priority': is_priority_source(feed_url, priority_sources),
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
    similarity_threshold: float = 0.6,
    unfurl_links: bool = False,
    community_exclusions: Optional[Dict[str, List[str]]] = None,
    exclude_syndicated_from: Optional[List[str]] = None,
    use_semantic_grouping: bool = False,
    semantic_similarity_threshold: float = 0.78,
    use_ai_summaries: bool = False,
    use_ai_relevance: bool = False,
    ai_relevance_exclusion_phrases: Optional[List[str]] = None,
    use_urgency: bool = False,
    use_group_summary: bool = False,
    use_suggested_angle: bool = False,
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
        unfurl_links: If False, disable Slack link/media unfurling (default: True)
        community_exclusions: Optional map community -> list of phrases to exclude (e.g. Vista -> ["Chula Vista"])
        exclude_syndicated_from: Optional list of syndication sources to exclude (e.g. AP, CalMatters)
        use_semantic_grouping: Use embedding similarity for grouping (default: False)
        semantic_similarity_threshold: Cosine threshold when using semantic grouping (default: 0.78)
        use_ai_summaries: Add one-sentence AI summary per article (default: False)
        use_ai_relevance: Assign communities via AI when not in text (default: False)
        ai_relevance_exclusion_phrases: Skip AI relevance if article mentions these places (other region)
        use_urgency: Classify breaking/developing/routine (default: False)
        use_group_summary: AI-synthesized summary for grouped stories (default: False)
        use_suggested_angle: AI-suggested follow-up angle for groups (default: False)
        
    Returns:
        Number of articles posted
    """
    # Collect all matches first; optionally collect no-match entries for AI relevance
    all_matches: List[Dict] = []
    ai_relevance_candidates: List[Tuple[Any, str]] = []  # (entry, feed_url)
    
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
                priority_sources=priority_sources,
                community_exclusions=community_exclusions,
                exclude_syndicated_from=exclude_syndicated_from,
            )
            
            if match:
                communities_str = ', '.join(match['communities'])
                logger.info(f"Match found for {communities_str}: {match['title']}")
                all_matches.append(match)
            elif use_ai_relevance and llm.is_available() and not (exclude_syndicated_from and is_syndicated_from(entry, exclude_syndicated_from)):
                # Only add if not too old (AI path bypasses check_entry_matches age filter)
                pub_datetime = get_pub_datetime(entry)
                if max_age_hours and pub_datetime:
                    age = datetime.now(ZoneInfo("America/Los_Angeles")) - pub_datetime
                    if age > timedelta(hours=max_age_hours):
                        continue  # Skip old articles
                # Skip if article mentions cross-region places (e.g. National City in North County)
                if ai_relevance_exclusion_phrases:
                    title = entry.get('title', '').strip()
                    summary_raw = (entry.get('summary', '') or '').strip()
                    summary_plain = strip_html(summary_raw).strip()
                    combined = (title + " " + summary_plain).lower()
                    for phrase in ai_relevance_exclusion_phrases:
                        if phrase and phrase.strip():
                            pattern = r'\b' + re.escape(phrase.lower()) + r'\b'
                            if re.search(pattern, combined):
                                logger.debug(f"Skipping AI relevance: article mentions '{phrase}': {entry.get('title', '')[:50]}")
                                break
                    else:
                        ai_relevance_candidates.append((entry, feed_url))
                else:
                    ai_relevance_candidates.append((entry, feed_url))
    
    # AI relevance: try to assign communities to non-matching entries
    if use_ai_relevance and ai_relevance_candidates and llm.is_available():
        candidates_titles = []
        candidates_excerpts = []
        for entry, _ in ai_relevance_candidates:
            title = entry.get('title', '').strip()
            summary_raw = (entry.get('summary', '') or '').strip()
            summary_plain = strip_html(summary_raw).strip()
            candidates_titles.append(title)
            candidates_excerpts.append(summary_plain if summary_plain else title)
        candidates_pairs = list(zip(candidates_titles, candidates_excerpts))
        relevance_results = ai_helpers.batch_ai_relevance(candidates_pairs, communities)
        # Second-pass AI check: verify each AI-assigned community before accepting
        to_verify = []
        to_verify_entries = []
        for (entry, feed_url), ai_communities in zip(ai_relevance_candidates, relevance_results):
            if not ai_communities:
                continue
            title = entry.get('title', '').strip()
            summary_raw = (entry.get('summary', '') or '').strip()
            summary_plain = strip_html(summary_raw).strip()
            excerpt = summary_plain if summary_plain else title
            to_verify.append((title, excerpt, ai_communities[0]))
            to_verify_entries.append((entry, feed_url, ai_communities))
        if to_verify:
            verified = ai_helpers.batch_verify_community_relevance(to_verify)
            for (entry, feed_url, ai_communities), passes in zip(to_verify_entries, verified):
                if not passes:
                    logger.debug(f"AI verification rejected (not specifically about {ai_communities[0]}): {entry.get('title', '')[:50]}")
                    continue
                m = _build_match_from_entry(entry, feed_url, ai_communities, 'ai_relevance', priority_sources)
                if cache.has_seen(m['link']):
                    continue
                logger.info(f"AI relevance match for {', '.join(ai_communities)}: {m['title']}")
                all_matches.append(m)
    
    if not all_matches:
        logger.info("No matching articles found")
        return 0
    
    # Urgency: classify each match
    if use_urgency and llm.is_available():
        for match in all_matches:
            match['urgency'] = ai_helpers.classify_urgency(match['title'], match.get('excerpt', ''))
    else:
        for match in all_matches:
            match['urgency'] = 'routine'
    
    # AI summaries for single articles (used when we send individual notifications)
    if use_ai_summaries and llm.is_available():
        for match in all_matches:
            summary = ai_helpers.summarize_article(match['title'], match.get('excerpt', ''))
            match['ai_summary'] = summary
    else:
        for match in all_matches:
            match['ai_summary'] = None
    
    # Embeddings for semantic grouping
    embedding_vectors = None
    if use_semantic_grouping and llm.is_available() and len(all_matches) > 1:
        texts = [m['title'] + ' ' + (m.get('excerpt') or '')[:500] for m in all_matches]
        embedding_vectors = llm.get_embeddings(texts)
    
    # Sort all_matches by urgency (breaking first) so grouped order reflects it
    urgency_order = {'breaking': 0, 'developing': 1, 'routine': 2}
    all_matches.sort(key=lambda m: (urgency_order.get(m.get('urgency', 'routine'), 2), -(m['pub_datetime'].timestamp() if m.get('pub_datetime') else 0)))
    
    posted_count = 0
    group_threshold = semantic_similarity_threshold if (use_semantic_grouping and embedding_vectors) else similarity_threshold
    
    # Group stories if enabled
    if group_stories and len(all_matches) > 1:
        grouper = StoryGrouper(similarity_threshold=group_threshold)
        groups = grouper.group_stories(all_matches, embedding_vectors=embedding_vectors)
        
        for group in groups:
            if len(group) > 1:
                group_summary = None
                suggested_angle = None
                if (use_group_summary or use_suggested_angle) and llm.is_available():
                    group_summary, suggested_angle = ai_helpers.group_summary_and_angle(group)
                if send_grouped_notification(
                    webhook_url,
                    group,
                    excerpt_length,
                    unfurl_links,
                    group_summary=group_summary,
                    suggested_angle=suggested_angle,
                ):
                    for article in group:
                        cache.mark_seen(article['link'])
                    posted_count += len(group)
                    logger.info(f"Posted grouped notification for {len(group)} articles")
            else:
                article = group[0]
                excerpt = article.get('ai_summary') or article.get('excerpt', '')
                if send_slack_notification(
                    webhook_url,
                    article['communities'],
                    article['title'],
                    article['pub_date'],
                    article['pub_datetime'],
                    article['link'],
                    article['source'],
                    excerpt,
                    article['match_location'],
                    article['is_priority'],
                    excerpt_length,
                    unfurl_links,
                    urgency=article.get('urgency'),
                ):
                    cache.mark_seen(article['link'])
                    posted_count += 1
    else:
        for match in all_matches:
            excerpt = match.get('ai_summary') or match.get('excerpt', '')
            if send_slack_notification(
                webhook_url,
                match['communities'],
                match['title'],
                match['pub_date'],
                match['pub_datetime'],
                match['link'],
                match['source'],
                excerpt,
                match['match_location'],
                match['is_priority'],
                excerpt_length,
                unfurl_links,
                urgency=match.get('urgency'),
            ):
                cache.mark_seen(match['link'])
                posted_count += 1
    
    return posted_count
