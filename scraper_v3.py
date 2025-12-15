"""
NBA Coach Post-Game Press Conference Transcript Scraper

Scrapes coach postgame interviews from @basketman2023 YouTube channel.
Uses YouTube captions when available, falls back to Whisper for transcription.

Requirements:
    pip install google-api-python-client youtube-transcript-api python-dotenv yt-dlp openai-whisper

Setup:
    1. Get a YouTube Data API key from Google Cloud Console
    2. Set YOUTUBE_API_KEY environment variable or create .env file
"""

import os
import json
import re
import sqlite3
import tempfile
import subprocess
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

# The channel that has all coach interviews
# @basketman2023
CHANNEL_HANDLE = "@basketman2023"
CHANNEL_ID = "UCmwOTk7ROGKohtHTWj-vAmQ"  # Hardcoded to save API quota

# Current NBA head coaches (2024-25 season) - all 30 teams
NBA_COACHES = [
    # Atlantic
    "Joe Mazzulla", "Mazzulla",           # Boston Celtics
    "Jordi Fernández", "Jordi Fernandez", # Brooklyn Nets  
    "Nick Nurse", "Nurse",                # Philadelphia 76ers
    "Tom Thibodeau", "Thibs", "Thibodeau", # New York Knicks
    "Darko Rajaković", "Darko Rajakovic", # Toronto Raptors
    
    # Central
    "Kenny Atkinson", "Atkinson",         # Cleveland Cavaliers
    "JB Bickerstaff", "J.B. Bickerstaff", # Detroit Pistons
    "Rick Carlisle", "Carlisle",          # Indiana Pacers
    "Doc Rivers", "Rivers",               # Milwaukee Bucks
    "Billy Donovan", "Donovan",           # Chicago Bulls
    
    # Southeast
    "Quin Snyder", "Snyder",              # Atlanta Hawks
    "Charles Lee",                         # Charlotte Hornets
    "Erik Spoelstra", "Spoelstra", "Spo", # Miami Heat
    "Jamahl Mosley", "Mosley",            # Orlando Magic
    "Brian Keefe", "Keefe",               # Washington Wizards
    
    # Northwest
    "Michael Malone", "Malone",           # Denver Nuggets
    "Mark Daigneault", "Daigneault",      # Oklahoma City Thunder
    "Chauncey Billups", "Billups",        # Portland Trail Blazers
    "Will Hardy", "Hardy",                # Utah Jazz
    "Chris Finch", "Finch",               # Minnesota Timberwolves
    
    # Pacific
    "Steve Kerr", "Kerr",                 # Golden State Warriors
    "JJ Redick", "Redick",                # Los Angeles Lakers
    "Tyronn Lue", "Ty Lue", "Lue",        # LA Clippers
    "Mike Brown", "Brown",                # Sacramento Kings
    "Kevin Young",                         # Phoenix Suns
    
    # Southwest
    "Ime Udoka", "Udoka",                 # Houston Rockets
    "Taylor Jenkins", "Jenkins",          # Memphis Grizzlies
    "Willie Green", "Green",              # New Orleans Pelicans
    "Gregg Popovich", "Pop", "Popovich",  # San Antonio Spurs
    "Jason Kidd", "Kidd",                 # Dallas Mavericks
]

