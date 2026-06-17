"""
Fetch external events and load them into the external_events table.

Supports two sources:
  1. OKC Thunder home games  -- NBA schedule via balldontlie.io API (free, no key)
  2. Manual CSV import       -- for Civic Center events and others

Usage:
    python scripts/fetch_events.py thunder          # fetch Thunder home schedule
    python scripts/fetch_events.py csv <filepath>   # import events from CSV
    python scripts/fetch_events.py thunder --season 2025  # specific season

CSV format (header row required):
    event_date,event_time,venue,event_type,event_name,expected_impact,estimated_attendance,notes
    2026-03-15,19:00,civic_center,concert,Sample Concert,high,5000,
"""

import sys
import csv
import json
from pathlib import Path
from datetime import date, datetime, time

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.config import engine

THUNDER_TEAM_ID = 21  # OKC Thunder team ID on balldontlie.io


def fetch_thunder_schedule(season: int = None) -> int:
    """
    Fetch OKC Thunder home games from balldontlie.io free API.
    Inserts into external_events. Safe to re-run (ON CONFLICT DO NOTHING).

    Args:
        season: NBA season year (e.g. 2025 for the 2025-26 season).
                Defaults to current season.

    Returns: number of events inserted.
    """
    import urllib.request

    if season is None:
        today = date.today()
        season = today.year if today.month >= 10 else today.year - 1

    inserted = 0
    cursor = 0
    per_page = 100

    while True:
        url = (
            f"https://api.balldontlie.io/v1/games"
            f"?seasons[]={season}"
            f"&team_ids[]={THUNDER_TEAM_ID}"
            f"&per_page={per_page}"
            f"&cursor={cursor}"
        )

        req = urllib.request.Request(url)
        req.add_header("Authorization", "")

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
        except Exception as e:
            print(f"API request failed: {e}")
            print("Falling back to manual entry. You can import Thunder games via CSV.")
            break

        games = data.get("data", [])
        if not games:
            break

        with engine.begin() as conn:
            for game in games:
                if game.get("home_team", {}).get("id") != THUNDER_TEAM_ID:
                    continue

                game_date_str = game.get("date", "")[:10]
                if not game_date_str:
                    continue

                try:
                    game_date = datetime.strptime(game_date_str, "%Y-%m-%d").date()
                except ValueError:
                    continue

                visitor = game.get("visitor_team", {}).get("full_name", "TBD")
                status = game.get("status", "")
                is_playoff = game.get("postseason", False)

                event_name = f"OKC Thunder vs {visitor}"
                impact = "massive" if is_playoff else "high"

                game_time = None
                raw_time = game.get("time", "")
                if raw_time and ":" in raw_time:
                    try:
                        game_time = datetime.strptime(raw_time, "%H:%M").time()
                    except ValueError:
                        pass

                conn.execute(text("""
                    INSERT INTO external_events
                        (event_date, event_time, venue, event_type, event_name,
                         expected_impact, estimated_attendance, notes)
                    VALUES
                        (:ed, :et, 'paycom_center', 'thunder_home', :en,
                         :ei, 18000, :notes)
                    ON CONFLICT (event_date, venue, event_name) DO NOTHING
                """), {
                    "ed": game_date,
                    "et": game_time,
                    "en": event_name,
                    "ei": impact,
                    "notes": f"Season {season}-{season+1}, {status}" if status else f"Season {season}-{season+1}",
                })
                inserted += 1

        meta = data.get("meta", {})
        next_cursor = meta.get("next_cursor")
        if next_cursor is None or next_cursor <= cursor:
            break
        cursor = next_cursor

    return inserted


def import_events_csv(filepath: str) -> int:
    """
    Import events from a CSV file.

    Expected columns:
        event_date (YYYY-MM-DD), event_time (HH:MM, optional),
        venue, event_type, event_name,
        expected_impact (low/medium/high/massive),
        estimated_attendance (optional), notes (optional)

    Returns: number of events inserted.
    """
    path = Path(filepath)
    if not path.exists():
        print(f"File not found: {filepath}")
        return 0

    inserted = 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        with engine.begin() as conn:
            for row in reader:
                try:
                    event_date = datetime.strptime(row["event_date"].strip(), "%Y-%m-%d").date()
                except (ValueError, KeyError):
                    print(f"Skipping row with invalid date: {row}")
                    continue

                event_time = None
                raw_time = row.get("event_time", "").strip()
                if raw_time:
                    try:
                        event_time = datetime.strptime(raw_time, "%H:%M").time()
                    except ValueError:
                        pass

                venue = row.get("venue", "other").strip()
                event_type = row.get("event_type", "show").strip()
                event_name = row.get("event_name", "").strip()
                if not event_name:
                    continue

                impact = row.get("expected_impact", "medium").strip()
                if impact not in ("low", "medium", "high", "massive"):
                    impact = "medium"

                attendance = None
                raw_att = row.get("estimated_attendance", "").strip()
                if raw_att:
                    try:
                        attendance = int(raw_att)
                    except ValueError:
                        pass

                notes = row.get("notes", "").strip() or None

                conn.execute(text("""
                    INSERT INTO external_events
                        (event_date, event_time, venue, event_type, event_name,
                         expected_impact, estimated_attendance, notes)
                    VALUES
                        (:ed, :et, :v, :etype, :en, :ei, :ea, :notes)
                    ON CONFLICT (event_date, venue, event_name) DO NOTHING
                """), {
                    "ed": event_date,
                    "et": event_time,
                    "v": venue,
                    "etype": event_type,
                    "en": event_name,
                    "ei": impact,
                    "ea": attendance,
                    "notes": notes,
                })
                inserted += 1

    return inserted


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python scripts/fetch_events.py thunder [--season YYYY]")
        print("  python scripts/fetch_events.py csv <filepath>")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "thunder":
        season = None
        if "--season" in sys.argv:
            idx = sys.argv.index("--season")
            if idx + 1 < len(sys.argv):
                season = int(sys.argv[idx + 1])
        count = fetch_thunder_schedule(season=season)
        print(f"Loaded {count} Thunder home games into external_events.")

    elif command == "csv":
        if len(sys.argv) < 3:
            print("Usage: python scripts/fetch_events.py csv <filepath>")
            sys.exit(1)
        count = import_events_csv(sys.argv[2])
        print(f"Imported {count} events from CSV.")

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
