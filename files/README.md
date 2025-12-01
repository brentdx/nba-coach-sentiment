# NBA Coach Post-Game Transcript Scraper

Automatically scrapes and stores transcripts from NBA coach post-game press conferences across all 30 team channels, then runs sentiment analysis to detect how coaches feel about specific players.

## Features

- Searches all 30 NBA team YouTube channels + the main NBA channel
- Identifies coach post-game press conferences using keyword matching
- Extracts transcripts from YouTube's auto-generated captions
- **Sentiment analysis** on player mentions to detect:
  - Coach's attitude toward players (positive/negative/neutral)
  - Hints about future playing time changes
  - Trending sentiment shifts over time
- Stores metadata in SQLite for easy querying
- Saves full transcripts as JSON files
- Deduplicates videos across channels
- Supports backfilling historical data

## Quick Start

### 1. Get API Keys

**YouTube Data API** (required):
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Enable the **YouTube Data API v3**
4. Go to Credentials → Create Credentials → API Key

**Anthropic API** (optional, for better sentiment analysis):
1. Go to [Anthropic Console](https://console.anthropic.com/)
2. Create an API key

### 2. Install Dependencies

```bash
cd nba_transcripts
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env and add your API keys
```

### 4. Run

```bash
# Daily scrape (last 24 hours)
python scraper.py

# Look back more days
python scraper.py --days 3

# Backfill a date range
python scraper.py --backfill 2024-10-22 2024-11-28
```

## Sentiment Analysis

After scraping transcripts, run sentiment analysis:

```bash
# Analyze all transcripts (rule-based, fast)
python sentiment_analysis.py --analyze

# Use Claude for more accurate analysis (slower, uses API credits)
python sentiment_analysis.py --analyze --llm

# Limit to recent transcripts
python sentiment_analysis.py --analyze --limit 50
```

### Query Sentiment Data

```bash
# Get sentiment trend for a specific player
python sentiment_analysis.py --player "Jayson Tatum"

# Get team sentiment report
python sentiment_analysis.py --team "Boston Celtics"

# Find players with notable sentiment shifts
python sentiment_analysis.py --shifts

# Generate full report
python sentiment_analysis.py --report
```

### Example Output

```
📈 NOTABLE SENTIMENT SHIFTS
----------------------------------------
🔥 Payton Pritchard: IMPROVING
   Recent: +0.65 | Before: +0.22

⚠️ D'Angelo Russell: DECLINING
   Recent: -0.31 | Before: +0.15

📊 TEAM SENTIMENT SUMMARIES
----------------------------------------
Boston Celtics
  Coach favorites: Jaylen Brown, Derrick White, Payton Pritchard
  Watch list: None detected

Los Angeles Lakers
  Coach favorites: Austin Reaves, Anthony Davis
  Watch list: D'Angelo Russell
```

### Programmatic Access

```python
from sentiment_analysis import compute_player_trends, get_team_sentiment_report

# Get player trend
trend = compute_player_trends("LeBron James")
print(f"Average sentiment: {trend['avg_sentiment']}")
print(f"Trend: {trend['trend']}")

# Get team report
report = get_team_sentiment_report("Los Angeles Lakers")
for player in report["players"]:
    print(f"{player['player_name']}: {player['avg_sentiment']}")
```

## Scheduling for 11 PM PT Nightly

Several options depending on your infrastructure:

### Option A: Cron (Linux/Mac)

```bash
python scheduler.py --cron
```

This outputs a crontab entry. Add it with `crontab -e`.

### Option B: systemd Timer (Linux servers)

```bash
python scheduler.py --systemd
```

This generates service and timer files for systemd.

### Option C: GitHub Actions (Free, no server needed!)

```bash
python scheduler.py --github-actions
```

This generates a workflow file. Commit to `.github/workflows/scrape.yml`.

**Recommended for 9FS** - runs on GitHub's infrastructure, commits transcripts back to repo.

### Option D: Daemon Mode (Docker/VMs)

```bash
pip install schedule
python scheduler.py --daemon
```

Runs as a long-lived process with built-in scheduling.

## Keeping Rosters Updated

Player rosters change throughout the season. Update them with:

```bash
# Fetch current rosters from ESPN
python roster_fetcher.py --source espn

# Output as Python dict (to update sentiment_analysis.py)
python roster_fetcher.py --python
```

Run this weekly or after major trades.

## Output Structure

```
nba_transcripts/
├── transcripts/
│   ├── 2024-11-27_Joe_Mazzulla_Postgame_abc123.json
│   ├── 2024-11-27_Steve_Kerr_Press_Conference_def456.json
│   └── ...
├── transcripts.db          # Transcript metadata
├── sentiment.db            # Sentiment analysis results
├── nba_rosters.json        # Current NBA rosters
├── scraper.py
├── sentiment_analysis.py
├── roster_fetcher.py
├── scheduler.py
└── requirements.txt
```

### Transcript JSON Format

```json
{
  "video_id": "abc123xyz",
  "title": "Joe Mazzulla Postgame Press Conference | Celtics vs Lakers",
  "channel_name": "Boston Celtics",
  "published_at": "2024-11-27T05:30:00Z",
  "coach_name": "Joe Mazzulla",
  "transcript": "Full transcript text here...",
  "url": "https://www.youtube.com/watch?v=abc123xyz"
}
```

### SQLite Database Queries

```sql
-- Find all mentions of a player
SELECT date, sentiment_score, context 
FROM player_sentiments 
WHERE player_name = 'Jayson Tatum'
ORDER BY date DESC;

-- Find most talked-about players this week
SELECT player_name, COUNT(*) as mentions, AVG(sentiment_score) as avg_sentiment
FROM player_sentiments
WHERE date > date('now', '-7 days')
GROUP BY player_name
ORDER BY mentions DESC
LIMIT 20;

-- Find negative sentiment mentions
SELECT player_name, date, context, sentiment_score
FROM player_sentiments
WHERE sentiment_score < -0.3
ORDER BY date DESC;
```

## API Quota Notes

**YouTube Data API**: 10,000 units/day
- Search request: 100 units
- We search ~31 channels = ~3,100 units per run
- Plenty of headroom for daily runs + occasional backfills

**youtube-transcript-api**: No quota (scrapes captions directly)

**Anthropic API** (if using --llm flag):
- ~$0.003 per player mention analyzed
- Optional - rule-based analysis is free

## Updating Coach Names

When coaches get fired/hired mid-season, update the `NBA_COACHES` list in `scraper.py` and `sentiment_analysis.py`.

## Use Cases

1. **Fantasy Sports**: Identify players likely to see increased/decreased minutes
2. **Sports Betting**: Detect rotation changes before they happen
3. **Trade Rumors**: Track deteriorating player-coach relationships
4. **Media Analysis**: Quantify coach communication patterns

## License

MIT - Use freely for your projects.