# Whether to use Whisper for transcription when captions unavailable
USE_WHISPER_FALLBACK = os.getenv("USE_WHISPER_FALLBACK", "false").lower() == "true"


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
            transcript_source TEXT,
            coach_name TEXT,
            teams_mentioned TEXT
        )
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_published_at ON videos(published_at)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_coach_name ON videos(coach_name)
    """)
    
    conn.commit()
    conn.close()


def get_youtube_service():
    """Create and return YouTube API service."""
    if not YOUTUBE_API_KEY:
        raise ValueError(
            "YOUTUBE_API_KEY not found. Please set it in your .env file or environment."
        )
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def is_coach_interview(title: str, description: str = "") -> bool:
    """Check if a video is a coach interview/press conference."""
    text = f"{title} {description}".lower()
    
    # This channel only posts interviews, so we just check for basic keywords
    interview_keywords = [
        "postgame", "post-game", "post game",
        "interview",
        "presser", "press conference",
        "halftime", "half time", "half-time",
        "talks", "speaks", "discusses", "reacts",
        "media",
    ]
    
    # Exclude non-interview content
    exclude_keywords = [
        "highlights", "dunk", "shot", "play", 
        "top 10", "best of", "mix",
    ]
    
    has_interview = any(kw in text for kw in interview_keywords)
    has_exclude = any(kw in text for kw in exclude_keywords)
    
    return has_interview and not has_exclude


def extract_coach_name(title: str, description: str = "") -> Optional[str]:
    """Extract the coach name from video title/description."""
    text = f"{title} {description}"
    for coach in NBA_COACHES:
        if coach.lower() in text.lower():
            return coach
    return None


def get_channel_videos(
    youtube,
    channel_id: str,
    published_after: datetime,
    published_before: datetime,
    max_results: int = 200,
) -> list[dict]:
    """Get recent videos from a channel."""
    videos = []
    
    try:
        request = youtube.search().list(
            part="snippet",
            channelId=channel_id,
            publishedAfter=published_after.strftime("%Y-%m-%dT%H:%M:%SZ"),
            publishedBefore=published_before.strftime("%Y-%m-%dT%H:%M:%SZ"),
            maxResults=50,
            order="date",
            type="video",
        )
        response = request.execute()
        
        for item in response.get("items", []):
            snippet = item["snippet"]
            title = snippet["title"]
            description = snippet.get("description", "")
            
            if is_coach_interview(title, description):
                coach_name = extract_coach_name(title, description)
                videos.append({
                    "video_id": item["id"]["videoId"],
                    "title": title,
                    "channel_name": snippet["channelTitle"],
                    "channel_id": channel_id,
                    "published_at": snippet["publishedAt"],
                    "description": description[:500],
                    "coach_name": coach_name,
                })
                print(f"  ✓ [{coach_name}] {title[:50]}...")
            else:
                print(f"  ✗ [skipped] {title[:50]}...")
            
        # Handle pagination
        next_page_token = response.get("nextPageToken")
        while next_page_token and len(videos) < max_results:
            request = youtube.search().list(
                part="snippet",
                channelId=channel_id,
                publishedAfter=published_after.strftime("%Y-%m-%dT%H:%M:%SZ"),
                publishedBefore=published_before.strftime("%Y-%m-%dT%H:%M:%SZ"),
                maxResults=50,
                order="date",
                type="video",
                pageToken=next_page_token,
            )
            response = request.execute()
            
            for item in response.get("items", []):
                snippet = item["snippet"]
                title = snippet["title"]
                description = snippet.get("description", "")
                
                if is_coach_interview(title, description):
                    coach_name = extract_coach_name(title, description)
                    videos.append({
                        "video_id": item["id"]["videoId"],
                        "title": title,
                        "channel_name": snippet["channelTitle"],
                        "channel_id": channel_id,
                        "published_at": snippet["publishedAt"],
                        "description": description[:500],
                        "coach_name": coach_name,
                    })
                    print(f"  ✓ [{coach_name}] {title[:50]}...")
                else:
                    print(f"  ✗ [skipped] {title[:50]}...")
            
            next_page_token = response.get("nextPageToken")
                
    except Exception as e:
        print(f"Error fetching videos: {e}")
    
    return videos


def fetch_transcript_youtube(video_id: str) -> Optional[str]:
    """Fetch transcript from YouTube captions."""
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(
            video_id,
            languages=["en", "en-US", "en-GB"],
        )
        
        full_transcript = " ".join(
            segment["text"] for segment in transcript_list
        )
        
        return full_transcript
        
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
        return None
    except Exception as e:
        print(f"      YouTube caption error: {e}")
        return None


def fetch_transcript_whisper(video_id: str) -> Optional[str]:
    """Download audio and transcribe with Whisper."""
    if not USE_WHISPER_FALLBACK:
        return None
        
    try:
        import whisper
    except ImportError:
        print("      Whisper not installed, skipping fallback")
        return None
    
    print(f"      Using Whisper for transcription...")
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "audio.mp3"
            
            # Download audio using yt-dlp
            url = f"https://www.youtube.com/watch?v={video_id}"
            cmd = [
                "yt-dlp",
                "-x",  # Extract audio
                "--audio-format", "mp3",
                "--audio-quality", "5",  # Lower quality = smaller file
                "-o", str(audio_path),
                url,
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            
            if result.returncode != 0:
                print(f"      yt-dlp error: {result.stderr[:100]}")
                return None
            
            # Transcribe with Whisper
            model = whisper.load_model("base")  # Use "small" or "medium" for better accuracy
            result = model.transcribe(str(audio_path))
            
            return result["text"]
            
    except Exception as e:
        print(f"      Whisper error: {e}")
        return None


def fetch_transcript(video_id: str) -> tuple[Optional[str], str]:
    """
    Fetch transcript, trying YouTube captions first, then Whisper.
    
    Returns:
        Tuple of (transcript_text, source) where source is "youtube" or "whisper"
    """
    # Try YouTube captions first
    transcript = fetch_transcript_youtube(video_id)
    if transcript:
        return transcript, "youtube"
    
    # Fall back to Whisper if enabled
    if USE_WHISPER_FALLBACK:
        transcript = fetch_transcript_whisper(video_id)
        if transcript:
            return transcript, "whisper"
    
    return None, ""


def save_transcript(video_id: str, transcript: str, metadata: dict, source: str) -> str:
    """Save transcript to file and return the path."""
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    
    date_str = metadata["published_at"][:10]
    coach = metadata.get("coach_name", "Unknown")
    safe_coach = re.sub(r'[^\w\s-]', '', coach)[:20]
    
    filename = f"{date_str}_{safe_coach}_{video_id}.json"
    filepath = TRANSCRIPTS_DIR / filename
    
    data = {
        "video_id": video_id,
        "title": metadata["title"],
        "channel_name": metadata["channel_name"],
        "published_at": metadata["published_at"],
        "coach_name": metadata.get("coach_name"),
        "transcript": transcript,
        "transcript_source": source,
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


def video_needs_transcript(video_id: str) -> bool:
    """Check if video exists but needs transcript."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT has_transcript FROM videos WHERE video_id = ?", 
        (video_id,)
    )
    row = cursor.fetchone()
    conn.close()
    
    if row is None:
        return False  # Video doesn't exist
    return row[0] == 0  # Needs transcript if has_transcript is False


