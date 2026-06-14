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
import time
import logging
from datetime import datetime, timezone

import requests
from scoring import Picks, Tournament, build_leaderboard
from api_adapter import build_tournament_from_api, APIFetchError, DIAG

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


def read_current_ranks() -> dict[str, dict]:
    """קורא את הדירוג וה-movement הנוכחיים (לפני העדכון).
    מחזיר {name: {"rank": int, "movement": int}}."""
    raw = sb_get("leaderboard", {"select": "name,rank,movement"})
    return {r["name"]: {"rank": r["rank"], "movement": r.get("movement", 0) or 0} for r in raw}


def read_baseline_ranks() -> dict:
    """קורא את ה-baseline היציב (הדירוג מלפני שהמשחקים החיים התחילו) מ-live_status.
    מחזיר {name: rank}. אם אין — מילון ריק."""
    try:
        raw = sb_get("live_status", {"select": "baseline_ranks", "id": "eq.1"})
        if raw and raw[0].get("baseline_ranks"):
            return raw[0]["baseline_ranks"]
    except Exception as e:
        log.warning(f"Could not read baseline_ranks (non-fatal): {e}")
    return {}


def read_current_max_total() -> float:
    """כמה 'מאוכלס' הלוח הקיים? משמש כשמירה מפני דריסה באפסים."""
    try:
        raw = sb_get("leaderboard", {"select": "total"})
        return max((float(r.get("total") or 0) for r in raw), default=0.0)
    except Exception as e:
        log.warning(f"Could not read current leaderboard totals: {e}")
        return 0.0


def write_sync_log(record: dict):
    """כותב שורת אבחון אחת לטבלת sync_log ב-Supabase. Fail-safe לחלוטין:
    אם הטבלה לא קיימת או הכתיבה נכשלת — רק מזהיר, לעולם לא מפיל את הריצה."""
    try:
        url = f"{SUPABASE_URL}/rest/v1/sync_log"
        headers = {**SB_HEADERS, "Prefer": "return=minimal"}
        resp = requests.post(url, headers=headers, json=[record], timeout=10)
        if resp.status_code >= 400:
            log.warning(f"sync_log write returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log.warning(f"Could not write sync_log (non-fatal): {e}")


def print_diag_summary(record: dict):
    """מדפיס בלוק סיכום ברור — מופיע בלוגי GitHub Actions לכל ריצה."""
    log.info("┌─────────────── SYNC DIAGNOSTICS ───────────────")
    log.info(f"│ decision     : {record['decision']}")
    log.info(f"│ fetch_ok     : {record['fetch_ok']}  http={record['http_status']}  attempts={record['attempts']}")
    log.info(f"│ games        : {record['n_games']} total → {record['n_finished']} finished")
    log.info(f"│ scorers      : {record['n_scorers']}  detail_fails={record['n_detail_fail']}")
    log.info(f"│ leaderboard  : prev_max={record['prev_max']} → new_max={record['new_max']}")
    log.info(f"│ duration     : {record['duration_ms']} ms")
    if record.get("error"):
        log.info(f"│ ERROR        : {record['error']}")
    if record.get("raw_sample"):
        log.info(f"│ raw_sample   : {record['raw_sample'][:200]}")
    log.info("└────────────────────────────────────────────────")


def run():
    """ריצה אחת של המחזור."""
    t0 = time.time()
    log.info("=" * 60)
    log.info("Starting leaderboard update cycle")

    decision = "UNKNOWN"
    prev_max = 0.0
    new_max = 0.0

    try:
        # 1. קריאת בחירות
        picks = read_picks()
        if not picks:
            decision = "SKIP_NO_PICKS"
            log.warning("No picks found, aborting")
            return

        # 2. מצב קודם (rank + movement) + baseline יציב + כמה הלוח מאוכלס
        prev_state = read_current_ranks()
        baseline_rank = read_baseline_ranks()
        prev_max = read_current_max_total()

        # 3. מצב הטורניר מ-API — אם הקריאה נכשלה, מדלגים על הכתיבה כדי לא לאפס את הלוח
        try:
            tournament = build_tournament_from_api()
        except APIFetchError as e:
            decision = "SKIP_FETCH_FAILED"
            log.error(f"API fetch failed — SKIPPING write to avoid wiping leaderboard. {e}")
            return

        # 4. שמירה על בסיס איכות הקריאה — לא על בסיס גובה הניקוד.
        #    דלג רק כש-/games החזיר 200 עם payload ריק (קריאה רעה). כך לוח
        #    תיקו/אפס לגיטימי כן נכתב — וזה מה שמתקן נתונים ישנים תקועים.
        #    (כשל רשת כבר נתפס למעלה כ-APIFetchError.)
        if DIAG.get("n_games", 0) == 0:
            decision = "SKIP_EMPTY_READ"
            log.error(
                "API returned 200 but ZERO games (empty/garbage payload) — "
                f"raw_sample={DIAG.get('raw_sample')!r}. SKIPPING write to protect leaderboard."
            )
            return

        # 5. חישוב ניקוד + כתיבה
        rows = build_leaderboard(picks, tournament, prev_state, baseline_rank)
        new_max = max((r["total"] for r in rows), default=0.0)
        sb_upsert("leaderboard", rows)

        # 6. כתיבת סטטוס משחקים חיים + baseline לטבלת live_status
        live_displays = DIAG.get("live_displays", [])
        has_live = bool(tournament.live_teams)
        # ה-baseline מתעדכן רק כשאין משחקים חיים — כך הוא מחזיק את "המצב היציב האחרון".
        # בזמן משחק חי משאירים את ה-baseline הישן (מלפני שהמשחק התחיל).
        new_baseline = ({r["name"]: r["rank"] for r in rows}
                        if not has_live else baseline_rank)
        sb_upsert("live_status", [{
            "id": 1,  # שורה יחידה — תמיד תידרס
            "matches": live_displays,
            "baseline_ranks": new_baseline,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }])
        if live_displays:
            log.info(f"Live matches: {live_displays}")
        decision = "WRITE"

        log.info(f"Done — {len(rows)} rows updated. Top 3:")
        for r in rows[:3]:
            log.info(f"  #{r['rank']} {r['name']} — {r['total']} pts")

    finally:
        # תיעוד אבחון תמיד — בכל מסלול (כתיבה או דילוג), כדי שנבין למה
        record = {
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": int((time.time() - t0) * 1000),
            "decision": decision,
            "fetch_ok": DIAG.get("fetch_ok"),
            "http_status": DIAG.get("http_status"),
            "attempts": DIAG.get("attempts", 0),
            "raw_bytes": DIAG.get("raw_bytes", 0),
            "n_games": DIAG.get("n_games", 0),
            "n_finished": DIAG.get("n_finished", 0),
            "n_scorers": DIAG.get("n_scorers", 0),
            "n_detail_fail": DIAG.get("n_detail_fail", 0),
            "prev_max": prev_max,
            "new_max": new_max,
            "error": DIAG.get("error"),
            "raw_sample": DIAG.get("raw_sample"),
        }
        print_diag_summary(record)
        write_sync_log(record)
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
