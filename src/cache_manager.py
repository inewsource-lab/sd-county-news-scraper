"""Cache management for tracking seen articles."""
import json
import os
from pathlib import Path
from typing import Set
from urllib.parse import urlparse, urlunparse
import logging

logger = logging.getLogger(__name__)

# #region agent log
DEBUG_LOG_PATH = Path(__file__).resolve().parent.parent / ".cursor" / "debug.log"
def _debug_log(location: str, message: str, data: dict, hypothesis_id: str, run_id: str = "run1"):
    try:
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps({"location": location, "message": message, "data": data, "hypothesisId": hypothesis_id, "runId": run_id, "timestamp": __import__("time").time()}) + "\n")
    except Exception:
        pass
# #endregion

# Maximum number of entries to keep in cache (prevents unbounded growth)
MAX_CACHE_SIZE = 10000


def _normalize_url(url: str) -> str:
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
        # #region agent log
        _debug_log("CacheManager.__init__", "cache_init", {"seen_file_absolute": str(self.seen_file.resolve()), "loaded_count": len(self.seen), "seen_file_exists": self.seen_file.exists()}, "H1")
        # #endregion
    
    def _load_cache(self) -> Set[str]:
        """Load seen URLs from cache file (all lines; normalized for consistent dedup)."""
        if not self.seen_file.exists():
            return set()
        
        try:
            with open(self.seen_file, 'r', encoding='utf-8') as f:
                return set(
                    _normalize_url(line.strip())
                    for line in f
                    if line.strip()
                )
        except Exception as e:
            logger.error(f"Error loading cache file {self.seen_file}: {e}")
            return set()
    
    def has_seen(self, url: str) -> bool:
        """Check if URL has been seen before (uses normalized URL for comparison)."""
        # #region agent log
        key = _normalize_url(url)
        result = key in self.seen
        _debug_log("CacheManager.has_seen", "has_seen_check", {"raw_url": url[:80] + "..." if len(url) > 80 else url, "normalized_key": key[:80] + "..." if len(key) > 80 else key, "result": result}, "H2")
        return result
        # #endregion
    
    def mark_seen(self, url: str) -> None:
        """Mark URL as seen (stores normalized URL)."""
        key = _normalize_url(url)
        if key:
            self.seen.add(key)
            # #region agent log
            _debug_log("CacheManager.mark_seen", "mark_seen", {"raw_url": url[:80] + "..." if len(url) > 80 else url, "normalized_key": key[:80] + "..." if len(key) > 80 else key}, "H2")
            # #endregion
    
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
            # #region agent log
            _debug_log("CacheManager.save", "cache_saved", {"seen_file_absolute": str(self.seen_file.resolve()), "saved_count": len(self.seen)}, "H4")
            # #endregion
        except Exception as e:
            logger.error(f"Error saving cache file {self.seen_file}: {e}")
            # #region agent log
            _debug_log("CacheManager.save", "cache_save_error", {"error": str(e), "seen_file": str(self.seen_file)}, "H4")
            # #endregion
