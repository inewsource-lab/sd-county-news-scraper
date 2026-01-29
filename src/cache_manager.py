"""Cache management for tracking seen articles."""
import os
from pathlib import Path
from typing import Set
from collections import deque
import logging

logger = logging.getLogger(__name__)

# Maximum number of entries to keep in cache (prevents unbounded growth)
MAX_CACHE_SIZE = 10000


class CacheManager:
    """Manages the cache of seen article URLs."""
    
    def __init__(self, cache_dir: str, region: str = ""):
        """
        Initialize cache manager.
        
        Args:
            cache_dir: Base directory for cache files
            region: Region identifier (e.g., 'north', 'south') for separate caches
        """
        self.region = region
        self.cache_dir = Path(cache_dir)
        cache_name = f"seen_{region}.txt" if region else "seen.txt"
        self.seen_file = self.cache_dir / cache_name
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.seen: Set[str] = self._load_cache()
        logger.info(f"Loaded {len(self.seen)} entries from cache")
    
    def _load_cache(self) -> Set[str]:
        """Load seen URLs from cache file."""
        if not self.seen_file.exists():
            return set()
        
        try:
            with open(self.seen_file, 'r', encoding='utf-8') as f:
                # Use deque to limit memory usage for very large files
                lines = deque(f, maxlen=MAX_CACHE_SIZE)
                return set(line.strip() for line in lines if line.strip())
        except Exception as e:
            logger.error(f"Error loading cache file {self.seen_file}: {e}")
            return set()
    
    def has_seen(self, url: str) -> bool:
        """Check if URL has been seen before."""
        return url in self.seen
    
    def mark_seen(self, url: str) -> None:
        """Mark URL as seen."""
        self.seen.add(url)
    
    def save(self) -> None:
        """Save cache to disk."""
        try:
            # Limit cache size to prevent unbounded growth
            if len(self.seen) > MAX_CACHE_SIZE:
                # Keep most recent entries (convert to list, take last N)
                seen_list = list(self.seen)
                self.seen = set(seen_list[-MAX_CACHE_SIZE:])
                logger.warning(f"Cache size exceeded {MAX_CACHE_SIZE}, trimmed to {len(self.seen)} entries")
            
            with open(self.seen_file, 'w', encoding='utf-8') as f:
                for url in sorted(self.seen):  # Sort for consistent file format
                    f.write(url + '\n')
            logger.debug(f"Saved {len(self.seen)} entries to cache")
        except Exception as e:
            logger.error(f"Error saving cache file {self.seen_file}: {e}")
