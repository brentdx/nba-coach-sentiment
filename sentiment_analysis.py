"""
NBA Coach Sentiment Analysis - Player Mentions

Analyzes coach press conference transcripts to extract sentiment about specific players.
Useful for predicting:
- Minutes allocation changes
- Rotation decisions
- Player-coach relationship status
- Potential trade candidates

Requirements:
    pip install openai anthropic spacy pandas
    python -m spacy download en_core_web_sm
"""

import json
import os
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# Paths
DATABASE_PATH = Path(__file__).parent / "transcripts.db"
SENTIMENT_DB_PATH = Path(__file__).parent / "sentiment.db"
TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"


@dataclass
class PlayerMention:
    """A single mention of a player in a transcript."""
    player_name: str
    team: str
    context: str  # The surrounding text
    sentiment_score: float  # -1 to 1
    sentiment_label: str  # positive, negative, neutral
    confidence: float
    indicators: list[str]  # What drove the sentiment
    video_id: str
    coach_name: str
    date: str


# Current NBA rosters (2024-25) - abbreviated for key players
# In production, pull from NBA API or sports-reference
NBA_ROSTERS = {
    "Boston Celtics": [
        "Jayson Tatum", "Jaylen Brown", "Derrick White", "Jrue Holiday",
        "Kristaps Porzingis", "Al Horford", "Payton Pritchard", "Sam Hauser",
    ],
    "Los Angeles Lakers": [
        "LeBron James", "Anthony Davis", "Austin Reaves", "D'Angelo Russell",
        "Rui Hachimura", "Gabe Vincent", "Jarred Vanderbilt", "Max Christie",
    ],
    "Golden State Warriors": [
        "Stephen Curry", "Draymond Green", "Andrew Wiggins", "Klay Thompson",
        "Jonathan Kuminga", "Kevon Looney", "Chris Paul", "Brandin Podziemski",
    ],
    "Denver Nuggets": [
        "Nikola Jokic", "Jamal Murray", "Michael Porter Jr", "Aaron Gordon",
        "Kentavious Caldwell-Pope", "Reggie Jackson", "Christian Braun",
    ],
    "Milwaukee Bucks": [
        "Giannis Antetokounmpo", "Damian Lillard", "Khris Middleton",
        "Brook Lopez", "Bobby Portis", "Malik Beasley", "Pat Connaughton",
    ],
    "Phoenix Suns": [
        "Kevin Durant", "Devin Booker", "Bradley Beal", "Jusuf Nurkic",
        "Grayson Allen", "Eric Gordon", "Royce O'Neale",
    ],
    "Philadelphia 76ers": [
        "Joel Embiid", "Tyrese Maxey", "Paul George", "Kelly Oubre Jr",
        "Tobias Harris", "De'Anthony Melton", "Nicolas Batum",
    ],
    "Miami Heat": [
        "Jimmy Butler", "Bam Adebayo", "Tyler Herro", "Terry Rozier",
        "Jaime Jaquez Jr", "Duncan Robinson", "Caleb Martin",
    ],
    "Dallas Mavericks": [
        "Luka Doncic", "Kyrie Irving", "Daniel Gafford", "Dereck Lively II",
        "Tim Hardaway Jr", "Josh Green", "Maxi Kleber",
    ],
    "New York Knicks": [
        "Jalen Brunson", "Julius Randle", "OG Anunoby", "Donte DiVincenzo",
        "Josh Hart", "Mitchell Robinson", "Isaiah Hartenstein",
    ],
    # Add more teams as needed - this is a subset for demonstration
}

# Create reverse lookup: player -> team
PLAYER_TO_TEAM = {}
for team, players in NBA_ROSTERS.items():
    for player in players:
        PLAYER_TO_TEAM[player.lower()] = team
        # Also add last name only for matching
        last_name = player.split()[-1].lower()
        if last_name not in PLAYER_TO_TEAM:  # Avoid conflicts
            PLAYER_TO_TEAM[last_name] = team


