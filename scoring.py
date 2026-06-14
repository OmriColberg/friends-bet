"""
מונדיאל 2026 — מנוע ניקוד להתערבות.

עיקרון מרכזי: חישוב מאפס (stateless / idempotent) בכל ריצה.
בכל מחזור מושכים את כל המצב הנוכחי, ומחשבים מחדש את כל הניקוד של כולם.
אין צבירת דלתאות, אין state לזכור, התיקונים של ה-API מסתדרים מעצמם.

הפרדה מכוונת:
  - Tournament = המודל הפנימי. כאן ממולא מ-mock; בפרודקשן ימולא ע"י adapter ל-API-Football.
  - score_*    = הלוגיקה הטהורה של חוקי ההתערבות. לא יודעת כלום על API או על Supabase.

מקור גולים לכובשת/סופגת: לפי תוצאת המשחק (רגיל+הארכה), לא לפי אירועי גול בודדים.
זה עוקף את כל בעיית האונגול — התוצאה כבר משקפת אותו לזכות הקבוצה הנכונה, ופנדלי הכרעה
לא נכללים בתוצאה (הם נפרדים).
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone


# ──────────────────────────── מודל הבחירות ────────────────────────────

@dataclass
class Picks:
    name: str
    tier_a: str       # דרג א'
    tier_b: str       # דרג ב'
    tier_c: str       # דרג ג'
    tier_d: str       # דרג ד'
    scorer: str       # נבחרת כובשת
    conceder: str     # נבחרת סופגת
    top_scorer: str   # מלך השערים


# ──────────────────────────── מודל הטורניר ────────────────────────────

# שלבים. שובר-שוויון בפנדלים רלוונטי רק לנוקאאוט.
STAGES = {"group", "r32", "r16", "qf", "sf", "third_place", "final"}


@dataclass
class Match:
    home: str
    away: str
    home_goals: int                 # שערים ברגיל+הארכה (ללא הכרעת פנדלים)
    away_goals: int
    stage: str
    finished: bool = True
    decided_by: str = "regular"     # "regular" | "penalties"
    pen_winner: Optional[str] = None  # שם המנצחת אם decided_by == "penalties"


@dataclass
class TeamState:
    qualified_r32: bool = False
    qualified_as: Optional[str] = None   # "1st" | "2nd" | "3rd"
    reached_final: bool = False
    won_cup: bool = False


@dataclass
class Tournament:
    matches: list = field(default_factory=list)
    teams: dict = field(default_factory=dict)
    player_goals: dict = field(default_factory=dict)
    golden_boot: Optional[str] = None
    live_teams: set = field(default_factory=set)  # נבחרות שמשחקות עכשיו (לחישוב ניקוד חי)


# ──────────────────────────── חוקי הניקוד ────────────────────────────

WIN, DRAW, LOSS = 3, 1, 0


def _team_matches(team: str, t: Tournament):
    return [m for m in t.matches if team in (m.home, m.away)]


def _match_points(team: str, m: Match) -> int:
    """3 ניצחון / 1 תיקו / 0 הפסד. הכרעה בפנדלים: מנצחת 3, מפסידה 1."""
    if m.decided_by == "penalties":
        return WIN if m.pen_winner == team else DRAW
    gf = m.home_goals if team == m.home else m.away_goals
    ga = m.away_goals if team == m.home else m.home_goals
    if gf > ga:
        return WIN
    if gf == ga:
        return DRAW
    return LOSS


def _per_match_points(team: str, t: Tournament) -> int:
    return sum(_match_points(team, m) for m in _team_matches(team, t))


def _r32_bonus(team: str, tier: str, t: Tournament) -> int:
    """בונוס עלייה ל-1/16. דרג ד' בלבד מקבל על מקום שלישי."""
    st = t.teams.get(team)
    if not st or not st.qualified_r32:
        return 0
    if tier == "D":
        if st.qualified_as in ("1st", "2nd"):
            return 3
        if st.qualified_as == "3rd":
            return 1
    if tier == "C":
        if st.qualified_as in ("1st", "2nd"):
            return 1
    return 0


def _deep_bonus(team: str, t: Tournament) -> int:
    """גמר = 2, אליפות = +1. חל על כל ארבעת הדרגים."""
    st = t.teams.get(team)
    if not st:
        return 0
    return (2 if st.reached_final else 0) + (1 if st.won_cup else 0)


