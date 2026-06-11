# מונדיאל 2026 — מנוע ניקוד + Cron

מחשב אוטומטית את טבלת ההתערבות, מושך תוצאות מ-football-data.org (חינם!),
וכותב ל-Supabase כל 15 דק' דרך GitHub Actions.

## מבנה הקבצים

```
scoring.py         ← מנוע הניקוד (חוקי ההתערבות)
mappings.py        ← מיפוי שמות עברית ↔ אנגלית (נבחרות + שחקנים)
api_adapter.py     ← שכבה 1: שואב מ-football-data.org → בונה Tournament
main.py            ← אורקסטרטור: reads picks → scores → upserts leaderboard
test_api.py        ← סקריפט בדיקה (מוודא שה-API מחזיר נתונים)
requirements.txt   ← תלויות (requests בלבד)
.github/workflows/ ← GitHub Actions cron
```

## הגדרה

### 1. football-data.org
- הירשם חינם: https://www.football-data.org/client/register
- העתק את ה-API Token מה-dashboard

### 2. GitHub Repo
- צור repo פרטי חדש (למשל `mundial-cron`)
- העלה את כל הקבצים

### 3. GitHub Secrets
ב-Settings → Secrets and variables → Actions, הוסף:

| Secret | ערך |
|--------|-----|
| `FOOTBALL_DATA_KEY` | ה-API Token מ-football-data.org |
| `SUPABASE_URL` | כתובת הפרויקט (`https://xxx.supabase.co`) |
| `SUPABASE_SERVICE_KEY` | ה-service_role key (לא ה-anon!) |

### 4. בדיקה ידנית
בטרמינל (מקומי):
```bash
export FOOTBALL_DATA_KEY=xxx
python test_api.py
```

ב-GitHub: Actions → "Update Mundial Leaderboard" → Run workflow

## תקציב API

football-data.org free = 10 קריאות/דקה, ללא מגבלה יומית.
כל ריצה = 3 קריאות (matches + standings + scorers).
ה-cron רץ כל 15 דק' בשעות משחקים. מספיק בשפע.