def save_video_metadata(
    video: dict, 
    transcript_path: Optional[str], 
    has_transcript: bool,
    transcript_source: str = ""
):
    """Save video metadata to database."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT OR REPLACE INTO videos 
        (video_id, title, channel_name, channel_id, published_at, 
         description, transcript_path, scraped_at, has_transcript, 
         transcript_source, coach_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        transcript_source,
        video.get("coach_name"),
    ))
    
    conn.commit()
    conn.close()


def retry_missing_transcripts():
    """Retry fetching transcripts for videos that don't have them."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT video_id, title, channel_name, channel_id, published_at, 
               description, coach_name
        FROM videos 
        WHERE has_transcript = 0
        ORDER BY published_at DESC
        LIMIT 50
    """)
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        print("No videos need transcript retry.")
        return 0
    
    print(f"\nRetrying transcripts for {len(rows)} videos...")
    
    success_count = 0
    for row in rows:
        video = {
            "video_id": row[0],
            "title": row[1],
            "channel_name": row[2],
            "channel_id": row[3],
            "published_at": row[4],
            "description": row[5],
            "coach_name": row[6],
        }
        
        print(f"  Retrying: {video['title'][:50]}...")
        
        transcript, source = fetch_transcript(video["video_id"])
        
        if transcript:
            transcript_path = save_transcript(
                video["video_id"], 
                transcript, 
                video,
                source
            )
            save_video_metadata(video, transcript_path, True, source)
            success_count += 1
            print(f"    ✓ Got transcript via {source} ({len(transcript):,} chars)")
        else:
            print(f"    ✗ Still no transcript available")
    
    print(f"\nRetry complete. Got {success_count}/{len(rows)} transcripts.")
    return success_count


def run_daily_scrape(days_back: int = 7):
    """Run the daily scrape job."""
    print(f"\n{'='*60}")
    print(f"NBA Coach Postgame Transcript Scraper")
    print(f"Source: {CHANNEL_HANDLE}")
    print(f"Started: {datetime.now()}")
    print(f"Whisper fallback: {'ENABLED' if USE_WHISPER_FALLBACK else 'DISABLED'}")
    print(f"{'='*60}\n")
    
    init_database()
    youtube = get_youtube_service()
    
    channel_id = CHANNEL_ID
    print(f"Using channel ID: {channel_id}")
    
    now = datetime.utcnow()
    published_before = now
    published_after = now - timedelta(days=days_back)
    
    print(f"\nSearching for videos from {published_after.date()} to {published_before.date()}")
    print(f"Filtering for coach interviews...\n")
    
    videos = get_channel_videos(
        youtube,
        channel_id,
        published_after,
        published_before,
        max_results=200,
    )
    
    print(f"\n{'='*60}")
    print(f"Found {len(videos)} coach interview videos")
    print(f"{'='*60}\n")
    
    if not videos:
        print("No new coach interviews found in date range.")
        # Still retry missing transcripts
        retry_missing_transcripts()
        return 0
    
    new_transcripts = 0
    skipped = 0
    no_transcript = 0
    
    for video in videos:
        video_id = video["video_id"]
        
        if video_exists(video_id):
            if video_needs_transcript(video_id):
                print(f"  [RETRY] {video['title'][:50]}...")
            else:
                print(f"  [SKIP] Already have: {video['title'][:50]}...")
                skipped += 1
                continue
        else:
            print(f"  [NEW] {video['title'][:55]}...")
        
        transcript, source = fetch_transcript(video_id)
        
        if transcript:
            transcript_path = save_transcript(video_id, transcript, video, source)
            save_video_metadata(video, transcript_path, True, source)
            new_transcripts += 1
            print(f"      ✓ Saved via {source} ({len(transcript):,} chars)")
        else:
            save_video_metadata(video, None, False, "")
            no_transcript += 1
            print(f"      ✗ No transcript available yet")
    
    # Retry any older videos that still need transcripts
    retry_missing_transcripts()
    
    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE")
    print(f"  New transcripts: {new_transcripts}")
    print(f"  Skipped (already have): {skipped}")
    print(f"  No transcript available: {no_transcript}")
    print(f"{'='*60}\n")
    
    return new_transcripts


def backfill(start_date: str, end_date: str):
    """Backfill transcripts for a date range."""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    days = (end - start).days + 1
    
    print(f"Backfilling {days} days from {start_date} to {end_date}")
    
    init_database()
    youtube = get_youtube_service()
    
    channel_id = CHANNEL_ID
    
    videos = get_channel_videos(youtube, channel_id, start, end, max_results=500)
    
    print(f"\nFound {len(videos)} coach interviews to process")
    
    new_count = 0
    for video in videos:
        video_id = video["video_id"]
        
        if video_exists(video_id) and not video_needs_transcript(video_id):
            continue
        
        print(f"  Processing: {video['title'][:50]}...")
        transcript, source = fetch_transcript(video_id)
        
        if transcript:
            transcript_path = save_transcript(video_id, transcript, video, source)
            save_video_metadata(video, transcript_path, True, source)
            new_count += 1
            print(f"    ✓ Saved via {source}")
        else:
            save_video_metadata(video, None, False, "")
    
    print(f"\nBackfill complete! Added {new_count} new transcripts.")


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
        default=7,
        help="Number of days to look back (default: 7)",
    )
    parser.add_argument(
        "--retry",
        action="store_true",
        help="Only retry fetching missing transcripts",
    )
    
    args = parser.parse_args()
    
    if args.retry:
        init_database()
        retry_missing_transcripts()
    elif args.backfill:
        backfill(args.backfill[0], args.backfill[1])
    else:
        run_daily_scrape(days_back=args.days)