def _goals_for(team: str, t: Tournament) -> int:
    return sum((m.home_goals if team == m.home else m.away_goals)
               for m in _team_matches(team, t))


def _goals_against(team: str, t: Tournament) -> int:
    return sum((m.away_goals if team == m.home else m.home_goals)
               for m in _team_matches(team, t))


# ──────────────────────────── חישוב למשתתף ────────────────────────────

def score_participant(p: Picks, t: Tournament) -> dict:
    a = _per_match_points(p.tier_a, t) + _deep_bonus(p.tier_a, t)
    b = _per_match_points(p.tier_b, t) + _deep_bonus(p.tier_b, t)
    c = _per_match_points(p.tier_c, t) + _r32_bonus(p.tier_c, "C", t) + _deep_bonus(p.tier_c, t)
    d = _per_match_points(p.tier_d, t) + _r32_bonus(p.tier_d, "D", t) + _deep_bonus(p.tier_d, t)

    scorer = 0.5 * _goals_for(p.scorer, t)
    conceder = 0.5 * _goals_against(p.conceder, t)
    top = 0.5 * t.player_goals.get(p.top_scorer, 0) + (1 if t.golden_boot == p.top_scorer else 0)

    total = round(a + b + c + d + scorer + conceder + top, 1)
    return {
        "name": p.name,
        "tier_a": p.tier_a, "tier_a_pts": a,
        "tier_b": p.tier_b, "tier_b_pts": b,
        "tier_c": p.tier_c, "tier_c_pts": c,
        "tier_d": p.tier_d, "tier_d_pts": d,
        "scorer": p.scorer, "scorer_pts": scorer,
        "conceder": p.conceder, "conceder_pts": conceder,
        "topscorer": p.top_scorer, "topscorer_pts": top,
        "total": total,
    }


def build_leaderboard(picks: list, t: Tournament, prev_state: dict | None = None,
                      baseline_rank: dict | None = None) -> list:
    """מחזיר את הטבלה כפי שהפרונט יקרא מ-Supabase. ממוין לפי total יורד.

    prev_state: {name: {"rank", "movement"}} — המצב מהריצה הקודמת (לשמירת movement קפוא).
    baseline_rank: {name: rank} — snapshot "יציב" של הדירוג מהמצב האחרון שבו לא היו משחקים חיים.

    מדיניות movement:
    - בזמן משחק חי (has_live) → ה-movement קפוא: משאירים את הערך מהריצה הקודמת.
    - כשאין משחקים חיים → מחשבים movement מול ה-baseline (הדירוג מלפני שהמשחקים התחילו).
    """
    rows = [score_participant(p, t) for p in picks]
    prev_state = prev_state or {}
    baseline_rank = baseline_rank or {}
    prev_rank = {name: s["rank"] for name, s in prev_state.items()}
    has_live = bool(t.live_teams)

    # מיון: ניקוד יורד, ובתיקו — לפי הדירוג הקודם (לשמירת יציבות)
    max_rank = len(rows) + 1
    rows.sort(key=lambda r: (-r["total"], prev_rank.get(r["name"], max_rank)))

    now = datetime.now(timezone.utc).isoformat()

    # חישוב דירוג — standard competition ranking (1-2-3-3-3-6)
    for i, r in enumerate(rows):
        if i == 0:
            r["rank"] = 1
        elif r["total"] == rows[i - 1]["total"]:
            r["rank"] = rows[i - 1]["rank"]
        else:
            r["rank"] = i + 1
        r["updated_at"] = now

    for r in rows:
        if has_live:
            # משחק חי → movement קפוא על מה שהיה לפני (מהריצה הקודמת)
            r["movement"] = prev_state.get(r["name"], {}).get("movement", 0)
        else:
            # אין משחקים חיים → movement מול ה-baseline היציב
            old_rank = baseline_rank.get(r["name"])
            r["movement"] = 0 if old_rank is None else old_rank - r["rank"]

    return rows


# ──────────────────────────── נתוני מוק (מהתמונה, ניקוד מאופס) ────────────────────────────