# Sentiment indicators - phrases that signal positive/negative sentiment
POSITIVE_INDICATORS = [
    # Performance praise
    "played great", "played well", "excellent", "fantastic", "amazing",
    "incredible", "outstanding", "tremendous", "phenomenal", "brilliant",
    "stepped up", "came through", "delivered", "dominated", "took over",
    
    # Role/minutes positive
    "earned", "deserves", "trust", "confident in", "believe in",
    "going to play", "more minutes", "expanded role", "starting",
    "love what he", "love his", "really like", "impressed",
    
    # Growth/development
    "improved", "getting better", "growing", "progressing", "developing",
    "matured", "evolved", "next level", "breakthrough",
    
    # Leadership/intangibles  
    "leader", "vocal", "sets the tone", "brings energy", "competitor",
    "professional", "works hard", "first one in", "dedicated",
    
    # Specific praise
    "great defense", "shot well", "efficient", "smart plays",
    "controlled the game", "made winning plays", "clutch",
]

NEGATIVE_INDICATORS = [
    # Performance criticism
    "struggled", "had a tough", "didn't play well", "off night",
    "not his best", "needs to be better", "got to do more",
    "unacceptable", "disappointed", "frustrating", "concerning",
    
    # Role/minutes negative
    "won't play", "less minutes", "coming off bench", "reduced role",
    "not ready", "not there yet", "needs work", "has to earn",
    "look at other options", "evaluate", "figure out",
    
    # Effort/attitude concerns
    "focus", "concentration", "attention to detail", "discipline",
    "can't have", "not acceptable", "expect more", "demand more",
    
    # Health/availability (often coded negative)
    "day to day", "questionable", "dealing with", "managing",
    
    # Specific criticism
    "turnovers", "defensive lapses", "shot selection", "forcing",
    "out of control", "decision making", "costly mistakes",
]

NEUTRAL_INDICATORS = [
    "we'll see", "evaluate", "day by day", "game to game",
    "depends on", "matchup", "situation", "look at film",
]


def init_sentiment_database():
    """Initialize SQLite database for sentiment analysis results."""
    conn = sqlite3.connect(SENTIMENT_DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS player_sentiments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT,
            player_name TEXT,
            team TEXT,
            coach_name TEXT,
            date TEXT,
            context TEXT,
            sentiment_score REAL,
            sentiment_label TEXT,
            confidence REAL,
            indicators TEXT,
            analyzed_at TEXT,
            UNIQUE(video_id, player_name, context)
        )
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_player_date 
        ON player_sentiments(player_name, date)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_team_date 
        ON player_sentiments(team, date)
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sentiment_trends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_name TEXT,
            team TEXT,
            period_start TEXT,
            period_end TEXT,
            avg_sentiment REAL,
            mention_count INTEGER,
            trend_direction TEXT,
            notable_shift BOOLEAN,
            computed_at TEXT,
            UNIQUE(player_name, period_start, period_end)
        )
    """)
    
    conn.commit()
    conn.close()


def extract_player_mentions(transcript: str, coach_team: str = None) -> list[dict]:
    """
    Extract all player name mentions from a transcript with surrounding context.
    
    Args:
        transcript: Full transcript text
        coach_team: The coach's team (to prioritize their players)
    
    Returns:
        List of dicts with player_name, team, context, position in text
    """
    mentions = []
    transcript_lower = transcript.lower()
    
    # Split into sentences for context extraction
    sentences = re.split(r'[.!?]+', transcript)
    
    for player_name, team in PLAYER_TO_TEAM.items():
        # Search for player name in transcript
        pattern = r'\b' + re.escape(player_name) + r'\b'
        
        for match in re.finditer(pattern, transcript_lower):
            start_pos = match.start()
            
            # Find which sentence contains this mention
            char_count = 0
            context = ""
            for sentence in sentences:
                char_count += len(sentence) + 1  # +1 for period
                if char_count > start_pos:
                    context = sentence.strip()
                    break
            
            # Expand context to nearby sentences if short
            if len(context) < 100:
                sent_idx = sentences.index(context) if context in sentences else -1
                if sent_idx > 0:
                    context = sentences[sent_idx - 1].strip() + ". " + context
                if sent_idx < len(sentences) - 1:
                    context = context + ". " + sentences[sent_idx + 1].strip()
            
            # Get full player name (we might have matched on last name)
            full_name = player_name
            for full, t in PLAYER_TO_TEAM.items():
                if t == team and full.endswith(player_name) and len(full) > len(player_name):
                    full_name = full
                    break
            
            mentions.append({
                "player_name": full_name.title(),
                "team": team,
                "context": context[:500],  # Limit context length
                "position": start_pos,
            })
    
    # Deduplicate mentions of same player in same context
    seen = set()
    unique_mentions = []
    for m in mentions:
        key = (m["player_name"], m["context"][:100])
        if key not in seen:
            seen.add(key)
            unique_mentions.append(m)
    
    return unique_mentions


def analyze_sentiment_rules(context: str) -> tuple[float, str, float, list[str]]:
    """
    Rule-based sentiment analysis using indicator phrases.
    
    Returns:
        tuple of (score, label, confidence, indicators_found)
    """
    context_lower = context.lower()
    
    positive_found = []
    negative_found = []
    neutral_found = []
    
    for indicator in POSITIVE_INDICATORS:
        if indicator in context_lower:
            positive_found.append(indicator)
    
    for indicator in NEGATIVE_INDICATORS:
        if indicator in context_lower:
            negative_found.append(indicator)
    
    for indicator in NEUTRAL_INDICATORS:
        if indicator in context_lower:
            neutral_found.append(indicator)
    
    # Calculate score
    pos_weight = len(positive_found)
    neg_weight = len(negative_found)
    total = pos_weight + neg_weight + 0.001  # Avoid division by zero
    
    if pos_weight == 0 and neg_weight == 0:
        return 0.0, "neutral", 0.3, neutral_found or ["no clear indicators"]
    
    score = (pos_weight - neg_weight) / total
    score = max(-1, min(1, score))  # Clamp to [-1, 1]
    
    # Determine label
    if score > 0.2:
        label = "positive"
    elif score < -0.2:
        label = "negative"
    else:
        label = "neutral"
    
    # Confidence based on number of indicators
    confidence = min(0.9, 0.4 + (total * 0.1))
    
    indicators = positive_found + negative_found
    
    return score, label, confidence, indicators


def analyze_sentiment_llm(
    context: str, 
    player_name: str,
    use_anthropic: bool = True
) -> tuple[float, str, float, list[str]]:
    """
    LLM-based sentiment analysis for more nuanced understanding.
    
    Args:
        context: The text surrounding the player mention
        player_name: The player being discussed
        use_anthropic: Use Claude (True) or OpenAI (False)
    
    Returns:
        tuple of (score, label, confidence, indicators_found)
    """
    prompt = f"""Analyze the following excerpt from an NBA coach's press conference about {player_name}.

