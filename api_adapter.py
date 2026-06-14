"""
שכבה 1 — Adapter ל-worldcup26.ir (משולב: משחקים + כובשי שערים).
API חינמי, פתוח לחלוטין וללא צורך במפתח (API Key).

אנדפוינטים בשימוש:
  GET https://worldcup26.ir/get/games      -> כל המשחקים, התוצאות והסטטוסים
  GET https://worldcup26.ir/get/game/{id}  -> מידע מורחב על משחק ספציפי כולל מערך כובשי שערים
"""

import time
import logging
import requests
from scoring import Tournament, Match, TeamState
from mappings import normalize_team, TEAM_ENG_TO_HEB, match_player, PLAYER_HEB_TO_SEARCH

log = logging.getLogger(__name__)

BASE_URL = "https://worldcup26.ir/get"


class APIFetchError(Exception):
    """נזרק כשלא ניתן לקרוא את ה-API. מסמן 'מצב לא ידוע' — לא 'מצב אפס'.
    קריטי: בלי זה, כל כשל רשת מתחזה ל'אין משחקים' ומאפס את כל הלוח."""
    pass


# ──────────────── Diagnostics: מה ה-API באמת החזיר בריצה הזו ────────────────
# נאסף לאורך הריצה, ונקרא ע"י main.py כדי לכתוב שורת sync_log + להדפיס סיכום.
DIAG: dict = {}


def _reset_diag():
    DIAG.clear()
    DIAG.update({
        "fetch_ok": None,      # האם /games נקרא בהצלחה
        "http_status": None,   # קוד HTTP אחרון של /games
        "attempts": 0,         # כמה ניסיונות נדרשו
        "raw_bytes": 0,        # גודל ה-payload הגולמי
        "n_games": 0,          # כמה משחקים חזרו בסך הכל
        "n_finished": 0,       # כמה נותחו כ"הסתיימו"
        "n_scorers": 0,        # כמה אירועי גול נאספו
        "n_detail_fail": 0,    # כמה קריאות פרטים נכשלו (סימן ל-rate-limit)
        "error": None,         # הודעת השגיאה אם נכשל
        "raw_sample": None,    # 400 התווים הראשונים — כשהקריאה נכשלה או חזרה ריקה
    })

# מיפוי השלבים מה-API למנוע הניקוד הפנימי של הטורניר
STAGE_MAP = {
    "group":         "group",
    "r32":           "r32",
    "r16":           "r16",
    "qf":            "qf",
    "sf":            "sf",
    "third_place":   "third_place",
    "final":         "final",
}


