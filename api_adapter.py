"""
שכבה 1 — Adapter ל-TheSportsDB (v1).
מותאם למפתח הטסט החינמי '123' או למפתח פרימיום.

אנדפוינטים מרכזיים:
  eventsseason.php?id=4344&s=2026 -> כל משחקי המונדיאל, תוצאות וכובשי שערים (מתוך פרטי המשחק)
"""

import os
import re
import logging
import requests
from scoring import Tournament, Match, TeamState
from mappings import normalize_team, TEAM_ENG_TO_HEB, match_player, PLAYER_HEB_TO_SEARCH

log = logging.getLogger(__name__)

# שליחת מפתח ה-API מתוך ה-env, ברירת מחדל לטסט החינמי 123
API_KEY = os.environ.get("FOOTBALL_DATA_KEY", "123")
BASE_URL = f"https://www.thesportsdb.com/api/v1/json/{API_KEY}"

# מזהה הליגה של ה-FIFA World Cup ב-TheSportsDB
WORLD_CUP_LEAGUE_ID = "4344"

# סטטוסים ב-TheSportsDB המצביעים על משחק שהסתיים
FINISHED_STATUSES = {"Match Finished", "FT"}

# מיפוי שלבים לפי שמות ה-Round או הסטטוס בתוך ה-API
STAGE_MAP = {
    "Group Stage":      "group",
    "Round of 32":      "r32",
    "Round of 16":      "r16",
    "Quarter-Final":    "qf",
    "Semi-Final":       "sf",
    "3rd Place Playoff": "third_place",
    "Final":            "final",
}


def _api_get(endpoint: str, params: dict = None) -> dict:
    url = f"{BASE_URL}/{endpoint}"
    log.info(f"TheSportsDB API call: {url} with params {params}")
    resp = requests.get(url, params=params or {}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_world_cup_data() -> list[dict]:
    """מושך את כל המשחקים לעונת מונדיאל 2026"""
    data = _api_get("eventsseason.php", {"id": WORLD_CUP_LEAGUE_ID, "s": "2026"})
    return data.get("events", []) or []


def _to_heb(api_name: str) -> str:
    if not api_name or api_name == "None":
        return "TBD"
    eng = normalize_team(api_name)
    return TEAM_ENG_TO_HEB.get(eng, eng)


def _parse_match(event: dict) -> Match | None:
    # בדיקה האם המשחק הסתיים
    status = event.get("strStatus", "")
    if status not in FINISHED_STATUSES:
        return None

    home_raw = event.get("strHomeTeam", "")
    away_raw = event.get("strAwayTeam", "")
    home = _to_heb(home_raw)
    away = _to_heb(away_raw)

    # השגת גולים (TheSportsDB מחזיר כמחרוזת או מספר)
    try:
        home_goals = int(event.get("intHomeScore") or 0)
        away_goals = int(event.get("intAwayScore") or 0)
    except (ValueError, TypeError):
        home_goals, away_goals = 0, 0

    log.info(f"  RAW MATCH: {home_raw} vs {away_raw} | score={home_goals}-{away_goals}")

    # בדיקת הכרעה בפנדלים (TheSportsDB שומר לעיתים בתוך שדה ייעודי או הערות)
    decided_by = "regular"
    pen_winner = None
    
    # ניסיון חילוץ מנצחת פנדלים במידה והיה תיקו והמשחק גמור
    # הערה: במידת הצורך בגרסת פרימיום v2 יש שדות מובנים יותר לפנדלים
    if home_goals == away_goals and event.get("strResult"):
        result_text = event.get("strResult", "")
        if "penalties" in result_text.lower():
            decided_by = "penalties"
            if home_raw.lower() in result_text.lower():
                pen_winner = home
            elif away_raw.lower() in result_text.lower():
                pen_winner = away

    # זיהוי השלב
    round_name = event.get("strRound", "Group Stage")
    stage = STAGE_MAP.get(round_name, "group")

    return Match(
        home=home, away=away,
        home_goals=home_goals, away_goals=away_goals,
        stage=stage, finished=True,
        decided_by=decided_by, pen_winner=pen_winner,
    )


def _extract_goals_from_details(goal_details: str) -> list[str]:
    """
    מפרק מחרוזת שערים מהפורמט של TheSportsDB (למשל: "23':Harry Kane; 45':Raheem Sterling;")
    ומחזיר רשימת שמות שחקנים שהבקיעו.
    """
    if not goal_details or goal_details == "None":
        return []
    
    players = []
    # פירוק לפי נקודה-פסיק או פסיק, תלוי באיך שהדאטה מוזן ב-API באותו רגע
    parts = re.split(r'[;,\n]', goal_details)
    for part in parts:
        if not part.strip():
            continue
        # הסרת דקות וסימנים מיוחדים (למשל "23': Name" או "Name 23'")
        clean_part = re.sub(r"\d+'?", "", part)
        clean_part = clean_part.replace(":", "").replace("'", "").strip()
        if clean_part:
            players.append(clean_part)
            
    return players


def build_tournament_from_api() -> Tournament:
    log.info("Fetching World Cup 2026 data from TheSportsDB...")
    raw_events = fetch_world_cup_data()

    matches = []
    api_extracted_scorers = {}  # שם שחקן באנגלית (מה-API) -> כמות שערים
    teams = {}

    for event in raw_events:
        # 1. עיבוד משחק
        parsed = _parse_match(event)
        if parsed:
            matches.append(parsed)
            
            # 2. חילוץ כובשי שערים מתוך פרטי המשחק הגמור
            home_goals_str = event.get("strHomeGoalDetails", "")
            away_goals_str = event.get("strAwayGoalDetails", "")
            
            all_match_scorers = (_extract_goals_from_details(home_goals_str) + 
                                 _extract_goals_from_details(away_goals_str))
            
            for player_name in all_match_scorers:
                api_extracted_scorers[player_name] = api_extracted_scorers.get(player_name, 0) + 1

    log.info(f"Parsed {len(matches)} finished matches out of {len(raw_events)} total events")

    # 3. בניית מצב עליית קבוצות על בסיס משחקי הנוקאאוט הקיימים
    # (מכיוון שה-API החינמי לא כולל אנדפוינט standings ישיר למונדיאל ללא מפתח מורחב)
    knockout_teams = set()
    for m in matches:
        if m.stage in ("r32", "r16", "qf", "sf", "third_place", "final"):
            knockout_teams.add(m.home)
            knockout_teams.add(m.away)
            
    for name in knockout_teams:
        teams[name] = TeamState(qualified_r32=True)

    # עדכון הגעה לגמר וזכייה
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

    # 4. מיפוי כובשי השערים לשמות בעברית עבור מנוע הניקוד
    player_goals = {}
    for heb_name in PLAYER_HEB_TO_SEARCH:
        player_goals[heb_name] = 0
        for api_player_name, goals in api_extracted_scorers.items():
            if match_player(api_player_name, heb_name):
                player_goals[heb_name] += goals
                log.info(f"  Player match: {heb_name} = {api_player_name} ({goals} goals parsed)")

    t = Tournament(
        matches=matches,
        teams=teams,
        player_goals=player_goals,
        golden_boot=None,
    )

    log.info(f"Tournament built: {len(t.matches)} matches, {len(t.teams)} teams tracked via knockout, "
             f"{len(t.player_goals)} players tracked")
    return t
