"""Cache management for tracking seen articles."""
from pathlib import Path
from typing import Dict
from urllib.parse import urlparse, urlunparse
import logging

logger = logging.getLogger(__name__)

# Maximum number of entries to keep in cache (prevents unbounded growth)
MAX_CACHE_SIZE = 10000


def normalize_url(url: str) -> str:
    """
    Normalize URL for cache key: scheme + netloc + path only (no query or fragment).
    Same article with different ?utm_source= or other params maps to the same key.
    """
    if not url or not url.strip():
        return ""
    try:
        parsed = urlparse(url.strip())
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    except Exception:
        return url.strip()


# Back-compat alias used by older imports / call sites
_normalize_url = normalize_url


class CacheManager:
    """Manages the cache of seen article URLs with insertion-order eviction."""

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
        # Dict preserves insertion order (oldest → newest). Values unused.
        self.seen: Dict[str, None] = self._load_cache()
        logger.info(f"Loaded {len(self.seen)} entries from cache")

    def _load_cache(self) -> Dict[str, None]:
        """Load seen URLs from cache file, preserving file order."""
        if not self.seen_file.exists():
            return {}

        try:
            ordered: Dict[str, None] = {}
            with open(self.seen_file, 'r', encoding='utf-8') as f:
                for line in f:
                    key = normalize_url(line.strip())
                    if key:
                        # Re-insert moves existing keys to end if duplicated
                        ordered.pop(key, None)
                        ordered[key] = None
            return ordered
        except Exception as e:
            logger.error(f"Error loading cache file {self.seen_file}: {e}")
            return {}

    def has_seen(self, url: str) -> bool:
        """Check if URL has been seen before (uses normalized URL for comparison)."""
        return normalize_url(url) in self.seen

    def mark_seen(self, url: str) -> None:
        """Mark URL as seen. Re-marking moves it to the newest end of the order."""
        key = normalize_url(url)
        if not key:
            return
        self.seen.pop(key, None)
        self.seen[key] = None

    def save(self) -> None:
        """Save cache to disk atomically, keeping the most recently marked entries."""
        try:
            if len(self.seen) > MAX_CACHE_SIZE:
                # Keep newest N (insertion order: oldest first)
                keys = list(self.seen.keys())[-MAX_CACHE_SIZE:]
                self.seen = {k: None for k in keys}
                logger.warning(
                    f"Cache size exceeded {MAX_CACHE_SIZE}, trimmed to {len(self.seen)} entries"
                )

            self.seen_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.seen_file.with_suffix(self.seen_file.suffix + ".tmp")
            with open(tmp, 'w', encoding='utf-8') as f:
                for url in self.seen.keys():
                    f.write(url + '\n')
            tmp.replace(self.seen_file)
            logger.debug(f"Saved {len(self.seen)} entries to cache")
        except Exception as e:
            logger.error(f"Error saving cache file {self.seen_file}: {e}")
