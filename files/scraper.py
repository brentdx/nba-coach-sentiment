"""
NBA Coach Post-Game Press Conference Transcript Scraper

This script fetches coach post-game press conference videos from NBA team channels
and downloads their transcripts automatically.

Requirements:
    pip install google-api-python-client youtube-transcript-api python-dotenv

Setup:
    1. Get a YouTube Data API key from Google Cloud Console
    2. Create a .env file with: YOUTUBE_API_KEY=your_key_here
"""

import os
import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

load_dotenv()

# Configuration
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
DATABASE_PATH = Path(__file__).parent / "transcripts.db"
TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"

# NBA Team YouTube Channel IDs (official team channels)
NBA_CHANNELS = {
    "Atlanta Hawks": "UCLlm1JKsKzxkRFBGJb7Llvg",
    "Boston Celtics": "UCL74l8G6x2rkp2LEQQmqkKQ",
    "Brooklyn Nets": "UCt5qEcfzMO8zSJmQ8z4Mzvg",
    "Charlotte Hornets": "UC4w4L1ng2x11qVXx3mbOaOg",
    "Chicago Bulls": "UCPZn95U8HEFv0S9qQ71WFXQ",
    "Cleveland Cavaliers": "UC5QDBVcQQG5xkLqvpHdqMwQ",
    "Dallas Mavericks": "UC3CjG-A1HclF4bDDVVXV9HQ",
    "Denver Nuggets": "UC6UJvA79c94-G19GyLH6wKQ",
    "Detroit Pistons": "UCCEywvPd2oRl-pEoqdmYPBw",
    "Golden State Warriors": "UCgoA_SJfNq2C3ys5eKk6UjA",
    "Houston Rockets": "UCZQTy6KWXm26hLLEzB2vCYg",
    "Indiana Pacers": "UC6DShFDlB2jLveLz0hWzXJw",
    "LA Clippers": "UCDkNPHYLTJPWQRmzKpz5iLA",
    "Los Angeles Lakers": "UC8CSt-oVqy8pUAoKSApTxQw",
    "Memphis Grizzlies": "UCVdvtuNWMHFHLfSdwJsKI2Q",
    "Miami Heat": "UCqQo7ewe87aYAe7ub5UqXMw",
    "Milwaukee Bucks": "UCuDQp9jUqTpfT1fvBMypqFA",
    "Minnesota Timberwolves": "UC6nqVWoR1bHhYVjA-jMfTHg",
    "New Orleans Pelicans": "UCYm3MgLIQUW-vHiF3FgdOrQ",
    "New York Knicks": "UC-_EBZ0gHPR_Ej2hE4tDCiw",
    "Oklahoma City Thunder": "UC8vjTUzwL6tV0sN0QeITn3A",
    "Orlando Magic": "UCUmQ0T9MNqMVRVXFGkOQ5SQ",
    "Philadelphia 76ers": "UC4SUDuZG4WPv19T_3rdQJmA",
    "Phoenix Suns": "UCxsM6HIFNfbA5VXmXRVIaJA",
    "Portland Trail Blazers": "UCYO7LlrDkGlZNrMvBrvhq2g",
    "Sacramento Kings": "UCpVNUV9XnNmE4Fva7yGzw3w",
    "San Antonio Spurs": "UC5nA9GCqAZJu8J_mMh8RLgg",
    "Toronto Raptors": "UCL8Nwz4h5ChsGwxQT9sZ8Xg",
    "Utah Jazz": "UC4B1YTLm6QPWvB8DjyW3CjA",
    "Washington Wizards": "UCw5_mFSVHwNLz2CbZ35j8xw",
    # Also include the main NBA channel
    "NBA": "UCWJ2lWNubArHWmf3FIHbfcQ",
}

# Keywords to identify coach post-game press conferences
POSTGAME_KEYWORDS = [
    "postgame",
    "post-game",
    "post game",
    "press conference",
    "presser",
    "after the game",
    "coach interview",
]

# Current NBA head coaches (2024-25 season) - update as needed
NBA_COACHES = [
    "Quin Snyder",
    "Joe Mazzulla",
    "Jordi Fernández",
    "Charles Lee",
    "Billy Donovan",
    "Kenny Atkinson",
    "Jason Kidd",
    "Michael Malone",
    "J.B. Bickerstaff",
    "JB Bickerstaff",
    "Steve Kerr",
    "Ime Udoka",
    "Rick Carlisle",
    "Tyronn Lue",
    "JJ Redick",
    "Taylor Jenkins",
    "Erik Spoelstra",
    "Doc Rivers",
    "Chris Finch",
    "Willie Green",
    "Tom Thibodeau",
    "Mark Daigneault",
    "Jamahl Mosley",
    "Nick Nurse",
    "Mike Budenholzer",
    "Chauncey Billups",
    "Mike Brown",
    "Gregg Popovich",
    "Darko Rajaković",
    "Will Hardy",
    "Brian Keefe",
]


