# San Diego County News Scraper

A Python-based RSS feed scraper that monitors San Diego County news sources and posts relevant articles to Slack. Supports separate monitoring for North County and South Bay, plus an optional Friday North County weekly briefing.

## Features

- **Dual Region Support**: Separate monitoring for North County and South Bay
- **Configurable**: YAML-based configuration for communities and feeds
- **Story grouping**: Groups similar coverage from multiple outlets
- **AI assists** (optional, needs `OPENAI_API_KEY`): summaries, urgency labels, semantic grouping, relevance when place names are missing
- **Weekly roundup**: Friday North County briefing built from a weekly archive + live RSS scan
- **Error Handling**: Timeouts, retries, and graceful feed failures
- **Cache Management**: Per-region seen-URL cache with atomic writes and size limits
- **GitHub Actions**: Hourly scraper + Friday weekly workflow

## Requirements

- Python 3.8+
- pip

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd "SD County news scrapers"
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Configuration

### Environment Variables

- **North County**: `SLACK_WEBHOOK_NORTH`
- **South Bay**: `SLACK_WEBHOOK_URL`
- **Weekly (optional)**: `SLACK_WEBHOOK_NORTH_WEEKLY` (falls back to `SLACK_WEBHOOK_NORTH`)
- **AI features**: `OPENAI_API_KEY`

Example:
```bash
export SLACK_WEBHOOK_NORTH="https://hooks.slack.com/services/YOUR/NORTH/WEBHOOK"
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/SOUTH/WEBHOOK"
export OPENAI_API_KEY="sk-..."
```

### Configuration Files

Edit the YAML files in the `config/` directory:

- `config/north_county.yaml` — North County communities, feeds, AI toggles
- `config/south_county.yaml` — South Bay communities, feeds, AI toggles

Common options: `max_age_hours`, `priority_sources`, `excerpt_length`, `group_stories`, `similarity_threshold`, `slack_unfurl_links`, `exclude_syndicated_from`, and the `use_*` AI flags.

Set `slack_unfurl_links: false` to disable Slack link/media previews.

## Usage

```bash
# North County
python scripts/run_scraper.py --region north

# South Bay
python scripts/run_scraper.py --region south

# Friday-style weekly briefing (North County)
python scripts/run_weekly_roundup.py
```

### Options (`run_scraper.py`)

- `--region` (required): `north` or `south`
- `--config-dir`: Directory containing config files (default: `config/`)
- `--cache-dir`: Directory for cache files (default: `.cache/`)
- `--debug`: Enable debug logging

## Scheduled Execution

GitHub Actions:

- `.github/workflows/scraper.yml` — hourly North and South scrapes
- `.github/workflows/north-county-weekly.yml` — Friday North County briefing

See [WEEKLY_ROUNDUP_SETUP.md](WEEKLY_ROUNDUP_SETUP.md) for weekly setup and secrets.

Local cron example:
```bash
0 * * * * cd /path/to/scraper && python scripts/run_scraper.py --region north
0 * * * * cd /path/to/scraper && python scripts/run_scraper.py --region south
```

## Project Structure

```
SD County news scrapers/
├── README.md
├── WEEKLY_ROUNDUP_SETUP.md
├── requirements.txt
├── config/
│   ├── north_county.yaml
│   └── south_county.yaml
├── src/
│   ├── scraper.py
│   ├── cache_manager.py
│   ├── notifier.py
│   ├── story_grouper.py
│   ├── llm.py
│   ├── ai_helpers.py
│   └── weekly_archive.py
├── scripts/
│   ├── run_scraper.py
│   └── run_weekly_roundup.py
└── .github/workflows/
    ├── scraper.yml
    └── north-county-weekly.yml
```

## How It Works

1. Load YAML config for the region
2. Fetch RSS feeds with timeout and a polite User-Agent
3. Match community names (word boundaries + exclusions)
4. Skip already-seen URLs and articles outside `max_age_hours`
5. Optionally assign communities via AI, group similar stories, and enrich Slack text
6. Post to Slack and update the seen-URL cache
7. (North) Archive matches for the Friday weekly briefing

## Cache Management

- Per-region files: `.cache/seen_north.txt`, `.cache/seen_south.txt`
- URLs are normalized (scheme + host + path) so tracking params do not create duplicates
- Newest entries are kept when the cache exceeds 10,000 URLs
- Writes are atomic (temp file + replace)
- North County also maintains `.cache/weekly_north.json` for the weekly roundup

## Troubleshooting

### "Environment variable not set"
Ensure the Slack webhook env var named in the YAML (`webhook_env_var`) is exported.

### "No articles posted"
Check logs for feed errors, confirm community names appear in titles/summaries, and verify the cache is not already marking items as seen.

### Import errors
```bash
pip install -r requirements.txt
```