Context: "{context}"

Determine the coach's sentiment toward {player_name}. Consider:
1. Is the coach praising or criticizing the player's performance?
2. Are there hints about future playing time (positive or negative)?
3. Is the coach expressing confidence or concern?
4. What specific phrases indicate the sentiment?

Respond in this exact JSON format:
{{
    "sentiment_score": <float from -1.0 (very negative) to 1.0 (very positive)>,
    "sentiment_label": "<positive|negative|neutral>",
    "confidence": <float from 0.0 to 1.0>,
    "indicators": ["<phrase 1>", "<phrase 2>"],
    "interpretation": "<one sentence explanation>"
}}

Only output the JSON, nothing else."""

    try:
        if use_anthropic:
            import anthropic
            client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )
            result_text = response.content[0].text
        else:
            import openai
            client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
            )
            result_text = response.choices[0].message.content
        
        # Parse JSON response
        result = json.loads(result_text)
        return (
            result["sentiment_score"],
            result["sentiment_label"],
            result["confidence"],
            result["indicators"],
        )
        
    except Exception as e:
        print(f"LLM analysis failed: {e}, falling back to rules")
        return analyze_sentiment_rules(context)


def analyze_transcript(
    transcript_path: Path,
    use_llm: bool = False,
    coach_team: str = None,
) -> list[PlayerMention]:
    """
    Analyze a single transcript for player sentiment.
    
    Args:
        transcript_path: Path to transcript JSON file
        use_llm: Whether to use LLM for analysis (more accurate but slower/costs)
        coach_team: The coach's team name
    
    Returns:
        List of PlayerMention objects
    """
    with open(transcript_path, "r") as f:
        data = json.load(f)
    
    transcript = data["transcript"]
    video_id = data["video_id"]
    coach_name = data.get("coach_name", "Unknown")
    date = data["published_at"][:10]
    
    # Extract player mentions
    mentions = extract_player_mentions(transcript, coach_team)
    
    results = []
    for mention in mentions:
        # Analyze sentiment
        if use_llm:
            score, label, confidence, indicators = analyze_sentiment_llm(
                mention["context"],
                mention["player_name"],
            )
        else:
            score, label, confidence, indicators = analyze_sentiment_rules(
                mention["context"]
            )
        
        results.append(PlayerMention(
            player_name=mention["player_name"],
            team=mention["team"],
            context=mention["context"],
            sentiment_score=score,
            sentiment_label=label,
            confidence=confidence,
            indicators=indicators,
            video_id=video_id,
            coach_name=coach_name,
            date=date,
        ))
    
    return results


def save_sentiment_results(mentions: list[PlayerMention]):
    """Save sentiment analysis results to database."""
    conn = sqlite3.connect(SENTIMENT_DB_PATH)
    cursor = conn.cursor()
    
    for m in mentions:
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO player_sentiments
                (video_id, player_name, team, coach_name, date, context,
                 sentiment_score, sentiment_label, confidence, indicators, analyzed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                m.video_id,
                m.player_name,
                m.team,
                m.coach_name,
                m.date,
                m.context,
                m.sentiment_score,
                m.sentiment_label,
                m.confidence,
                json.dumps(m.indicators),
                datetime.utcnow().isoformat(),
            ))
        except sqlite3.IntegrityError:
            pass  # Skip duplicates
    
    conn.commit()
    conn.close()


def compute_player_trends(player_name: str, days: int = 30) -> dict:
    """
    Compute sentiment trends for a player over time.
    
    Returns:
        Dict with trend analysis
    """
    conn = sqlite3.connect(SENTIMENT_DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT date, sentiment_score, sentiment_label, context, coach_name
        FROM player_sentiments
        WHERE player_name = ?
        ORDER BY date DESC
        LIMIT 100
    """, (player_name,))
    
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return {"error": f"No data found for {player_name}"}
    
    # Calculate statistics
    scores = [r[1] for r in rows]
    avg_score = sum(scores) / len(scores)
    
    # Recent vs older comparison
    recent_scores = scores[:min(5, len(scores))]
    older_scores = scores[min(5, len(scores)):]
    
    recent_avg = sum(recent_scores) / len(recent_scores) if recent_scores else 0
    older_avg = sum(older_scores) / len(older_scores) if older_scores else recent_avg
    
    trend_diff = recent_avg - older_avg
    if trend_diff > 0.2:
        trend = "improving"
    elif trend_diff < -0.2:
        trend = "declining"
    else:
        trend = "stable"
    
    return {
        "player_name": player_name,
        "mention_count": len(rows),
        "avg_sentiment": round(avg_score, 3),
        "recent_avg": round(recent_avg, 3),
        "older_avg": round(older_avg, 3),
        "trend": trend,
        "trend_magnitude": round(abs(trend_diff), 3),
        "latest_mentions": [
            {
                "date": r[0],
                "score": r[1],
                "label": r[2],
                "context": r[3][:200],
                "coach": r[4],
            }
            for r in rows[:5]
        ],
    }


