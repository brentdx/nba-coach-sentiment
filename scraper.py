"""
NBA Coach Post-Game Press Conference Transcript Scraper

Scrapes coach postgame interviews from @basketman2023 YouTube channel.

Requirements:
    pip install google-api-python-client youtube-transcript-api python-dotenv

Setup:
    1. Get a YouTube Data API key from Google Cloud Console
    2. Set YOUTUBE_API_KEY environment variable or create .env file
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

# The channel that has all coach interviews
# @basketman2023
CHANNEL_HANDLE = "@basketman2023"
CHANNEL_ID = "UCmwOTk7ROGKohtHTWj-vAmQ"  # Hardcoded to save API quota

# Current NBA head coaches (2024-25 season)
NBA_COACHES = [
    "Quin Snyder",
    "Joe Mazzulla",
    "Jordi Fernández",
    "Jordi Fernandez",
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
    "Ty Lue",
    "JJ Redick",
    "Taylor Jenkins",
    "Erik Spoelstra",
    "Spoelstra",
    "Doc Rivers",
    "Chris Finch",
    "Willie Green",
    "Tom Thibodeau",
    "Thibs",
    "Thibodeau",
    "Mark Daigneault",
    "Jamahl Mosley",
    "Nick Nurse",
    "Mike Budenholzer",
    "Budenholzer",
    "Chauncey Billups",
    "Mike Brown",
    "Gregg Popovich",
    "Pop",
    "Popovich",
    "Darko Rajaković",
    "Darko Rajakovic",
    "Will Hardy",
    "Brian Keefe",
    # Interim / recent changes
    "Griff Aldrich",
    "Kevin Young",
    "Mazzulla",
    "Kerr",
    "Kidd",
    "Carlisle",
    "Nurse",
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


def resolve_channel_id(youtube, handle: str) -> str:
    """Resolve a YouTube handle (@username) to a channel ID."""
    try:
        # Try searching for the channel
        request = youtube.search().list(
            part="snippet",
            q=handle,
            type="channel",
            maxResults=1,
        )
        response = request.execute()
        
        if response.get("items"):
            channel_id = response["items"][0]["snippet"]["channelId"]
            print(f"Resolved {handle} to channel ID: {channel_id}")
            return channel_id
        
        # Alternative: try channels.list with forHandle
        request = youtube.channels().list(
            part="id",
            forHandle=handle.replace("@", ""),
        )
        response = request.execute()
        
        if response.get("items"):
            return response["items"][0]["id"]
            
    except Exception as e:
        print(f"Error resolving channel handle: {e}")
    
    raise ValueError(f"Could not resolve channel handle: {handle}")


def is_coach_interview(title: str, description: str = "") -> bool:
    """Check if a video is a coach interview/press conference."""
    text = f"{title} {description}".lower()
    
    # Check if any coach name is in the title
    has_coach = any(coach.lower() in text for coach in NBA_COACHES)
    
    # Keywords that suggest it's a press conference / interview
    interview_keywords = [
        "postgame",
        "post-game", 
        "post game",
        "press conference",
        "presser",
        "interview",
        "talks",
        "speaks",
        "reacts",
        "on the",
        "after",
        "following",
        "discusses",
        "media",
    ]
    has_interview_keyword = any(kw in text for kw in interview_keywords)
    
    # Must have coach name - that's our primary filter
    return has_coach


def extract_coach_name(title: str, description: str = "") -> Optional[str]:
    """Extract the coach name from video title/description."""
    text = f"{title} {description}"
    for coach in NBA_COACHES:
        if coach.lower() in text.lower():
            # Return the longer/full name version
            return coach
    return None


def get_channel_videos(
    youtube,
    channel_id: str,
    published_after: datetime,
    published_before: datetime,
    max_results: int = 50,
) -> list[dict]:
    """Get recent videos from a channel."""
    videos = []
    
    try:
        # Search for videos from this channel
        request = youtube.search().list(
            part="snippet",
            channelId=channel_id,
            publishedAfter=published_after.strftime("%Y-%m-%dT%H:%M:%SZ"),
            publishedBefore=published_before.strftime("%Y-%m-%dT%H:%M:%SZ"),
            maxResults=max_results,
            order="date",
            type="video",
        )
        response = request.execute()
        
        for item in response.get("items", []):
            snippet = item["snippet"]
            title = snippet["title"]
            description = snippet.get("description", "")
            
            # Filter for coach interviews
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
            
        # Handle pagination if needed
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
            
            next_page_token = response.get("nextPageToken")
                
    except Exception as e:
        print(f"Error fetching videos: {e}")
    
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
        print(f"      No transcript: {type(e).__name__}")
        return None
    except Exception as e:
        print(f"      Transcript error: {e}")
        return None


def save_transcript(video_id: str, transcript: str, metadata: dict) -> str:
    """Save transcript to file and return the path."""
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    
    # Create filename from date, coach, and video ID
    date_str = metadata["published_at"][:10]
    coach = metadata.get("coach_name", "Unknown")
    safe_coach = re.sub(r'[^\w\s-]', '', coach)[:20]
    safe_title = re.sub(r'[^\w\s-]', '', metadata["title"])[:30]
    safe_title = re.sub(r'\s+', '_', safe_title)
    
    filename = f"{date_str}_{safe_coach}_{video_id}.json"
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


def run_daily_scrape(days_back: int = 7):
    """
    Run the daily scrape job.
    
    Args:
        days_back: Number of days to look back for videos
    """
    print(f"\n{'='*60}")
    print(f"NBA Coach Postgame Transcript Scraper")
    print(f"Source: {CHANNEL_HANDLE}")
    print(f"Started: {datetime.now()}")
    print(f"{'='*60}\n")
    
    init_database()
    youtube = get_youtube_service()
    
    # Use hardcoded channel ID
    channel_id = CHANNEL_ID
    print(f"Using channel ID: {channel_id}")
    
    # Set date range
    now = datetime.utcnow()
    published_before = now
    published_after = now - timedelta(days=days_back)
    
    print(f"\nSearching for videos from {published_after.date()} to {published_before.date()}")
    print(f"Filtering for coach interviews...\n")
    
    # Get videos
    videos = get_channel_videos(
        youtube,
        channel_id,
        published_after,
        published_before,
        max_results=100,
    )
    
    print(f"\n{'='*60}")
    print(f"Found {len(videos)} coach interview videos")
    print(f"{'='*60}\n")
    
    if not videos:
        print("No new coach interviews found in date range.")
        return 0
    
    # Process each video
    new_transcripts = 0
    skipped = 0
    no_transcript = 0
    
    for video in videos:
        video_id = video["video_id"]
        
        # Skip if already processed
        if video_exists(video_id):
            print(f"  [SKIP] Already have: {video['title'][:50]}...")
            skipped += 1
            continue
        
        print(f"  [NEW] {video['title'][:55]}...")
        
        # Fetch transcript
        transcript = fetch_transcript(video_id)
        
        if transcript:
            transcript_path = save_transcript(video_id, transcript, video)
            save_video_metadata(video, transcript_path, has_transcript=True)
            new_transcripts += 1
            print(f"      ✓ Saved ({len(transcript):,} chars)")
        else:
            save_video_metadata(video, None, has_transcript=False)
            no_transcript += 1
    
    print(f"\n{'='*60}")
    print(f"SCRAPE COMPLETE")
    print(f"  New transcripts: {new_transcripts}")
    print(f"  Skipped (existing): {skipped}")
    print(f"  No transcript available: {no_transcript}")
    print(f"{'='*60}\n")
    
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
    
    # Use hardcoded channel ID
    channel_id = CHANNEL_ID
    
    # Get all videos in range
    videos = get_channel_videos(youtube, channel_id, start, end, max_results=500)
    
    print(f"\nFound {len(videos)} coach interviews to process")
    
    new_count = 0
    for video in videos:
        video_id = video["video_id"]
        
        if video_exists(video_id):
            continue
        
        print(f"  Processing: {video['title'][:50]}...")
        transcript = fetch_transcript(video_id)
        
        if transcript:
            transcript_path = save_transcript(video_id, transcript, video)
            save_video_metadata(video, transcript_path, has_transcript=True)
            new_count += 1
            print(f"    ✓ Saved")
        else:
            save_video_metadata(video, None, has_transcript=False)
    
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
    
    args = parser.parse_args()
    
    if args.backfill:
        backfill(args.backfill[0], args.backfill[1])
    else:
        run_daily_scrape(days_back=args.days)
