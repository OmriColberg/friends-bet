"""
מיפוי שמות: עברית ←→ API-Football.
כל שם עברי שמופיע ב-picks חייב להיות כאן.
ה-API מחזיר שמות באנגלית — המפה ההפוכה נבנית אוטומטית.
"""

# שמות הנבחרות: עברית → אנגלית (כפי שמגיע מ-API-Football)
TEAM_HEB_TO_ENG = {
    # דרג א'
    "אנגליה":     "England",
    "ארגנטינה":   "Argentina",
    "ברזיל":      "Brazil",
    "גרמניה":     "Germany",
    "ספרד":        "Spain",
    "פורטוגל":    "Portugal",
    "צרפת":        "France",
    # דרג ב'
    "אוסטריה":    "Austria",
    "אורוגוואי":  "Uruguay",
    'ארה"ב':      "USA",
    "טורקיה":     "Turkey",
    "יפן":         "Japan",
    "מקסיקו":     "Mexico",
    "מרוקו":       "Morocco",
    "נורווגיה":   "Norway",
    "צ'כיה":      "Czech Republic",
    "קולומביה":   "Colombia",
    "קרואטיה":    "Croatia",
    "שווייץ":     "Switzerland",
    # דרג ג'
    "אוסטרליה":   "Australia",
    "איראן":       "Iran",
    "דרום קוריאה": "South Korea",
    "חוף השנהב":  "Ivory Coast",
    "מצרים":       "Egypt",
    "סנגל":        "Senegal",
    "סקוטלנד":    "Scotland",
    "שוודיה":     "Sweden",
    # דרג ד'
    "אוזבקיסטן":  "Uzbekistan",
    "דרום אפריקה": "South Africa",
    "ירדן":        "Jordan",
    "כף ורדה":    "Cape Verde",
    "ניו זילנד":  "New Zealand",
    "פנמה":        "Panama",
    "קונגו":       "DR Congo",
    "קטאר":        "Qatar",
    "תוניסיה":    "Tunisia",
    # נבחרות שמופיעות רק בכובשת/סופגת
    "בלגיה":       "Belgium",
    "האיטי":       "Haiti",
    "הולנד":       "Netherlands",
    "עיראק":       "Iraq",
    "קורסאו":     "Curacao",
    "קנדה":        "Canada",
    # נבחרות שלא נבחרו ע"י אף משתתף אבל משחקות בטורניר
    "אלג'יריה":   "Algeria",
    "בוסניה":      "Bosnia-Herzegovina",
    "אקוודור":     "Ecuador",
    "גאנה":        "Ghana",
    "פרגוואי":     "Paraguay",
    "ערב הסעודית": "Saudi Arabia",
}

# מפה הפוכה: אנגלית → עברית
TEAM_ENG_TO_HEB = {v: k for k, v in TEAM_HEB_TO_ENG.items()}

# וריאציות שמות ב-API (למקרה שה-API מחזיר שם שונה)
TEAM_ALIASES = {
    "Korea Republic":       "South Korea",
    "Korea, Republic of":   "South Korea",
    "Côte d'Ivoire":        "Ivory Coast",
    "Cote D'Ivoire":        "Ivory Coast",
    "Türkiye":              "Turkey",
    "Turkiye":              "Turkey",
    "Czechia":              "Czech Republic",
    "Congo DR":             "DR Congo",
    "Congo":                "DR Congo",
    "Dem. Rep. Congo":      "DR Congo",
    "Curaçao":              "Curacao",
    "United States":        "USA",
    "United States of America": "USA",
    "Cape Verde Islands":   "Cape Verde",
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
}


def normalize_team(api_name: str) -> str:
    """מנרמל שם נבחרת שמגיע מ-API-Football לשם הסטנדרטי שלנו (אנגלית)."""
    if api_name in TEAM_ENG_TO_HEB:
        return api_name
    return TEAM_ALIASES.get(api_name, api_name)


def team_eng_to_heb(eng_name: str) -> str:
    """ממפה שם אנגלית → עברית. זורק KeyError אם לא נמצא."""
    norm = normalize_team(eng_name)
    if norm in TEAM_ENG_TO_HEB:
        return TEAM_ENG_TO_HEB[norm]
    raise KeyError(f"Unknown team: {eng_name!r} (normalized: {norm!r})")


def team_heb_to_eng(heb_name: str) -> str:
    """ממפה שם עברית → אנגלית. זורק KeyError אם לא נמצא."""
    if heb_name in TEAM_HEB_TO_ENG:
        return TEAM_HEB_TO_ENG[heb_name]
    raise KeyError(f"Unknown Hebrew team: {heb_name!r}")


# שמות שחקנים: עברית → רשימת שמות אפשריים ב-API (שם משפחה / שם מלא)
# ה-API מחזיר שמות בפורמטים שונים, אז נשמור כמה וריאציות ונעשה fuzzy match.
PLAYER_HEB_TO_SEARCH = {
    "קיליאן אמבפה":     ["Mbappé", "Mbappe", "K. Mbappé", "K. Mbappe", "Kilian Ambaph", "Ambaph"],
    "הארי קיין":        ["Kane", "H. Kane", "Harry Kane"],
    "לאמין ימאל":       ["Yamal", "L. Yamal", "Lamine Yamal"],
    "ארלינג האלנד":     ["Haaland", "E. Haaland", "Erling Haaland", "Håland", "Arling Halnd", "Halnd"],
    "ליונל מסי":        ["Messi", "L. Messi", "Lionel Messi"],
    "מיקל אויארסבאל":  ["Oyarzabal", "M. Oyarzabal", "Mikel Oyarzabal"],
    "לאוטרו מרטינס":   ["Martínez", "Martinez", "L. Martínez", "Lautaro Martínez", "Lautaro Martinez"],
    "ויניסיוס ז'וניור": ["Vinícius", "Vinicius", "Vinícius Jr", "Vinicius Jr", "Vinícius Júnior", "Vinicius Junior", "V. Júnior", "V. Junior", "V. Vinícius", "V. Vinicius"],
    "לירוי סאנה":       ["Sané", "Sane", "L. Sané", "L. Sane", "Leroy Sané", "Leroy Sane"],
    "כריסטיאנו רונאלדו": ["Ronaldo", "C. Ronaldo", "Cristiano Ronaldo"],
    "עוסמאן דמבלה":     ["Dembélé", "Dembele", "O. Dembélé", "O. Dembele", "Ousmane Dembélé"],
}


def match_player(api_name: str, heb_name: str) -> bool:
    """בודק האם שם שחקן מה-API תואם לבחירת המשתתף."""
    search_names = PLAYER_HEB_TO_SEARCH.get(heb_name, [])
    api_lower = api_name.lower()
    for s in search_names:
        if s.lower() in api_lower or api_lower in s.lower():
            return True
    return False


def find_player_goals(heb_name: str, api_scorers: list[dict]) -> int:
    """מחפש את מספר הגולים של שחקן מתוך רשימת המבקיעים של ה-API."""
    for entry in api_scorers:
        api_name = entry.get("name", "")
        if match_player(api_name, heb_name):
            return entry.get("goals", 0)
    return 0
