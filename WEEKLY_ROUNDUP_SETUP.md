# North County Weekly Roundup

This adds a Friday North County news briefing while keeping the existing hourly scraper in place.

## What it does

The modern North County hourly job (`scripts/run_scraper.py --region north`) now also saves a compact copy of each matched story in `.cache/weekly_north.json`. That archive is stored in the same GitHub Actions cache you already use for seen URLs.

Every Friday, the weekly workflow:

1. Restores the latest North County cache, including the weekly story archive.
2. Loads North County stories discovered during the previous 7 days.
3. Also scans the live RSS feeds as a safety net for very recent stories and first-run installs.
4. Uses the existing geographic matching and AI relevance checks.
5. Groups duplicate coverage with the existing story-grouping code.
6. Sends the grouped developments to OpenAI for one reporter-focused briefing.
7. Posts that briefing to Slack.

Archiving stories throughout the week matters because busy RSS feeds may no longer expose Monday or Tuesday stories by Friday.

## Secrets

The workflow uses:

- `OPENAI_API_KEY`
- `SLACK_WEBHOOK_NORTH` as the existing fallback

### Recommended: give the weekly roundup its own Slack channel

If the reporter should receive only the weekly briefing, create an incoming webhook for that Slack channel and save it in GitHub as:

- `SLACK_WEBHOOK_NORTH_WEEKLY`

The weekly job uses that webhook first. If it is not present, it automatically posts to `SLACK_WEBHOOK_NORTH`.

## Test before Friday

In GitHub:

1. Upload/commit the updated files.
2. Let the regular North County scraper run at least once so it creates `.cache/weekly_north.json`.
3. Open **Actions**.
4. Select **North County Weekly Roundup**.
5. Click **Run workflow**.
6. Confirm one roundup appears in the intended Slack channel.

A manual test also performs a live seven-day RSS scan, so it can work even before the archive has accumulated a full week.

## Schedule

The workflow runs at `21:00 UTC` every Friday: 2 p.m. Pacific during daylight-saving time and 1 p.m. Pacific during standard time.

## Reliability safeguards

- AI relevance and verification are split into bounded batches so a busy seven-day window cannot overflow one request.
- Multi-word communities such as `San Marcos` and `Rancho Santa Fe` are parsed correctly from batched AI responses.
- Embeddings are also requested in bounded batches and fall back to title grouping if an embeddings call fails.
- RSS entries with an `updated` date but no `published` date can still be included.
- Slack webhook posting retries transient failures three times.
- The source packet is capped to fit comfortably inside the current `gpt-4o-mini` context window.
- RSS titles/excerpts are treated as untrusted source material in the final curation prompt.

## Files added

- `.github/workflows/north-county-weekly.yml`
- `scripts/run_weekly_roundup.py`
- `src/weekly_archive.py`
- `WEEKLY_ROUNDUP_SETUP.md`

## Existing files changed

- `scripts/run_scraper.py` — tells the modern North County hourly scraper to maintain the weekly archive.
- `src/scraper.py` — optionally archives matched stories before Slack posting.
- `src/ai_helpers.py` — fixes parsing of multi-word community names and numbered yes/no responses.

## Existing older workflows

The weekly archive is populated by the North County job in `scraper.yml`. Legacy root scripts (`rss_notify.py`, `rss_notify_north.py`) have been removed; use `scripts/run_scraper.py` only.
