"""
שכבה 1 — Adapter ל-worldcup26.ir (משולב: משחקים + כובשי שערים).
API חינמי, פתוח לחלוטין וללא צורך במפתח (API Key).

אנדפוינטים בשימוש:
  GET https://worldcup26.ir/get/games      -> כל המשחקים, התוצאות והסטטוסים
  GET https://worldcup26.ir/get/game/{id}  -> מידע מורחב על משחק ספציפי כולל מערך כובשי שערים
"""

import logging
import requests
from scoring import Tournament, Match, TeamState
from mappings import normalize_team, TEAM_ENG_TO_HEB, match_player, PLAYER_HEB_TO_SEARCH

log = logging.getLogger(__name__)

BASE_URL = "https://worldcup26.ir/get"

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


def fetch_matches() -> list[dict]:
    """מושך את רשימת כל המשחקים הכללית"""
    url = f"{BASE_URL}/games"
    log.info(f"Calling public World Cup API: {url}")
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        return data.get("games", []) or []
    except Exception as e:
        log.error(f"Failed to fetch games from worldcup26.ir: {e}")
        return []


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
        game.get("finished") == "true" or 
        game.get("finished") is True or 
        game.get("time_elapsed") == "finished"
    )
    if not is_finished:
        return None

    home_raw = game.get("home_team_en", "")
    away_raw = game.get("away_team_en", "")
    home = _to_heb(home_raw)
    away = _to_heb(away_raw)

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
    raw_games = fetch_matches()

    matches = []
    api_extracted_scorers = {}  # מפה זמנית: שם שחקן באנגלית -> כמות שערים מצטברת
    teams = {}

    for game in raw_games:
        parsed = _parse_match(game)
        if parsed:
            matches.append(parsed)
            
            # בדיקה אם מדובר במשחק שהסתיים ונכבשו בו שערים לפני שפונים ל-API המורחב
            game_id = game.get("id")
            home_score = int(game.get("home_score", 0) or 0)
            away_score = int(game.get("away_score", 0) or 0)
            
            if game_id and (home_score > 0 or away_score > 0):
                detailed_game = fetch_game_details(str(game_id))
                
                # שליפת מערך המבקיעים מתוך פרטי המשחק (תומך בשדות goals או events של ה-API)
                goals_events = detailed_game.get("goals", []) or detailed_game.get("events", [])
                if isinstance(goals_events, list):
                    for goal in goals_events:
                        player_name = ""
                        if isinstance(goal, dict):
                            player_name = goal.get("player_name") or goal.get("player") or ""
                        elif isinstance(goal, str):
                            player_name = goal
                        
                        if player_name:
                            api_extracted_scorers[player_name] = api_extracted_scorers.get(player_name, 0) + 1

    log.info(f"Processed {len(matches)} finished matches out of {len(raw_games)} total games")

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
        matches=matches,
        teams=teams,
        player_goals=player_goals,
        golden_boot=None,
    )

    log.info("Tournament mapping completed successfully from worldcup26.ir.")
    return t
