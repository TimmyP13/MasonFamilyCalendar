"""
Scrape Mason High School athletics schedules from gomasoncomets.com.

The athletics site publishes schedules only as per-sport PDFs linked from
/schedules/. There is no ICS, RSS or JSON feed, so this walks the links,
downloads each PDF, and parses the tabular rows.

Output: data/sports-scraped.json

Design notes:
  * Tolerant by default. A PDF that will not parse is reported, not fatal.
  * Season-window filtered, so last year's PDFs (which the site leaves up
    until the new ones are posted) never leak into the current feed.
  * Everything it could not parse lands in the "problems" list so the build
    log tells you exactly what needs a manual override.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup

try:
    import pdfplumber
except ImportError:  # pragma: no cover
    pdfplumber = None

ROOT = Path(__file__).resolve().parent.parent
SCHEDULES_URL = "https://www.gomasoncomets.com/schedules/"
HEADERS = {
    "User-Agent": (
        "MasonFamilyCalendar/1.0 (unofficial community calendar; "
        "+https://github.com/)"
    )
}
TIMEOUT = 45

# ---------------------------------------------------------------------------
# Sport / level classification
# ---------------------------------------------------------------------------

SPORT_PATTERNS = [
    ("football", r"\bfootball\b"),
    ("cross-country", r"cross\s*country"),
    ("golf", r"\bgolf\b"),
    ("soccer", r"\bsoccer\b"),
    ("tennis", r"\btennis\b"),
    ("volleyball", r"\bvolleyball\b"),
    # "WPschedule2025info.pdf" has no word boundary after wp, hence the lookahead
    ("water-polo", r"water\s*polo|\bwp(?=[\s_\-]|schedule)"),
    ("basketball", r"\bbasketball\b"),
    ("bowling", r"\bbowling\b"),
    ("swim-dive", r"swim|s\s*&\s*d|dive|diving"),
    ("wrestling", r"\bwrestling\b"),
    ("ice-hockey", r"ice\s*hockey|\bhockey\b"),
    ("baseball", r"\bbaseball\b"),
    ("lacrosse", r"\blacrosse\b"),
    ("track-field", r"track"),
    ("softball", r"\bsoftball\b"),
    ("cheer", r"\bcheer\b"),
]

SPORT_LABELS = {
    "football": "Football",
    "cross-country": "Cross Country",
    "golf": "Golf",
    "soccer": "Soccer",
    "tennis": "Tennis",
    "volleyball": "Volleyball",
    "water-polo": "Water Polo",
    "basketball": "Basketball",
    "bowling": "Bowling",
    "swim-dive": "Swimming & Diving",
    "wrestling": "Wrestling",
    "ice-hockey": "Ice Hockey",
    "baseball": "Baseball",
    "lacrosse": "Lacrosse",
    "track-field": "Track & Field",
    "softball": "Softball",
    "cheer": "Cheer",
}

SEASONS = {
    "fall": {"football", "cross-country", "golf", "soccer", "volleyball",
             "water-polo", "cheer"},
    "winter": {"basketball", "bowling", "swim-dive", "wrestling", "ice-hockey"},
    "spring": {"baseball", "softball", "lacrosse", "track-field"},
}


def classify_sport(text: str) -> str | None:
    low = text.lower()
    # tennis before volleyball etc. is not an issue, but check the longest first
    for code, pattern in SPORT_PATTERNS:
        if re.search(pattern, low):
            return code
    return None


def classify_level(text: str) -> str:
    low = text.lower()
    if "freshman" in low or "frosh" in low:
        return "Freshman"
    if re.search(r"\bjv\b|junior varsity", low):
        return "JV"
    if "varsity" in low:
        return "Varsity"
    if "all levels" in low:
        return "All Levels"
    return "Unspecified"


def classify_gender(text: str) -> str:
    low = text.lower()
    has_boys = bool(re.search(r"\bboys?\b|\bmen'?s\b", low))
    has_girls = bool(re.search(r"\bgirls?\b|\bwomen'?s\b", low))
    if has_boys and has_girls:
        return "Boys & Girls"
    if has_boys:
        return "Boys"
    if has_girls:
        return "Girls"
    return ""


def sport_season(code: str) -> str:
    for season, codes in SEASONS.items():
        if code in codes:
            return season
    return "other"


# ---------------------------------------------------------------------------
# Row parsing
# ---------------------------------------------------------------------------

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

RE_NUMERIC_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
RE_WORD_DATE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?\b",
    re.IGNORECASE,
)
RE_TIME = re.compile(r"\b(\d{1,2}):(\d{2})\s*([AaPp])\.?[Mm]\.?\b")
RE_HOME_AWAY = re.compile(r"\b(home|away|neutral|h|a)\b", re.IGNORECASE)
RE_DAYNAME = re.compile(
    r"\b(mon|tue|tues|wed|weds|thu|thur|thurs|fri|sat|sun)[a-z]*\.?\b",
    re.IGNORECASE,
)
NOISE_LINE = re.compile(
    r"^\s*(date|day|opponent|location|time|site|event|schedule|"
    r"mason high school|page \d+|generated|printed)\b",
    re.IGNORECASE,
)


def parse_date(text: str, default_year: int, season_start: date) -> date | None:
    m = RE_NUMERIC_DATE.search(text)
    if m:
        mo, dy, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if yr < 100:
            yr += 2000
        try:
            return date(yr, mo, dy)
        except ValueError:
            return None

    m = RE_WORD_DATE.search(text)
    if m:
        mo = MONTHS[m.group(1).lower()]
        dy = int(m.group(2))
        if m.group(3):
            yr = int(m.group(3))
        else:
            # No year printed. Infer from the season window: months at or after
            # the season's start month belong to the start year, else the next.
            yr = season_start.year if mo >= season_start.month else season_start.year + 1
        try:
            return date(yr, mo, dy)
        except ValueError:
            return None
    return None


def parse_time(text: str) -> tuple[int, int] | None:
    m = RE_TIME.search(text)
    if not m:
        return None
    hour, minute, ampm = int(m.group(1)), int(m.group(2)), m.group(3).lower()
    if ampm == "p" and hour != 12:
        hour += 12
    if ampm == "a" and hour == 12:
        hour = 0
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


def parse_row(line: str, default_year: int, season_start: date) -> dict | None:
    """Pull one game out of a text line. Returns None if the line is not a game row."""
    line = " ".join(line.split())
    if not line or NOISE_LINE.match(line):
        return None

    # Season-range headers ("Varsity Schedule 8/1/2025 to 11/30/2025") carry two
    # dates and no opponent. Two dates on one line is never a real game row.
    if len(RE_NUMERIC_DATE.findall(line)) > 1:
        return None

    game_date = parse_date(line, default_year, season_start)
    if not game_date:
        return None

    time_match = RE_TIME.search(line)
    tm = parse_time(line)

    ha_match = None
    for m in RE_HOME_AWAY.finditer(line):
        ha_match = m
    home_away = ""
    if ha_match:
        token = ha_match.group(1).lower()
        home_away = {"h": "Home", "a": "Away"}.get(token, token.capitalize())

    # Opponent = whatever survives after removing date, day name, H/A and time.
    remainder = line
    for pattern in (RE_NUMERIC_DATE, RE_WORD_DATE, RE_DAYNAME):
        remainder = pattern.sub(" ", remainder)
    if time_match:
        remainder = remainder.replace(time_match.group(0), " ")
    if ha_match:
        remainder = remainder[: ha_match.start()] + " " + remainder[ha_match.end():] \
            if ha_match.start() < len(remainder) else remainder
    remainder = re.sub(r"\b(home|away|neutral)\b", " ", remainder, flags=re.IGNORECASE)
    remainder = re.sub(r"[,;|]+", " ", remainder)
    remainder = re.sub(r"\s{2,}", " ", remainder).strip(" -–—•")

    if not remainder or len(remainder) < 2:
        return None

    return {
        "date": game_date.isoformat(),
        "time": f"{tm[0]:02d}:{tm[1]:02d}" if tm else None,
        "opponent": remainder,
        "homeAway": home_away,
    }


# ---------------------------------------------------------------------------
# PDF handling
# ---------------------------------------------------------------------------

def pdf_lines(content: bytes) -> list[str]:
    if pdfplumber is None:
        raise RuntimeError("pdfplumber is not installed")
    lines: list[str] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            # Tables first: these PDFs are exports from a scheduling system and
            # usually carry a real table structure.
            for table in page.extract_tables() or []:
                for row in table:
                    cells = [c.replace("\n", " ").strip() for c in row if c]
                    if cells:
                        lines.append("  ".join(cells))
            text = page.extract_text() or ""
            lines.extend(text.split("\n"))
    # de-duplicate while preserving order (table + text extraction overlap)
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = " ".join(line.split())
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def discover_pdfs(session: requests.Session) -> list[dict]:
    resp = session.get(SCHEDULES_URL, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    found: dict[str, dict] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if ".pdf" not in href.lower():
            continue
        url = urljoin(SCHEDULES_URL, href)
        label = " ".join(a.get_text(" ").split())
        filename = unquote(url.rsplit("/", 1)[-1])

        # The link text is sometimes split across elements ("Water" / "Polo"),
        # so fall back to the filename for classification.
        basis = f"{label} {filename}"
        sport = classify_sport(basis)
        if not sport:
            continue
        if "roster" in filename.lower() and "schedule" not in filename.lower():
            continue

        found.setdefault(url, {
            "url": url,
            "label": label or filename,
            "filename": filename,
            "sport": sport,
            "level": classify_level(basis),
            "gender": classify_gender(basis),
        })
    return list(found.values())


def scrape(season_start: date, season_end: date, levels: set[str]) -> dict:
    session = requests.Session()
    problems: list[str] = []
    games: list[dict] = []

    try:
        pdfs = discover_pdfs(session)
    except Exception as exc:
        return {
            "generated": datetime.utcnow().isoformat() + "Z",
            "seasonStart": season_start.isoformat(),
            "seasonEnd": season_end.isoformat(),
            "games": [],
            "sources": [],
            "problems": [f"Could not load {SCHEDULES_URL}: {exc}"],
        }

    sources: list[dict] = []
    for pdf in pdfs:
        keep_level = pdf["level"] in levels or pdf["level"] in ("All Levels", "Unspecified")
        if not keep_level:
            continue
        try:
            resp = session.get(pdf["url"], headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            lines = pdf_lines(resp.content)
        except Exception as exc:
            problems.append(f"{pdf['filename']}: fetch/parse failed ({exc})")
            continue

        parsed = 0
        in_window = 0
        for line in lines:
            row = parse_row(line, season_start.year, season_start)
            if not row:
                continue
            parsed += 1
            gd = date.fromisoformat(row["date"])
            if not (season_start <= gd <= season_end):
                continue
            in_window += 1
            games.append({
                **row,
                "sport": pdf["sport"],
                "sportLabel": SPORT_LABELS.get(pdf["sport"], pdf["sport"]),
                "level": pdf["level"],
                "gender": pdf["gender"],
                "season": sport_season(pdf["sport"]),
                "source": pdf["url"],
            })

        sources.append({
            "file": pdf["filename"],
            "url": pdf["url"],
            "sport": pdf["sport"],
            "level": pdf["level"],
            "gender": pdf["gender"],
            "rowsParsed": parsed,
            "rowsInSeason": in_window,
        })
        if parsed == 0:
            problems.append(f"{pdf['filename']}: no game rows recognised")
        elif in_window == 0:
            problems.append(
                f"{pdf['filename']}: {parsed} rows parsed but none fall inside "
                f"{season_start}..{season_end} (probably a previous season still posted)"
            )

    # de-duplicate identical games arriving from overlapping PDFs
    unique: dict[tuple, dict] = {}
    for g in games:
        key = (g["sport"], g["level"], g["gender"], g["date"], g["time"], g["opponent"])
        unique.setdefault(key, g)

    return {
        "generated": datetime.utcnow().isoformat() + "Z",
        "seasonStart": season_start.isoformat(),
        "seasonEnd": season_end.isoformat(),
        "games": sorted(unique.values(), key=lambda g: (g["date"], g["time"] or "", g["sport"])),
        "sources": sources,
        "problems": problems,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season-start", default="2026-08-01")
    ap.add_argument("--season-end", default="2027-07-31")
    ap.add_argument("--levels", default="Varsity",
                    help="comma separated: Varsity,JV,Freshman")
    ap.add_argument("--out", default=str(ROOT / "data" / "sports-scraped.json"))
    args = ap.parse_args()

    result = scrape(
        date.fromisoformat(args.season_start),
        date.fromisoformat(args.season_end),
        {lvl.strip() for lvl in args.levels.split(",") if lvl.strip()},
    )

    Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"PDFs examined : {len(result['sources'])}")
    print(f"Games in window: {len(result['games'])}")
    for p in result["problems"]:
        print(f"  ! {p}")
    if not result["games"]:
        print(
            "\nNo games landed inside the season window. This is expected until "
            "Mason athletics posts the new season's PDFs; the feed will publish "
            "empty and fill itself on the next scheduled run."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
