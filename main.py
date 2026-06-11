"""
Main — הסקריפט שרץ בכל מחזור cron.

1. קורא picks מ-Supabase (הבחירות של כל המשתתפים)
2. מושך מצב טורניר מ-API-Football
3. מחשב ניקוד לכולם (stateless, מאפס)
4. שומר דירוג קודם ← מחשב movement
5. כותב leaderboard ל-Supabase
"""

import os
import sys
import json
import logging
from datetime import datetime, timezone

import requests
from scoring import Picks, Tournament, build_leaderboard
from api_adapter import build_tournament_from_api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ──────────────── Supabase config ────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")  # service_role!

SB_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}


def sb_get(table: str, params: dict = None) -> list[dict]:
    """קריאה מ-Supabase REST API."""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {**SB_HEADERS, "Prefer": "return=representation"}
    resp = requests.get(url, headers=headers, params=params or {}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def sb_upsert(table: str, rows: list[dict]):
    """כתיבה (upsert) ל-Supabase REST API."""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {**SB_HEADERS, "Prefer": "resolution=merge-duplicates"}
    resp = requests.post(url, headers=headers, json=rows, timeout=15)
    resp.raise_for_status()
    log.info(f"Upserted {len(rows)} rows to {table}")


def read_picks() -> list[Picks]:
    """קורא את הבחירות מ-Supabase ומחזיר רשימת Picks."""
    raw = sb_get("picks", {"select": "*"})
    picks = []
    for r in raw:
        picks.append(Picks(
            name=r["name"],
            tier_a=r["tier_a"],
            tier_b=r["tier_b"],
            tier_c=r["tier_c"],
            tier_d=r["tier_d"],
            scorer=r["scorer"],
            conceder=r["conceder"],
            top_scorer=r["top_scorer"],
        ))
    log.info(f"Read {len(picks)} picks from Supabase")
    return picks


def read_current_ranks() -> dict[str, int]:
    """קורא את הדירוג הנוכחי (לפני העדכון) כדי לחשב movement."""
    raw = sb_get("leaderboard", {"select": "name,rank"})
    return {r["name"]: r["rank"] for r in raw}


def run():
    """ריצה אחת של המחזור."""
    log.info("=" * 60)
    log.info("Starting leaderboard update cycle")

    # 1. קריאת בחירות
    picks = read_picks()
    if not picks:
        log.warning("No picks found, aborting")
        return

    # 2. דירוג קודם (ל-movement)
    prev_rank = read_current_ranks()

    # 3. מצב הטורניר מ-API
    tournament = build_tournament_from_api()

    # 4. חישוב ניקוד
    rows = build_leaderboard(picks, tournament, prev_rank)

    # 5. כתיבה ל-Supabase
    sb_upsert("leaderboard", rows)

    log.info(f"Done — {len(rows)} rows updated. Top 3:")
    for r in rows[:3]:
        log.info(f"  #{r['rank']} {r['name']} — {r['total']} pts")
    log.info("=" * 60)


if __name__ == "__main__":
    # בדיקת env vars
    missing = []
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not SUPABASE_KEY:
        missing.append("SUPABASE_SERVICE_KEY")
    if not os.environ.get("FOOTBALL_DATA_KEY"):
        missing.append("FOOTBALL_DATA_KEY")
    if missing:
        log.error(f"Missing environment variables: {', '.join(missing)}")
        sys.exit(1)
    run()
