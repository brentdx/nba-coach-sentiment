"""
NBA Roster Fetcher

Fetches current NBA rosters from public APIs to keep player lists up to date.
This ensures the sentiment analysis can identify all players correctly.

Run periodically (weekly) or at start of season.
"""

import json
from datetime import datetime
from pathlib import Path

import requests

ROSTERS_PATH = Path(__file__).parent / "nba_rosters.json"

# NBA team IDs (from various APIs)
NBA_TEAMS = {
    "Atlanta Hawks": {"abbrev": "ATL", "nba_id": 1610612737},
    "Boston Celtics": {"abbrev": "BOS", "nba_id": 1610612738},
    "Brooklyn Nets": {"abbrev": "BKN", "nba_id": 1610612751},
    "Charlotte Hornets": {"abbrev": "CHA", "nba_id": 1610612766},
    "Chicago Bulls": {"abbrev": "CHI", "nba_id": 1610612741},
    "Cleveland Cavaliers": {"abbrev": "CLE", "nba_id": 1610612739},
    "Dallas Mavericks": {"abbrev": "DAL", "nba_id": 1610612742},
    "Denver Nuggets": {"abbrev": "DEN", "nba_id": 1610612743},
    "Detroit Pistons": {"abbrev": "DET", "nba_id": 1610612765},
    "Golden State Warriors": {"abbrev": "GSW", "nba_id": 1610612744},
    "Houston Rockets": {"abbrev": "HOU", "nba_id": 1610612745},
    "Indiana Pacers": {"abbrev": "IND", "nba_id": 1610612754},
    "LA Clippers": {"abbrev": "LAC", "nba_id": 1610612746},
    "Los Angeles Lakers": {"abbrev": "LAL", "nba_id": 1610612747},
    "Memphis Grizzlies": {"abbrev": "MEM", "nba_id": 1610612763},
    "Miami Heat": {"abbrev": "MIA", "nba_id": 1610612748},
    "Milwaukee Bucks": {"abbrev": "MIL", "nba_id": 1610612749},
    "Minnesota Timberwolves": {"abbrev": "MIN", "nba_id": 1610612750},
    "New Orleans Pelicans": {"abbrev": "NOP", "nba_id": 1610612740},
    "New York Knicks": {"abbrev": "NYK", "nba_id": 1610612752},
    "Oklahoma City Thunder": {"abbrev": "OKC", "nba_id": 1610612760},
    "Orlando Magic": {"abbrev": "ORL", "nba_id": 1610612753},
    "Philadelphia 76ers": {"abbrev": "PHI", "nba_id": 1610612755},
    "Phoenix Suns": {"abbrev": "PHX", "nba_id": 1610612756},
    "Portland Trail Blazers": {"abbrev": "POR", "nba_id": 1610612757},
    "Sacramento Kings": {"abbrev": "SAC", "nba_id": 1610612758},
    "San Antonio Spurs": {"abbrev": "SAS", "nba_id": 1610612759},
    "Toronto Raptors": {"abbrev": "TOR", "nba_id": 1610612761},
    "Utah Jazz": {"abbrev": "UTA", "nba_id": 1610612762},
    "Washington Wizards": {"abbrev": "WAS", "nba_id": 1610612764},
}


def fetch_rosters_balldontlie() -> dict:
    """
    Fetch rosters from balldontlie API (free, no auth required).
    
    Returns:
        Dict of team -> list of player names
    """
    rosters = {}
    
    # Get all players (paginated)
    base_url = "https://api.balldontlie.io/v1/players"
    headers = {"Authorization": "YOUR_API_KEY"}  # Free tier available
    
    all_players = []
    cursor = None
    
    try:
        for _ in range(10):  # Max 10 pages
            params = {"per_page": 100}
            if cursor:
                params["cursor"] = cursor
            
            response = requests.get(base_url, params=params, headers=headers, timeout=30)
            
            if response.status_code != 200:
                print(f"API error: {response.status_code}")
                break
            
            data = response.json()
            all_players.extend(data.get("data", []))
            
            cursor = data.get("meta", {}).get("next_cursor")
            if not cursor:
                break
        
        # Organize by team
        for player in all_players:
            team = player.get("team", {})
            team_name = team.get("full_name", "Unknown")
            player_name = f"{player['first_name']} {player['last_name']}"
            
            if team_name not in rosters:
                rosters[team_name] = []
            rosters[team_name].append(player_name)
        
    except Exception as e:
        print(f"Error fetching rosters: {e}")
    
    return rosters


