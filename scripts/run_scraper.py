#!/usr/bin/env python3
"""
Main entry point for San Diego County news scraper.

Usage:
    python run_scraper.py --region north
    python run_scraper.py --region south
"""
import os
import sys
import argparse
import logging
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Install with: pip install pyyaml")
    sys.exit(1)

# Add parent directory to path to import src modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.scraper import scrape_and_notify
from src.cache_manager import CacheManager


def setup_logging(debug: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def load_config(config_path: Path) -> dict:
    """
    Load configuration from YAML file.
    
    Args:
        config_path: Path to YAML config file
        
    Returns:
        Configuration dictionary
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    return config


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='San Diego County News Scraper',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        '--region',
        choices=['north', 'south'],
        required=True,
        help='Region to scrape (north or south)'
    )
    parser.add_argument(
        '--config-dir',
        type=Path,
        default=Path(__file__).parent.parent / 'config',
        help='Directory containing config files (default: config/)'
    )
    parser.add_argument(
        '--cache-dir',
        type=Path,
        default=Path(__file__).parent.parent / '.cache',
        help='Directory for cache files (default: .cache/)'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )
    
    args = parser.parse_args()
    
    setup_logging(args.debug)
    logger = logging.getLogger(__name__)
    
    # Load configuration
    config_file = args.config_dir / f"{args.region}_county.yaml"
    try:
        config = load_config(config_file)
        logger.info(f"Loaded configuration for {config['region']} region")
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        sys.exit(1)
    
    # Get webhook URL from environment
    webhook_env_var = config.get('webhook_env_var', 'SLACK_WEBHOOK_URL')
    webhook_url = os.getenv(webhook_env_var)
    
    if not webhook_url:
        logger.error(f"Environment variable {webhook_env_var} is not set. Exiting.")
        sys.exit(1)
    
    logger.debug(f"Using webhook from {webhook_env_var}")
    
    # Get communities and feeds from config
    communities = config.get('communities', [])
    feeds = config.get('feeds', [])
    
    if not communities:
        logger.error("No communities configured")
        sys.exit(1)
    if not feeds:
        logger.error("No feeds configured")
        sys.exit(1)
    
    # Get optional configuration settings
    max_age_hours = config.get('max_age_hours')
    priority_sources = config.get('priority_sources')
    excerpt_length = config.get('excerpt_length', 250)
    
    logger.info(f"Monitoring {len(communities)} communities across {len(feeds)} feeds")
    if max_age_hours:
        logger.info(f"Filtering articles to last {max_age_hours} hours")
    if priority_sources:
        logger.info(f"Priority sources: {len(priority_sources)} configured")
    
    # Initialize cache manager
    cache = CacheManager(str(args.cache_dir), region=args.region)
    
    # Run scraper
    try:
        posted_count = scrape_and_notify(
            feed_urls=feeds,
            communities=communities,
            webhook_url=webhook_url,
            cache=cache,
            max_age_hours=max_age_hours,
            priority_sources=priority_sources,
            excerpt_length=excerpt_length
        )
        
        logger.info(f"Posted {posted_count} new articles")
        
        # Save cache
        cache.save()
        logger.info("Cache saved successfully")
        
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        cache.save()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        cache.save()  # Try to save cache even on error
        sys.exit(1)


if __name__ == "__main__":
    main()
