# San Diego County News Scraper

A Python-based RSS feed scraper that monitors San Diego County news sources and posts relevant articles to Slack channels. Supports separate monitoring for North County and South Bay regions.

## Features

- **Dual Region Support**: Separate monitoring for North County and South Bay
- **Configurable**: YAML-based configuration for communities and feeds
- **Error Handling**: Retry logic, timeouts, and graceful error handling
- **Cache Management**: Prevents duplicate posts with size-limited cache
- **Logging**: Structured logging with configurable levels
- **Separate Slack Channels**: Each region posts to its own Slack webhook/channel

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

Set the following environment variables with your Slack webhook URLs:

- **North County**: `SLACK_WEBHOOK_NORTH`
- **South Bay**: `SLACK_WEBHOOK_URL`

Example:
```bash
export SLACK_WEBHOOK_NORTH="https://hooks.slack.com/services/YOUR/NORTH/WEBHOOK"
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/SOUTH/WEBHOOK"
```

### Configuration Files

Edit the YAML files in the `config/` directory to customize:

- **Communities**: List of community names to monitor
- **Feeds**: RSS feed URLs to scrape

- `config/north_county.yaml` - North County configuration
- `config/south_county.yaml` - South Bay configuration

## Usage

Run the scraper for a specific region:

```bash
# North County
python scripts/run_scraper.py --region north

# South Bay
python scripts/run_scraper.py --region south
```

### Options

- `--region` (required): Region to scrape (`north` or `south`)
- `--config-dir`: Directory containing config files (default: `config/`)
- `--cache-dir`: Directory for cache files (default: `.cache/`)
- `--debug`: Enable debug logging

### Examples

```bash
# Run with debug logging
python scripts/run_scraper.py --region north --debug

# Use custom config directory
python scripts/run_scraper.py --region south --config-dir /path/to/configs
```

## Scheduled Execution

To run automatically, set up a cron job or scheduled task:

```bash
# Run every hour
0 * * * * cd /path/to/scraper && python scripts/run_scraper.py --region north
0 * * * * cd /path/to/scraper && python scripts/run_scraper.py --region south
```

Or use a task scheduler like `systemd` timers on Linux or launchd on macOS.

## Project Structure

```
SD County news scrapers/
├── README.md
├── requirements.txt
├── .gitignore
├── config/
│   ├── north_county.yaml
│   └── south_county.yaml
├── src/
│   ├── __init__.py
│   ├── scraper.py          # Core scraping logic
│   ├── cache_manager.py   # Cache management
│   └── notifier.py        # Slack notifications
└── scripts/
    └── run_scraper.py       # Main entry point
```

## How It Works

1. **Load Configuration**: Reads YAML config for the specified region
2. **Fetch Feeds**: Scrapes RSS feeds with error handling and retries
3. **Match Communities**: Checks article titles/summaries against community keywords
4. **Check Cache**: Skips articles that have already been posted
5. **Post to Slack**: Sends notifications to the configured webhook
6. **Update Cache**: Saves seen articles to prevent duplicates

## Cache Management

The scraper maintains a cache of seen article URLs to prevent duplicate posts. The cache:
- Is stored per region (separate files for north/south)
- Has a maximum size limit (10,000 entries)
- Automatically trims old entries when limit is reached
- Is saved after each run

## Error Handling

- **Feed Fetching**: Continues to next feed if one fails
- **Slack Posting**: Retries up to 3 times with exponential backoff
- **Network Timeouts**: 10-15 second timeouts prevent hanging
- **Logging**: All errors are logged for debugging

## Troubleshooting

### "Environment variable not set"
- Ensure `SLACK_WEBHOOK_NORTH` or `SLACK_WEBHOOK_URL` is set
- Check that the variable is exported in your shell environment

### "Config file not found"
- Verify config files exist in `config/` directory
- Check file names: `north_county.yaml` and `south_county.yaml`

### "No articles posted"
- Check logs for feed fetching errors
- Verify community names match article content (case-insensitive)
- Check cache - articles may have already been posted

### Import errors
- Ensure all dependencies are installed: `pip install -r requirements.txt`
- Check Python version (3.8+ required)

## License

[Your license here]

## Contributing

[Contributing guidelines here]