MOCK_PICKS = [
    Picks("אליק", "ספרד",     "שווייץ",   "דרום קוריאה", "קטאר",       "צרפת",     "קוראסאו", "אמבפה"),
    Picks("שי",   "אנגליה",   "קולומביה", "מצרים",        "תוניסיה",    "ספרד",     "קוראסאו", "קיין"),
    Picks("עמרי", "צרפת",     "אורוגוואי","סנגל",         "דרום אפריקה","ברזיל",    "פנמה",    "אמבפה"),
    Picks("דני",  "פורטוגל",  "מרוקו",    "איראן",        "אוזבקיסטן",  "צרפת",     "קוראסאו", "רונאלדו"),
    Picks("יובל", "ברזיל",    "יפן",      "גאנה",         "קטאר",       "ספרד",     "האיטי",   "ויניסיוס"),
    Picks("רועי", "ארגנטינה", "מקסיקו",   "דרום קוריאה",  "פנמה",       "ארגנטינה", "קוראסאו", "מסי"),
    Picks("ניר",  "גרמניה",   "אקוודור",  "מצרים",        "קונגו",      "אנגליה",   "כף ורדה", "קיין"),
    Picks("גיא",  "הולנד",    "קרואטיה",  "סקוטלנד",      "האיטי",      "פורטוגל",  "קוראסאו", "אמבפה"),
]


def empty_tournament() -> Tournament:
    """מצב פתיחה — לפני שריקה ראשונה. כולם 0."""
    return Tournament()


def sample_midtournament() -> Tournament:
    """תרחיש בדיקה מומצא (לא אמיתי!) רק כדי להוכיח שהמנוע מחשב נכון."""
    t = Tournament()
    t.matches = [
        # בית — ספרד 2 ניצחונות, צרפת ניצחון+תיקו
        Match("ספרד", "דרום קוריאה", 3, 1, "group"),
        Match("ספרד", "שווייץ",      2, 0, "group"),
        Match("צרפת", "פנמה",        4, 0, "group"),
        Match("צרפת", "אורוגוואי",   1, 1, "group"),
        Match("ארגנטינה", "מקסיקו",  1, 0, "group"),
        Match("קוראסאו", "ספרד",     0, 5, "group"),   # קוראסאו ספגה 5 → לסופגת
        # נוקאאוט עם הכרעת פנדלים
        Match("צרפת", "ברזיל", 1, 1, "r32", decided_by="penalties", pen_winner="צרפת"),
    ]
    t.teams = {
        "ספרד":     TeamState(qualified_r32=True, qualified_as="1st"),
        "צרפת":     TeamState(qualified_r32=True, qualified_as="1st"),
        "דרום אפריקה": TeamState(qualified_r32=True, qualified_as="3rd"),  # דרג ד' של עמרי → בונוס 1
        "קטאר":     TeamState(qualified_r32=True, qualified_as="2nd"),     # דרג ד' של אליק → בונוס 3
        "סנגל":     TeamState(qualified_r32=True, qualified_as="2nd"),     # דרג ג' של עמרי → בונוס 1
    }
    t.player_goals = {"אמבפה": 4, "קיין": 2, "ויניסיוס": 3, "מסי": 1}
    t.golden_boot = None
    return t


def _fmt(x: float) -> str:
    return str(int(x)) if x == int(x) else str(x)


def print_table(rows: list, title: str):
    print(f"\n{'='*72}\n{title}\n{'='*72}")
    print(f"{'#':>2}  {'שם':<6} {' א':>5} {'ב':>5} {'ג':>5} {'ד':>5} {'כובש':>5} {'סופג':>5} {'מלך':>5} {'סהכ':>6}")
    for r in rows:
        print(f"{r['rank']:>2}  {r['name']:<6} "
              f"{_fmt(r['tier_a_pts']):>5} {_fmt(r['tier_b_pts']):>5} "
              f"{_fmt(r['tier_c_pts']):>5} {_fmt(r['tier_d_pts']):>5} "
              f"{_fmt(r['scorer_pts']):>5} {_fmt(r['conceder_pts']):>5} "
              f"{_fmt(r['topscorer_pts']):>5} {_fmt(r['total']):>6}")


if __name__ == "__main__":
    print_table(build_leaderboard(MOCK_PICKS, empty_tournament()),
                "מצב פתיחה (לפני שריקה ראשונה) — הכל מאופס")
    print_table(build_leaderboard(MOCK_PICKS, sample_midtournament()),
                "תרחיש בדיקה מומצא — להוכחת תקינות הלוגיקה בלבד")