def init_database():
    """Initialize SQLite database for storing transcript metadata."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            video_id TEXT PRIMARY KEY,
            title TEXT,
            channel_name TEXT,
            channel_id TEXT,
            published_at TEXT,
            description TEXT,
            transcript_path TEXT,
            scraped_at TEXT,
            has_transcript BOOLEAN,
            coach_name TEXT,
            teams_mentioned TEXT
        )
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_published_at ON videos(published_at)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_channel_name ON videos(channel_name)
    """)
    
    conn.commit()
    conn.close()


def get_youtube_service():
    """Create and return YouTube API service."""
    if not YOUTUBE_API_KEY:
        raise ValueError(
            "YOUTUBE_API_KEY not found. Please set it in your .env file."
        )
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def is_postgame_video(title: str, description: str = "") -> bool:
    """Check if a video is likely a coach post-game press conference."""
    text = f"{title} {description}".lower()
    
    # Must contain postgame-related keywords
    has_postgame_keyword = any(kw in text for kw in POSTGAME_KEYWORDS)
    
    # Should mention a coach or be clearly a press conference
    has_coach_mention = any(coach.lower() in text for coach in NBA_COACHES)
    is_press_conference = "press" in text or "presser" in text or "interview" in text
    
    # Exclude highlights, recap, and non-press content
    exclude_keywords = [
        "highlights",
        "recap",
        "top plays",
        "best of",
        "game winner",
        "buzzer beater",
        "dunk",
        "player interview",  # We want coach interviews, not player
    ]
    has_exclude = any(kw in text for kw in exclude_keywords)
    
    return has_postgame_keyword and (has_coach_mention or is_press_conference) and not has_exclude


def extract_coach_name(title: str, description: str = "") -> Optional[str]:
    """Try to extract the coach name from video title/description."""
    text = f"{title} {description}"
    for coach in NBA_COACHES:
        if coach.lower() in text.lower():
            return coach
    return None


def search_channel_videos(
    youtube,
    channel_id: str,
    channel_name: str,
    published_after: datetime,
    published_before: datetime,
) -> list[dict]:
    """Search for postgame videos from a specific channel."""
    videos = []
    
    try:
        request = youtube.search().list(
            part="snippet",
            channelId=channel_id,
            publishedAfter=published_after.isoformat() + "Z",
            publishedBefore=published_before.isoformat() + "Z",
            maxResults=50,
            order="date",
            type="video",
            q="postgame OR post-game OR press conference",
        )
        response = request.execute()
        
        for item in response.get("items", []):
            snippet = item["snippet"]
            title = snippet["title"]
            description = snippet.get("description", "")
            
            if is_postgame_video(title, description):
                videos.append({
                    "video_id": item["id"]["videoId"],
                    "title": title,
                    "channel_name": channel_name,
                    "channel_id": channel_id,
                    "published_at": snippet["publishedAt"],
                    "description": description[:500],  # Truncate long descriptions
                    "coach_name": extract_coach_name(title, description),
                })
                
    except Exception as e:
        print(f"Error searching {channel_name}: {e}")
    
    return videos


def fetch_transcript(video_id: str) -> Optional[str]:
    """Fetch transcript for a YouTube video."""
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(
            video_id,
            languages=["en", "en-US", "en-GB"],
        )
        
        # Combine all transcript segments into full text
        full_transcript = " ".join(
            segment["text"] for segment in transcript_list
        )
        
        return full_transcript
        
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable) as e:
        print(f"No transcript available for {video_id}: {e}")
        return None
    except Exception as e:
        print(f"Error fetching transcript for {video_id}: {e}")
        return None


def save_transcript(video_id: str, transcript: str, metadata: dict) -> str:
    """Save transcript to file and return the path."""
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    
    # Create filename from date and title
    date_str = metadata["published_at"][:10]
    safe_title = re.sub(r'[^\w\s-]', '', metadata["title"])[:50]
    safe_title = re.sub(r'\s+', '_', safe_title)
    
    filename = f"{date_str}_{safe_title}_{video_id}.json"
    filepath = TRANSCRIPTS_DIR / filename
    
    # Save both transcript and metadata
    data = {
        "video_id": video_id,
        "title": metadata["title"],
        "channel_name": metadata["channel_name"],
        "published_at": metadata["published_at"],
        "coach_name": metadata.get("coach_name"),
        "transcript": transcript,
        "url": f"https://www.youtube.com/watch?v={video_id}",
    }
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    return str(filepath)