def fetch_rosters_nba_api() -> dict:
    """
    Fetch rosters from NBA's stats API.
    More reliable but may have rate limits.
    
    Returns:
        Dict of team -> list of player names
    """
    rosters = {}
    
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.nba.com/",
        "Accept": "application/json",
    }
    
    for team_name, team_info in NBA_TEAMS.items():
        try:
            url = f"https://stats.nba.com/stats/commonteamroster"
            params = {
                "TeamID": team_info["nba_id"],
                "Season": "2024-25",
            }
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                rows = data.get("resultSets", [{}])[0].get("rowSet", [])
                headers_list = data.get("resultSets", [{}])[0].get("headers", [])
                
                name_idx = headers_list.index("PLAYER") if "PLAYER" in headers_list else 3
                
                players = [row[name_idx] for row in rows]
                rosters[team_name] = players
                print(f"  {team_name}: {len(players)} players")
            else:
                print(f"  {team_name}: Failed ({response.status_code})")
                
        except Exception as e:
            print(f"  {team_name}: Error - {e}")
    
    return rosters


def fetch_rosters_espn() -> dict:
    """
    Fetch rosters from ESPN API (unofficial but reliable).
    
    Returns:
        Dict of team -> list of player names
    """
    rosters = {}
    
    espn_team_ids = {
        "Atlanta Hawks": "atl", "Boston Celtics": "bos", "Brooklyn Nets": "bkn",
        "Charlotte Hornets": "cha", "Chicago Bulls": "chi", "Cleveland Cavaliers": "cle",
        "Dallas Mavericks": "dal", "Denver Nuggets": "den", "Detroit Pistons": "det",
        "Golden State Warriors": "gs", "Houston Rockets": "hou", "Indiana Pacers": "ind",
        "LA Clippers": "lac", "Los Angeles Lakers": "lal", "Memphis Grizzlies": "mem",
        "Miami Heat": "mia", "Milwaukee Bucks": "mil", "Minnesota Timberwolves": "min",
        "New Orleans Pelicans": "no", "New York Knicks": "ny", "Oklahoma City Thunder": "okc",
        "Orlando Magic": "orl", "Philadelphia 76ers": "phi", "Phoenix Suns": "phx",
        "Portland Trail Blazers": "por", "Sacramento Kings": "sac", "San Antonio Spurs": "sa",
        "Toronto Raptors": "tor", "Utah Jazz": "uta", "Washington Wizards": "wsh",
    }
    
    for team_name, abbrev in espn_team_ids.items():
        try:
            url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{abbrev}/roster"
            response = requests.get(url, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                athletes = data.get("athletes", [])
                
                players = []
                for category in athletes:
                    for player in category.get("items", []):
                        players.append(player.get("displayName", player.get("fullName", "")))
                
                rosters[team_name] = players
                print(f"  {team_name}: {len(players)} players")
            else:
                print(f"  {team_name}: Failed ({response.status_code})")
                
        except Exception as e:
            print(f"  {team_name}: Error - {e}")
    
    return rosters


def save_rosters(rosters: dict):
    """Save rosters to JSON file."""
    data = {
        "updated_at": datetime.utcnow().isoformat(),
        "rosters": rosters,
    }
    
    with open(ROSTERS_PATH, "w") as f:
        json.dump(data, f, indent=2)
    
    print(f"\nSaved rosters to {ROSTERS_PATH}")


def load_rosters() -> dict:
    """Load rosters from JSON file."""
    if ROSTERS_PATH.exists():
        with open(ROSTERS_PATH, "r") as f:
            data = json.load(f)
            return data.get("rosters", {})
    return {}


def generate_python_dict(rosters: dict) -> str:
    """Generate Python code for NBA_ROSTERS dict."""
    lines = ["NBA_ROSTERS = {"]
    
    for team, players in sorted(rosters.items()):
        lines.append(f'    "{team}": [')
        for player in sorted(players):
            lines.append(f'        "{player}",')
        lines.append("    ],")
    
    lines.append("}")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="NBA Roster Fetcher")
    parser.add_argument("--source", choices=["espn", "nba", "balldontlie"], 
                       default="espn", help="Data source")
    parser.add_argument("--python", action="store_true", 
                       help="Output as Python dict")
    
    args = parser.parse_args()
    
    print(f"Fetching NBA rosters from {args.source}...")
    
    if args.source == "espn":
        rosters = fetch_rosters_espn()
    elif args.source == "nba":
        rosters = fetch_rosters_nba_api()
    else:
        rosters = fetch_rosters_balldontlie()
    
    if rosters:
        save_rosters(rosters)
        
        if args.python:
            print("\n" + "="*60)
            print("Python dict for sentiment_analysis.py:")
            print("="*60)
            print(generate_python_dict(rosters))
        
        total_players = sum(len(p) for p in rosters.values())
        print(f"\nTotal: {len(rosters)} teams, {total_players} players")
    else:
        print("Failed to fetch rosters")
