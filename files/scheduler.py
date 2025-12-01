#!/usr/bin/env python3
"""
NBA Transcript Scraper Scheduler

This script sets up scheduled execution of the NBA transcript scraper.
It can run as a long-running process or generate crontab entries.

For deployment options:
1. Cron (Linux/Mac) - Use the generated crontab entry
2. systemd timer - Use the generated service/timer files  
3. Cloud scheduler - AWS EventBridge, GCP Cloud Scheduler, etc.
4. This script as a daemon - Run with --daemon flag
"""

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import schedule

# Path to the scraper script
SCRAPER_PATH = Path(__file__).parent / "scraper.py"


def run_scraper():
    """Execute the scraper script."""
    print(f"\n{'='*60}")
    print(f"Starting scheduled scrape at {datetime.now()}")
    print(f"{'='*60}\n")
    
    try:
        result = subprocess.run(
            [sys.executable, str(SCRAPER_PATH)],
            capture_output=True,
            text=True,
        )
        print(result.stdout)
        if result.stderr:
            print(f"Errors: {result.stderr}")
        print(f"\nScrape completed with return code: {result.returncode}")
    except Exception as e:
        print(f"Error running scraper: {e}")


def run_daemon():
    """Run as a long-running daemon with scheduled execution."""
    print("Starting NBA Transcript Scraper Daemon")
    print("Scheduled to run daily at 11:00 PM Pacific Time")
    print("Press Ctrl+C to stop\n")
    
    # Schedule for 11 PM Pacific
    # Note: The schedule library uses the system timezone
    # If your server is in UTC, adjust accordingly (11 PM PT = 7 AM UTC next day during PST)
    schedule.every().day.at("23:00").do(run_scraper)
    
    # Also run immediately on startup to catch up
    print("Running initial scrape on startup...")
    run_scraper()
    
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute


def generate_crontab():
    """Generate crontab entry for 11 PM Pacific Time."""
    script_path = Path(__file__).parent.resolve() / "scraper.py"
    python_path = sys.executable
    
    # 11 PM Pacific = 7 AM UTC (during PST) or 6 AM UTC (during PDT)
    # Using PST (standard time) - adjust if needed
    cron_entry = f"""
# NBA Coach Postgame Transcript Scraper
# Runs daily at 11:00 PM Pacific Time (7:00 AM UTC during PST)
# To install: crontab -e and paste this line
0 7 * * * cd {script_path.parent} && {python_path} {script_path} >> {script_path.parent}/cron.log 2>&1

# If your system supports TZ variable in cron:
# CRON_TZ=America/Los_Angeles
# 0 23 * * * cd {script_path.parent} && {python_path} {script_path} >> {script_path.parent}/cron.log 2>&1
"""
    print(cron_entry)
    return cron_entry


def generate_systemd_files():
    """Generate systemd service and timer files."""
    script_path = Path(__file__).parent.resolve() / "scraper.py"
    python_path = sys.executable
    
    service_content = f"""[Unit]
Description=NBA Coach Postgame Transcript Scraper
After=network.target

[Service]
Type=oneshot
WorkingDirectory={script_path.parent}
ExecStart={python_path} {script_path}
StandardOutput=append:{script_path.parent}/scraper.log
StandardError=append:{script_path.parent}/scraper.log

[Install]
WantedBy=multi-user.target
"""
    
    timer_content = """[Unit]
Description=Run NBA Transcript Scraper daily at 11 PM Pacific

[Timer]
OnCalendar=*-*-* 23:00:00 America/Los_Angeles
Persistent=true

[Install]
WantedBy=timers.target
"""
    
    print("=== nba-transcripts.service ===")
    print(service_content)
    print("\n=== nba-transcripts.timer ===")
    print(timer_content)
    print("\nTo install:")
    print("1. Save these files to /etc/systemd/system/")
    print("2. Run: sudo systemctl daemon-reload")
    print("3. Run: sudo systemctl enable --now nba-transcripts.timer")
    
    return service_content, timer_content


def generate_github_actions():
    """Generate GitHub Actions workflow for scheduled runs."""
    workflow = """name: NBA Transcript Scraper

on:
  schedule:
    # 7 AM UTC = 11 PM Pacific (PST)
    # Adjust to 6 AM UTC during PDT if needed
    - cron: '0 7 * * *'
  workflow_dispatch:  # Allow manual triggers

jobs:
  scrape:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          
      - name: Run scraper
        env:
          YOUTUBE_API_KEY: ${{ secrets.YOUTUBE_API_KEY }}
        run: |
          python scraper.py
          
      - name: Upload transcripts
        uses: actions/upload-artifact@v4
        with:
          name: transcripts-${{ github.run_number }}
          path: transcripts/
          retention-days: 90
          
      - name: Commit new transcripts
        run: |
          git config --local user.email "action@github.com"
          git config --local user.name "GitHub Action"
          git add transcripts/ transcripts.db
          git diff --staged --quiet || git commit -m "Add transcripts for $(date +%Y-%m-%d)"
          git push
"""
    print("=== .github/workflows/scrape.yml ===")
    print(workflow)
    return workflow


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="NBA Transcript Scraper Scheduler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Deployment Options:
  --daemon          Run as a long-running daemon (good for Docker/VMs)
  --cron            Generate crontab entry
  --systemd         Generate systemd service/timer files  
  --github-actions  Generate GitHub Actions workflow
  --run-now         Run the scraper immediately (for testing)
        """,
    )
    
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    parser.add_argument("--cron", action="store_true", help="Generate crontab entry")
    parser.add_argument("--systemd", action="store_true", help="Generate systemd files")
    parser.add_argument("--github-actions", action="store_true", help="Generate GH Actions workflow")
    parser.add_argument("--run-now", action="store_true", help="Run scraper immediately")
    
    args = parser.parse_args()
    
    if args.daemon:
        # Need schedule library for daemon mode
        try:
            import schedule
        except ImportError:
            print("Installing schedule library...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "schedule"])
            import schedule
        run_daemon()
    elif args.cron:
        generate_crontab()
    elif args.systemd:
        generate_systemd_files()
    elif args.github_actions:
        generate_github_actions()
    elif args.run_now:
        run_scraper()
    else:
        parser.print_help()