def get_team_sentiment_report(team: str) -> dict:
    """Generate a sentiment report for all players on a team."""
    conn = sqlite3.connect(SENTIMENT_DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            player_name,
            COUNT(*) as mention_count,
            AVG(sentiment_score) as avg_sentiment,
            MAX(date) as last_mentioned
        FROM player_sentiments
        WHERE team = ?
        GROUP BY player_name
        ORDER BY avg_sentiment DESC
    """, (team,))
    
    rows = cursor.fetchall()
    conn.close()
    
    players = []
    for row in rows:
        sentiment_category = "positive" if row[2] > 0.2 else ("negative" if row[2] < -0.2 else "neutral")
        players.append({
            "player_name": row[0],
            "mention_count": row[1],
            "avg_sentiment": round(row[2], 3),
            "sentiment_category": sentiment_category,
            "last_mentioned": row[3],
        })
    
    # Flag players to watch
    positive_players = [p for p in players if p["avg_sentiment"] > 0.3]
    negative_players = [p for p in players if p["avg_sentiment"] < -0.2]
    
    return {
        "team": team,
        "total_players_mentioned": len(players),
        "players": players,
        "coach_favorites": [p["player_name"] for p in positive_players],
        "players_to_watch": [p["player_name"] for p in negative_players],
    }


def find_sentiment_shifts(min_shift: float = 0.3) -> list[dict]:
    """Find players with notable recent sentiment shifts."""
    conn = sqlite3.connect(SENTIMENT_DB_PATH)
    cursor = conn.cursor()
    
    # Get all unique players
    cursor.execute("SELECT DISTINCT player_name FROM player_sentiments")
    players = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    shifts = []
    for player in players:
        trend = compute_player_trends(player)
        if "error" not in trend and trend["trend_magnitude"] >= min_shift:
            shifts.append({
                "player_name": player,
                "trend": trend["trend"],
                "magnitude": trend["trend_magnitude"],
                "recent_avg": trend["recent_avg"],
                "older_avg": trend["older_avg"],
                "mention_count": trend["mention_count"],
            })
    
    # Sort by magnitude of shift
    shifts.sort(key=lambda x: x["magnitude"], reverse=True)
    
    return shifts


def run_batch_analysis(use_llm: bool = False, limit: int = None):
    """
    Run sentiment analysis on all transcripts.
    
    Args:
        use_llm: Use LLM for analysis (slower, more accurate)
        limit: Max number of transcripts to process (None = all)
    """
    init_sentiment_database()
    
    transcript_files = list(TRANSCRIPTS_DIR.glob("*.json"))
    
    if limit:
        transcript_files = transcript_files[:limit]
    
    print(f"Analyzing {len(transcript_files)} transcripts...")
    
    total_mentions = 0
    for i, filepath in enumerate(transcript_files):
        print(f"  [{i+1}/{len(transcript_files)}] {filepath.name[:50]}...")
        
        try:
            mentions = analyze_transcript(filepath, use_llm=use_llm)
            if mentions:
                save_sentiment_results(mentions)
                total_mentions += len(mentions)
                print(f"    Found {len(mentions)} player mentions")
        except Exception as e:
            print(f"    Error: {e}")
    
    print(f"\nAnalysis complete! Total player mentions: {total_mentions}")


def generate_report():
    """Generate a summary report of all sentiment analysis."""
    print("\n" + "="*60)
    print("NBA COACH SENTIMENT ANALYSIS REPORT")
    print("="*60)
    
    # Notable shifts
    print("\n📈 NOTABLE SENTIMENT SHIFTS")
    print("-" * 40)
    shifts = find_sentiment_shifts(min_shift=0.25)
    
    if shifts:
        for shift in shifts[:10]:
            emoji = "🔥" if shift["trend"] == "improving" else "⚠️"
            print(f"{emoji} {shift['player_name']}: {shift['trend'].upper()}")
            print(f"   Recent: {shift['recent_avg']:+.2f} | Before: {shift['older_avg']:+.2f}")
            print()
    else:
        print("No significant shifts detected")
    
    # Team reports for a few teams
    print("\n📊 TEAM SENTIMENT SUMMARIES")
    print("-" * 40)
    
    sample_teams = ["Boston Celtics", "Los Angeles Lakers", "Golden State Warriors"]
    for team in sample_teams:
        report = get_team_sentiment_report(team)
        if report["players"]:
            print(f"\n{team}")
            print(f"  Coach favorites: {', '.join(report['coach_favorites'][:3]) or 'None detected'}")
            print(f"  Watch list: {', '.join(report['players_to_watch'][:3]) or 'None detected'}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="NBA Coach Sentiment Analysis")
    parser.add_argument("--analyze", action="store_true", help="Run batch analysis")
    parser.add_argument("--llm", action="store_true", help="Use LLM for analysis")
    parser.add_argument("--limit", type=int, help="Limit transcripts to process")
    parser.add_argument("--player", type=str, help="Get trend for specific player")
    parser.add_argument("--team", type=str, help="Get report for specific team")
    parser.add_argument("--shifts", action="store_true", help="Find sentiment shifts")
    parser.add_argument("--report", action="store_true", help="Generate full report")
    
    args = parser.parse_args()
    
    if args.analyze:
        run_batch_analysis(use_llm=args.llm, limit=args.limit)
    elif args.player:
        trend = compute_player_trends(args.player)
        print(json.dumps(trend, indent=2))
    elif args.team:
        report = get_team_sentiment_report(args.team)
        print(json.dumps(report, indent=2))
    elif args.shifts:
        shifts = find_sentiment_shifts()
        print(json.dumps(shifts, indent=2))
    elif args.report:
        generate_report()
    else:
        parser.print_help()
