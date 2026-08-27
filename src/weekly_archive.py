"""Small persistent archive used to build weekly North County roundups.

The hourly scraper already discovers matching stories while they are fresh in RSS.
This module stores a compact copy of those matches in the existing .cache folder so
Friday's roundup is not limited by how many items an RSS feed still exposes.
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
PACIFIC = ZoneInfo("America/Los_Angeles")

_FIELDS = (
    "communities",
    "title",
    "pub_date",
    "link",
    "source",
    "excerpt",
    "match_location",
    "is_priority",
)


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=PACIFIC)
        return dt.astimezone(PACIFIC)
    except (TypeError, ValueError):
        return None


def _load_raw(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read weekly archive %s: %s", path, exc)
        return []


def update_archive(path: Path, articles: Iterable[Dict], retention_days: int = 10) -> int:
    """Merge article matches into the archive, dedupe by URL, and prune old rows."""
    path = Path(path)
    now = datetime.now(PACIFIC)
    cutoff = now - timedelta(days=retention_days)

    existing = _load_raw(path)
    by_url: Dict[str, Dict] = {}
    for item in existing:
        link = str(item.get("link") or "").strip()
        if link:
            by_url[link] = item

    for article in articles:
        link = str(article.get("link") or "").strip()
        if not link:
            continue
        row = {field: article.get(field) for field in _FIELDS}
        pub_dt = article.get("pub_datetime")
        row["pub_datetime"] = pub_dt.isoformat() if isinstance(pub_dt, datetime) else None
        row["archived_at"] = now.isoformat()
        by_url[link] = row

    kept: List[Dict] = []
    for row in by_url.values():
        # If the feed did not provide a publication date, discovery time is still
        # enough to know the item belongs to the current weekly window.
        dt = _parse_datetime(row.get("pub_datetime")) or _parse_datetime(row.get("archived_at"))
        if dt and dt >= cutoff:
            kept.append(row)

    kept.sort(
        key=lambda row: _parse_datetime(row.get("pub_datetime"))
        or _parse_datetime(row.get("archived_at"))
        or datetime.min.replace(tzinfo=PACIFIC),
        reverse=True,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    logger.info("Weekly archive now contains %s items", len(kept))
    return len(kept)


def load_archive(path: Path, lookback_hours: int = 168) -> List[Dict]:
    """Load archive rows from the requested lookback window as scraper-style dicts."""
    path = Path(path)
    cutoff = datetime.now(PACIFIC) - timedelta(hours=lookback_hours)
    results: List[Dict] = []

    for row in _load_raw(path):
        dt = _parse_datetime(row.get("pub_datetime")) or _parse_datetime(row.get("archived_at"))
        if not dt or dt < cutoff:
            continue
        item = {field: row.get(field) for field in _FIELDS}
        item["pub_datetime"] = dt
        if not item.get("pub_date") or item.get("pub_date") == "Unknown date":
            item["pub_date"] = dt.strftime("%Y-%m-%d %H:%M PT")
        item["communities"] = item.get("communities") or []
        item["is_priority"] = bool(item.get("is_priority", False))
        results.append(item)

    results.sort(key=lambda item: item["pub_datetime"], reverse=True)
    return results
