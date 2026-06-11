"""
שכבה 1 — Adapter ל-football-data.org (v4).
חינמי, כולל מונדיאל 2026, מגבלה 10 קריאות/דקה (לא ליום!).

אנדפוינטים:
  GET /v4/competitions/WC/matches   → תוצאות כל המשחקים
  GET /v4/competitions/WC/standings → מיקום בבית
  GET /v4/competitions/WC/scorers   → מלכי שערים
"""

import os
import json
import logging
import requests
from scoring import Tournament, Match, TeamState
from mappings import normalize_team, TEAM_ENG_TO_HEB, match_player, PLAYER_HEB_TO_SEARCH

log = logging.getLogger(__name__)

API_KEY = os.environ.get("FOOTBALL_DATA_KEY", "")
BASE_URL = "https://api.football-data.org/v4"

HEADERS = {
    "X-Auth-Token": API_KEY,
}

# סטטוסים שמסמנים משחק שהסתיים
FINISHED_STATUSES = {"FINISHED"}

# מיפוי שלב
STAGE_MAP = {
    "GROUP_STAGE":     "group",
    "LAST_32":         "r32",
    "ROUND_OF_32":     "r32",
    "LAST_16":         "r16",
    "ROUND_OF_16":     "r16",
    "QUARTER_FINALS":  "qf",
    "SEMI_FINALS":     "sf",
    "THIRD_PLACE":     "third_place",
    "FINAL":           "final",
}


def _api_get(endpoint: str, params: dict = None) -> dict:
    url = f"{BASE_URL}/{endpoint}"
    log.info(f"API call: {url}")
    resp = requests.get(url, headers=HEADERS, params=params or {}, timeout=30)
    resp.raise_for_status()
    remaining = resp.headers.get("X-Requests-Available", "?")
    log.info(f"API OK — requests available this minute: {remaining}")
    return resp.json()


def fetch_matches() -> list[dict]:
    data = _api_get("competitions/WC/matches")
    return data.get("matches", [])


def fetch_standings() -> list[dict]:
    data = _api_get("competitions/WC/standings")
    return data.get("standings", [])


def fetch_scorers() -> list[dict]:
    data = _api_get("competitions/WC/scorers", {"limit": 100})
    return data.get("scorers", [])


def _to_heb(api_name: str) -> str:
    if not api_name or api_name == "None":
        return "TBD"
    eng = normalize_team(api_name)
    return TEAM_ENG_TO_HEB.get(eng, eng)


def _parse_match(match: dict) -> Match | None:
    status = match.get("status", "")
    if status not in FINISHED_STATUSES:
        return None

    home_raw = match.get("homeTeam", {}).get("name", "")
    away_raw = match.get("awayTeam", {}).get("name", "")
    home = _to_heb(home_raw)
    away = _to_heb(away_raw)

    score = match.get("score", {})
    duration = score.get("duration", "REGULAR")

    # תוצאה ברגיל
    ft = score.get("fullTime", {})
    home_goals = ft.get("home", 0) or 0
    away_goals = ft.get("away", 0) or 0

    # הכרעה בפנדלים
    decided_by = "regular"
    pen_winner = None
    pen = score.get("penalties", {})
    pen_home = pen.get("home")
    pen_away = pen.get("away")
    if pen_home is not None and pen_away is not None:
        decided_by = "penalties"
        pen_winner = home if pen_home > pen_away else away

    stage_raw = match.get("stage", "GROUP_STAGE")
    stage = STAGE_MAP.get(stage_raw, "group")

    return Match(
        home=home, away=away,
        home_goals=home_goals, away_goals=away_goals,
        stage=stage, finished=True,
        decided_by=decided_by, pen_winner=pen_winner,
    )


def _parse_standings(raw_standings: list[dict]) -> dict[str, TeamState]:
    teams: dict[str, TeamState] = {}
    for group in raw_standings:
        if group.get("type") != "TOTAL":
            continue
        for entry in group.get("table", []):
            raw_name = entry.get("team", {}).get("name", "")
            name = _to_heb(raw_name)
            rank = entry.get("position", 99)
            pos = None
            if rank == 1:
                pos = "1st"
            elif rank == 2:
                pos = "2nd"
            elif rank == 3:
                pos = "3rd"
            # football-data.org doesn't have a "qualified" flag per se,
            # but we can infer from the competition progression.
            # For now, mark qualified if they have a position — we'll refine
            # based on knockout matches existing.
            teams[name] = TeamState(
                qualified_r32=False,  # will be set below
                qualified_as=pos,
            )
    return teams


def _detect_qualification(matches: list[Match], teams: dict[str, TeamState]):
    """אם יש משחקי נוקאאוט, הקבוצות שמופיעות בהם עלו."""
    knockout_teams = set()
    for m in matches:
        if m.stage in ("r32", "r16", "qf", "sf", "third_place", "final"):
            knockout_teams.add(m.home)
            knockout_teams.add(m.away)
    for name in knockout_teams:
        if name in teams:
            teams[name].qualified_r32 = True
        else:
            teams[name] = TeamState(qualified_r32=True)


def _detect_deep_runs(matches: list[Match], teams: dict[str, TeamState]):
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


def _parse_scorers(raw: list[dict]) -> list[dict]:
    scorers = []
    for entry in raw:
        player = entry.get("player", {})
        goals = entry.get("goals", 0) or 0
        scorers.append({
            "name": player.get("name", ""),
            "goals": goals,
        })
    return scorers


def build_tournament_from_api() -> Tournament:
    log.info("Fetching matches...")
    raw_matches = fetch_matches()

    log.info("Fetching standings...")
    raw_standings = fetch_standings()

    log.info("Fetching scorers...")
    raw_scorers = fetch_scorers()

    # פירוק משחקים
    matches = []
    for m in raw_matches:
        parsed = _parse_match(m)
        if parsed:
            matches.append(parsed)
    log.info(f"Parsed {len(matches)} finished matches out of {len(raw_matches)} total")

    # פירוק טבלאות בתים
    teams = _parse_standings(raw_standings)

    # זיהוי עלייה מנוקאאוט
    _detect_qualification(matches, teams)

    # זיהוי הגעה לגמר/זכייה
    _detect_deep_runs(matches, teams)

    # פירוק מבקיעים
    scorers_list = _parse_scorers(raw_scorers)

    # בניית player_goals: מיפוי שם עברי → גולים
    player_goals = {}
    for heb_name in PLAYER_HEB_TO_SEARCH:
        for api_entry in scorers_list:
            if match_player(api_entry["name"], heb_name):
                player_goals[heb_name] = api_entry["goals"]
                log.info(f"  Player match: {heb_name} = {api_entry['name']} ({api_entry['goals']} goals)")
                break

    t = Tournament(
        matches=matches,
        teams=teams,
        player_goals=player_goals,
        golden_boot=None,
    )

    log.info(f"Tournament built: {len(t.matches)} matches, {len(t.teams)} teams, "
             f"{len(t.player_goals)} players tracked")
    return t