def fetch_matches(retries: int = 3, backoff: float = 2.0) -> list[dict]:
    """מושך את רשימת כל המשחקים. נכשל בקול (raise) במקום להחזיר רשימה ריקה,
    כדי שהאורקסטרטור יבחין בין 'כשל קריאה' לבין 'אין משחקים שהסתיימו'.
    לאורך הדרך ממלא את DIAG כדי שנבין בדיוק מה ה-API החזיר."""
    url = f"{BASE_URL}/games"
    log.info(f"Calling public World Cup API: {url}")
    last_err = None
    for attempt in range(1, retries + 1):
        DIAG["attempts"] = attempt
        try:
            resp = requests.get(url, timeout=20)
            DIAG["http_status"] = resp.status_code
            DIAG["raw_bytes"] = len(resp.content or b"")
            resp.raise_for_status()
            data = resp.json()
            games = data.get("games", []) or []
            DIAG["n_games"] = len(games)
            DIAG["fetch_ok"] = True
            # אם 200 אבל ריק — שומרים דגימה כדי להבין למה (זה התרחיש שמאפס את הלוח)
            if not games:
                DIAG["raw_sample"] = (resp.text or "")[:400]
                log.warning(f"/games returned 200 but ZERO games. status={resp.status_code} bytes={DIAG['raw_bytes']}")
            return games
        except Exception as e:
            last_err = e
            # ניסיון ללכוד גוף תשובה גם בכשל (למשל HTML של Cloudflare/429)
            body = getattr(getattr(e, "response", None), "text", None)
            if body:
                DIAG["raw_sample"] = body[:400]
            log.warning(f"fetch_matches attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(backoff * attempt)  # backoff לינארי: 2s, 4s
    # מיצינו את הניסיונות — מסמנים כשל במקום להעמיד פנים שאין משחקים
    DIAG["fetch_ok"] = False
    DIAG["error"] = str(last_err)
    raise APIFetchError(f"Could not fetch games after {retries} attempts: {last_err}")


def fetch_game_details(game_id: str) -> dict:
    """מושך פרטי משחק ספציפי הכולל את רשימת כובשי השערים המורחבת"""
    url = f"{BASE_URL}/game/{game_id}"
    log.info(f"Calling detailed game API for ID {game_id}: {url}")
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json().get("game", {}) or {}
    except Exception as e:
        log.error(f"Failed to fetch game details for ID {game_id}: {e}")
        return {}


def _to_heb(api_name: str) -> str:
    if not api_name or api_name.lower() == "null" or api_name == "None":
        return "TBD"
    eng = normalize_team(api_name)
    return TEAM_ENG_TO_HEB.get(eng, eng)


def _parse_match(game: dict) -> Match | None:
    # בדיקה האם המשחק הסתיים (לפי השדות שחוזרים ב-API הכללי)
    is_finished = (
        str(game.get("finished", "")).lower() == "true" or
        game.get("time_elapsed") == "finished"
    )
    if not is_finished:
        return None

    home_raw = game.get("home_team_name_en", "") or game.get("home_team_en", "")
    away_raw = game.get("away_team_name_en", "") or game.get("away_team_en", "")
    home = _to_heb(home_raw)
    away = _to_heb(away_raw)

    # משחקי placeholder — הנבחרות עדיין לא נקבעו (TBD). מתעלמים מהם לחלוטין.
    # ה-API מחזיר אותם כ"הסתיים" אבל אין בהם נתון אמיתי, וקריאת game/{id} עליהם מחזירה 400.
    if home == "TBD" or away == "TBD":
        log.info(f"  SKIPPING placeholder match (TBD): id={game.get('id')} score={game.get('home_score')}-{game.get('away_score')}")
        return None

    try:
        home_goals = int(game.get("home_score", 0))
        away_goals = int(game.get("away_score", 0))
    except (ValueError, TypeError):
        home_goals, away_goals = 0, 0

    log.info(f"  PARSED MATCH: {home} {home_goals}-{away_goals} {away}")

    # בדיקת הכרעות פנדלים בשלבי נוקאאוט
    decided_by = "regular"
    pen_winner = None
    if game.get("penalty_winner"):
        decided_by = "penalties"
        pen_winner = _to_heb(game.get("penalty_winner"))

    stage_raw = game.get("type", "group")
    stage = STAGE_MAP.get(stage_raw, "group")

    return Match(
        home=home, away=away,
        home_goals=home_goals, away_goals=away_goals,
        stage=stage, finished=True,
        decided_by=decided_by, pen_winner=pen_winner,
    )


def build_tournament_from_api() -> Tournament:
    _reset_diag()
    raw_games = fetch_matches()

    matches = []
    live_matches = []   # משחקים פעילים כרגע — לסימון בלוח
    api_extracted_scorers = {}
    teams = {}

    for game in raw_games:
        # משחק חי — מחשבים ניקוד חלקי ושומרים לסימון
        is_live = str(game.get("time_elapsed", "")).lower() == "live"
        if is_live:
            parsed_live = _parse_match_live(game)
            if parsed_live:
                live_matches.append(parsed_live)
                matches.append(parsed_live)

        parsed = _parse_match(game)
        if parsed:
            matches.append(parsed)

        # כובשי שערים — גם ממשחקים גמורים וגם מחיים
        if parsed or is_live:
            for field in ("home_scorers", "away_scorers"):
                raw = game.get(field, "") or ""
                if not raw or raw.lower() == "null":
                    continue
                raw = raw.strip("{}")
                for entry in raw.split('","'):
                    entry = entry.strip().strip('"').strip("'")
                    import re
                    name = re.sub(r"\s+\d+['′]?\s*$", "", entry).strip()
                    if name:
                        api_extracted_scorers[name] = api_extracted_scorers.get(name, 0) + 1

    # בניית תצוגת משחקים חיים — "ברזיל 1-1 מרוקו דקה 60"
    live_displays = []
    for game in raw_games:
        if str(game.get("time_elapsed", "")).lower() != "live":
            continue
        home = _to_heb(game.get("home_team_name_en", "") or game.get("home_team_en", ""))
        away = _to_heb(game.get("away_team_name_en", "") or game.get("away_team_en", ""))
        if home == "TBD" or away == "TBD":
            continue
        hs = game.get("home_score", "0") or "0"
        as_ = game.get("away_score", "0") or "0"
        elapsed = game.get("elapsed", "") or game.get("minute", "") or ""
        minute_str = f" דקה {elapsed}" if elapsed else ""
        live_displays.append(f"{home} {hs}-{as_} {away}{minute_str}")

    DIAG["live_displays"] = live_displays

    live_team_names = set()
    for m in live_matches:
        live_team_names.add(m.home)
        live_team_names.add(m.away)

    log.info(f"Processed {len(matches)} finished/live matches out of {len(raw_games)} total games (live: {len(live_matches)})")
    DIAG["n_finished"] = len([m for m in matches if m.finished])
    DIAG["n_live"] = len(live_matches)
    DIAG["n_scorers"] = sum(api_extracted_scorers.values())

    # זיהוי עולות שלב לפי השתתפות בפועל במשחקי נוקאאוט בטורניר
    knockout_teams = set()
    for m in matches:
        if m.stage in ("r32", "r16", "qf", "sf", "third_place", "final"):
            knockout_teams.add(m.home)
            knockout_teams.add(m.away)
            
    for name in knockout_teams:
        teams[name] = TeamState(qualified_r32=True)

    # זיהוי הגעה לגמר וזכייה באליפות
    for m in matches:
        if m.stage == "final":
            teams.setdefault(m.home, TeamState()).reached_final = True
            teams.setdefault(m.away, TeamState()).reached_final = True
            if m.decided_by == "penalties":
                winner = m.pen_winner
            elif m.home_goals > m.away_goals:
                winner = m.home
            else:
                winner = m.away
            if winner:
                teams.setdefault(winner, TeamState()).won_cup = True
                teams[winner].reached_final = True

    # התאמת שמות המבקיעים מה-API לשמות בעברית עבור מנוע הניקוד
    player_goals = {}
    for heb_name in PLAYER_HEB_TO_SEARCH:
        player_goals[heb_name] = 0
        for api_player_name, goals in api_extracted_scorers.items():
            if match_player(api_player_name, heb_name):
                player_goals[heb_name] += goals
                log.info(f"  Scorer Match: {heb_name} -> {api_player_name} ({goals} goals parsed)")

    t = Tournament(
        matches=matches,  # כולל משחקים חיים — הניקוד מתעדכן תוך כדי
        teams=teams,
        player_goals=player_goals,
        golden_boot=None,
        live_teams=live_team_names,
    )

    log.info("Tournament mapping completed successfully from worldcup26.ir.")
    return t


def _parse_match_live(game: dict):
    """מנתח משחק חי — מחזיר Match עם finished=False לצורך סימון בלוח."""
    home_raw = game.get("home_team_name_en", "") or game.get("home_team_en", "")
    away_raw = game.get("away_team_name_en", "") or game.get("away_team_en", "")
    home = _to_heb(home_raw)
    away = _to_heb(away_raw)
    if home == "TBD" or away == "TBD" or not home or not away:
        return None
    home_goals = int(game.get("home_score", 0) or 0)
    away_goals = int(game.get("away_score", 0) or 0)
    stage = _parse_stage(game)
    return Match(home=home, away=away, home_goals=home_goals,
                 away_goals=away_goals, stage=stage, finished=False)
