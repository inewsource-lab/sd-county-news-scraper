"""Slack notification handling."""
import logging
import requests
from typing import Optional
from time import sleep

logger = logging.getLogger(__name__)

# Request timeout in seconds
REQUEST_TIMEOUT = 10
# Maximum retry attempts
MAX_RETRIES = 3
# Base delay for exponential backoff (seconds)
RETRY_DELAY_BASE = 2


def send_slack_notification(webhook_url: str, community: str, title: str, pub_date: str, link: str) -> bool:
    """
    Send notification to Slack webhook.
    
    Args:
        webhook_url: Slack webhook URL
        community: Community name
        title: Article title
        pub_date: Publication date string
        link: Article URL
        
    Returns:
        True if successful, False otherwise
    """
    message = (
        f":bell: *{community}* — {title}\n"
        f"_Published: {pub_date}_\n"
        f"{link}"
    )
    
    payload = {"text": message}
    
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                webhook_url,
                json=payload,
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            logger.info(f"Posted to Slack: {community} - {title}")
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
