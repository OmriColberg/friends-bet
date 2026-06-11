"""
סקריפט בדיקה — מוודא שה-football-data.org מחזיר נתונים למונדיאל 2026.
הרץ עם: FOOTBALL_DATA_KEY=xxx python test_api.py
"""

import os
import sys

key = os.environ.get("FOOTBALL_DATA_KEY", "")
if not key:
    print("❌ Missing FOOTBALL_DATA_KEY environment variable")
    print("   Usage:")
    print("   Linux/Mac:  export FOOTBALL_DATA_KEY=your_key && python test_api.py")
    print("   Windows PS: $env:FOOTBALL_DATA_KEY='your_key'; python test_api.py")
    print("   Windows CMD: set FOOTBALL_DATA_KEY=your_key && python test_api.py")
    print("")
    print("   Get a free key at: https://www.football-data.org/client/register")
    sys.exit(1)

from api_adapter import fetch_matches, fetch_standings, fetch_scorers
from mappings import normalize_team, TEAM_ENG_TO_HEB

print("=" * 50)
print("בדיקת חיבור ל-football-data.org — מונדיאל 2026")
print("=" * 50)

# 1. Matches
print("\n1️⃣  Fetching matches...")
try:
    matches = fetch_matches()
    print(f"   ✅ {len(matches)} matches returned")
    finished = [m for m in matches if m.get("status") == "FINISHED"]
    live = [m for m in matches if m.get("status") in ("IN_PLAY", "PAUSED", "HALFTIME")]
    scheduled = len(matches) - len(finished) - len(live)
    print(f"   Finished: {len(finished)} | Live: {len(live)} | Scheduled: {scheduled}")

    if matches:
        m0 = matches[0]
        home = m0.get("homeTeam", {}).get("name", "?")
        away = m0.get("awayTeam", {}).get("name", "?")
        status = m0.get("status", "?")
        print(f"   Example: {home} vs {away} (status: {status})")

    # בדיקת מיפוי שמות
    print("\n   Checking team name mappings...")
    unknown = set()
    for m in matches:
        for side in ("homeTeam", "awayTeam"):
            name = m.get(side, {}).get("name", "")
            eng = normalize_team(name)
            if eng not in TEAM_ENG_TO_HEB:
                unknown.add(f"{name} → {eng}")
    if unknown:
        print(f"   ⚠️  {len(unknown)} unmapped teams (need to add to mappings.py):")
        for u in sorted(unknown):
            print(f"      {u}")
    else:
        print("   ✅ All teams mapped to Hebrew")
except Exception as e:
    print(f"   ❌ Error: {e}")
    sys.exit(1)

# 2. Standings
print("\n2️⃣  Fetching standings...")
try:
    standings = fetch_standings()
    groups = len([s for s in standings if s.get("type") == "TOTAL"])
    print(f"   ✅ {groups} groups returned")
except Exception as e:
    print(f"   ❌ Error: {e}")

# 3. Scorers
print("\n3️⃣  Fetching scorers...")
try:
    scorers = fetch_scorers()
    print(f"   ✅ {len(scorers)} scorers returned")
    if scorers:
        top = scorers[0]
        name = top.get("player", {}).get("name", "?")
        goals = top.get("goals", 0)
        print(f"   Top: {name} ({goals} goals)")
except Exception as e:
    print(f"   ❌ Error: {e}")

print("\n" + "=" * 50)
print("בדיקה הושלמה!")
print("=" * 50)