def video_exists(video_id: str) -> bool:
    """Check if video already exists in database."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM videos WHERE video_id = ?", (video_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def save_video_metadata(video: dict, transcript_path: Optional[str], has_transcript: bool):
    """Save video metadata to database."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT OR REPLACE INTO videos 
        (video_id, title, channel_name, channel_id, published_at, 
         description, transcript_path, scraped_at, has_transcript, coach_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        video["video_id"],
        video["title"],
        video["channel_name"],
        video["channel_id"],
        video["published_at"],
        video.get("description", ""),
        transcript_path,
        datetime.utcnow().isoformat(),
        has_transcript,
        video.get("coach_name"),
    ))
    
    conn.commit()
    conn.close()


def run_daily_scrape(days_back: int = 1):
    """
    Run the daily scrape job.
    
    Args:
        days_back: Number of days to look back for videos (default 1 for daily job)
    """
    print(f"Starting NBA postgame transcript scrape at {datetime.now()}")
    
    init_database()
    youtube = get_youtube_service()
    
    # Set date range
    now = datetime.utcnow()
    published_before = now
    published_after = now - timedelta(days=days_back)
    
    print(f"Searching for videos from {published_after.date()} to {published_before.date()}")
    
    all_videos = []
    
    # Search each NBA channel
    for channel_name, channel_id in NBA_CHANNELS.items():
        print(f"Searching {channel_name}...")
        videos = search_channel_videos(
            youtube,
            channel_id,
            channel_name,
            published_after,
            published_before,
        )
        all_videos.extend(videos)
        print(f"  Found {len(videos)} potential postgame videos")
    
    # Deduplicate by video ID
    seen_ids = set()
    unique_videos = []
    for video in all_videos:
        if video["video_id"] not in seen_ids:
            seen_ids.add(video["video_id"])
            unique_videos.append(video)
    
    print(f"\nTotal unique videos found: {len(unique_videos)}")
    
    # Process each video
    new_transcripts = 0
    for video in unique_videos:
        video_id = video["video_id"]
        
        # Skip if already processed
        if video_exists(video_id):
            print(f"  Skipping {video_id} (already processed)")
            continue
        
        print(f"  Processing: {video['title'][:60]}...")
        
        # Fetch transcript
        transcript = fetch_transcript(video_id)
        
        if transcript:
            transcript_path = save_transcript(video_id, transcript, video)
            save_video_metadata(video, transcript_path, has_transcript=True)
            new_transcripts += 1
            print(f"    ✓ Saved transcript ({len(transcript)} chars)")
        else:
            save_video_metadata(video, None, has_transcript=False)
            print(f"    ✗ No transcript available")
    
    print(f"\nScrape complete! New transcripts saved: {new_transcripts}")
    return new_transcripts


def backfill(start_date: str, end_date: str):
    """
    Backfill transcripts for a date range.
    
    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    days = (end - start).days + 1
    
    print(f"Backfilling {days} days from {start_date} to {end_date}")
    
    init_database()
    youtube = get_youtube_service()
    
    all_videos = []
    
    for channel_name, channel_id in NBA_CHANNELS.items():
        print(f"Searching {channel_name}...")
        videos = search_channel_videos(
            youtube,
            channel_id,
            channel_name,
            start,
            end,
        )
        all_videos.extend(videos)
    
    # Dedupe and process
    seen_ids = set()
    unique_videos = []
    for video in all_videos:
        if video["video_id"] not in seen_ids:
            seen_ids.add(video["video_id"])
            unique_videos.append(video)
    
    print(f"\nFound {len(unique_videos)} unique videos to process")
    
    for video in unique_videos:
        video_id = video["video_id"]
        
        if video_exists(video_id):
            continue
        
        print(f"  Processing: {video['title'][:50]}...")
        transcript = fetch_transcript(video_id)
        
        if transcript:
            transcript_path = save_transcript(video_id, transcript, video)
            save_video_metadata(video, transcript_path, has_transcript=True)
            print(f"    ✓ Saved")
        else:
            save_video_metadata(video, None, has_transcript=False)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="NBA Postgame Transcript Scraper")
    parser.add_argument(
        "--backfill",
        nargs=2,
        metavar=("START_DATE", "END_DATE"),
        help="Backfill transcripts for date range (YYYY-MM-DD format)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Number of days to look back (default: 1)",
    )
    
    args = parser.parse_args()
    
    if args.backfill:
        backfill(args.backfill[0], args.backfill[1])
    else:
        run_daily_scrape(days_back=args.days)
