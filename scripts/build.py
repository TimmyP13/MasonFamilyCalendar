"""
Build every .ics feed plus the static site into dist/.

Run:  python scripts/build.py --base-url https://you.github.io/mason-family-calendar
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from ics import Calendar, make_uid

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = ROOT / "site"
DIST = ROOT / "dist"
FEED_DIR = DIST / "feeds"

UID_NS = "masonfamilycalendar"
DISCLAIMER = (
    "Unofficial community calendar. Not affiliated with, endorsed by, or operated "
    "by Mason City Schools. Always confirm against the district's official calendar."
)

CATEGORY_LABELS = {
    "no-school": "No School",
    "first-last": "First / Last Day",
    "journey": "Journey Day",
    "holiday": "Holiday",
    "event": "School Event",
    "sports": "Athletics",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def academic_events_for(audience: str, academic: dict) -> list[dict]:
    """Resolve the event list for one building code, applying byAudience overrides."""
    out: list[dict] = []
    for ev in academic["events"]:
        auds = ev.get("audiences", ["all"])
        if "all" not in auds and audience not in auds:
            continue
        resolved = dict(ev)
        override = (ev.get("byAudience") or {}).get(audience)
        if override:
            resolved.update(override)
        resolved.pop("byAudience", None)
        out.append(resolved)
    return out


def add_academic(cal: Calendar, events: list[dict], audience: str) -> None:
    for ev in events:
        cal.add_all_day(
            uid=make_uid(UID_NS, "academic", audience, ev["id"]),
            summary=ev["summary"],
            start=date.fromisoformat(ev["start"]),
            end_inclusive=date.fromisoformat(ev["end"]),
            description=(ev.get("description", "") + "\n\n" + DISCLAIMER).strip(),
            categories=CATEGORY_LABELS.get(ev.get("category", ""), ""),
        )


def game_title(g: dict) -> str:
    bits = [b for b in (g.get("gender"), g["sportLabel"]) if b]
    label = " ".join(bits)
    level = g.get("level") or ""
    if level and level not in ("Unspecified", "All Levels"):
        label = f"{label} ({level})"
    prefix = "vs" if g.get("homeAway") == "Home" else "at" if g.get("homeAway") == "Away" else "vs"
    return f"{label} {prefix} {g['opponent']}".strip()


def add_sports(cal: Calendar, games: list[dict]) -> None:
    for g in games:
        gd = date.fromisoformat(g["date"])
        uid = make_uid(UID_NS, "sport", g["sport"], g.get("level", ""),
                       g.get("gender", ""), g["date"], g["opponent"])
        desc_parts = [
            f"{g.get('gender','')} {g['sportLabel']} — {g.get('level','')}".strip(" —"),
            f"Opponent: {g['opponent']}",
        ]
        if g.get("homeAway"):
            desc_parts.append(f"Home/Away: {g['homeAway']}")
        if not g.get("time"):
            desc_parts.append("Start time not listed on the published schedule.")
        if g.get("source"):
            desc_parts.append(f"Source: {g['source']}")
        desc_parts.append(DISCLAIMER)
        description = "\n".join(p for p in desc_parts if p)

        location = "Mason High School, 6100 S Mason Montgomery Rd, Mason, OH 45040" \
            if g.get("homeAway") == "Home" else (g["opponent"] if g.get("homeAway") == "Away" else "")

        if g.get("time"):
            hh, mm = (int(x) for x in g["time"].split(":"))
            cal.add_timed(
                uid=uid,
                summary=game_title(g),
                start=datetime(gd.year, gd.month, gd.day, hh, mm),
                duration_minutes=g.get("durationMinutes", 120),
                description=description,
                location=location,
                categories="Athletics",
            )
        else:
            cal.add_all_day(
                uid=uid,
                summary=game_title(g) + " (time TBA)",
                start=gd,
                end_inclusive=gd,
                description=description,
                categories="Athletics",
            )


def add_sports_placeholder(cal: Calendar) -> None:
    """
    A VCALENDAR with zero VEVENTs is legal, but several clients (Google in
    particular) treat an empty subscription as a broken URL and quietly drop
    it. One informational event keeps the subscription healthy and tells the
    parent exactly why it looks empty.
    """
    cal.add_all_day(
        uid=make_uid(UID_NS, "sports-placeholder", cal.name),
        summary="Varsity schedules not published yet",
        start=date(2026, 8, 13),
        end_inclusive=date(2026, 8, 13),
        description=(
            "Mason athletics has not posted its 2026-2027 schedules yet.\n\n"
            "This subscription is live and checks for them every day. Games will "
            "appear here on their own within about a day of the schedules going up "
            "— you do not need to re-subscribe.\n\n"
            "Source checked: https://www.gomasoncomets.com/schedules/\n\n"
            + DISCLAIMER
        ),
        categories="Athletics",
    )


def write_feed(cal: Calendar, filename: str, now: datetime) -> dict:
    FEED_DIR.mkdir(parents=True, exist_ok=True)
    path = FEED_DIR / filename
    payload = cal.serialize(now)
    path.write_text(payload, encoding="utf-8", newline="")
    return {"file": filename, "events": len(cal.events), "bytes": len(payload.encode())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="https://example.github.io/mason-family-calendar",
                    help="public base URL where dist/ will be served (no trailing slash)")
    ap.add_argument("--now", default=None, help="ISO timestamp override, for reproducible builds")
    args = ap.parse_args()

    base = args.base_url.rstrip("/")
    now = datetime.fromisoformat(args.now) if args.now else datetime.utcnow()

    schools = load_json(DATA / "schools.json")
    academic = load_json(DATA / "academic-2026-27.json")

    scraped_path = DATA / "sports-scraped.json"
    scraped = load_json(scraped_path) if scraped_path.exists() else {"games": [], "problems": [], "sources": []}
    manual_path = DATA / "sports-manual.json"
    manual = load_json(manual_path) if manual_path.exists() else {"games": []}

    # manual entries win over scraped ones with the same identity
    merged: dict[tuple, dict] = {}
    for g in scraped.get("games", []) + manual.get("games", []):
        merged[(g["sport"], g.get("level", ""), g.get("gender", ""), g["date"], g["opponent"])] = g
    games = sorted(merged.values(), key=lambda g: (g["date"], g.get("time") or ""))

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    feeds: list[dict] = []
    year = academic["year"]

    published = [b for b in schools["buildings"] if b["published"]]

    # --- one academic feed per published building ---------------------------
    for b in published:
        cal = Calendar(
            name=f"{b['abbr']} {year} — Mason Family Calendar",
            description=(f"{b['name']} (grades {b['grades']}) academic calendar for {year}. "
                         f"{DISCLAIMER}"),
            url=f"{base}/feeds/{b['code']}.ics",
            color="#1f7ae0",
        )
        add_academic(cal, academic_events_for(b["code"], academic), b["code"])
        info = write_feed(cal, f"{b['code']}.ics", now)
        feeds.append({
            **info,
            "id": b["code"],
            "title": f"{b['name']} ({b['grades']})",
            "kind": "academic",
            "building": b["code"],
            "summary": f"Academic calendar only — no school days, breaks, Journey Days, first and last day.",
        })

    # --- district-wide academic feed ---------------------------------------
    cal = Calendar(
        name=f"Mason City Schools {year} — District Calendar",
        description=f"District-wide academic calendar for {year}. {DISCLAIMER}",
        url=f"{base}/feeds/district.ics",
        color="#1f7ae0",
    )
    add_academic(cal, [e for e in academic["events"] if "all" in e.get("audiences", ["all"])], "all")
    info = write_feed(cal, "district.ics", now)
    feeds.append({
        **info, "id": "district", "title": "Whole district (any grade)",
        "kind": "academic", "building": "all",
        "summary": "Every district-wide date. Use this if you have kids in several buildings.",
    })

    # --- varsity sports, all sports ----------------------------------------
    cal = Calendar(
        name=f"MHS Varsity Athletics {year} — Mason Family Calendar",
        description=f"All Mason High School varsity athletics for {year}. {DISCLAIMER}",
        url=f"{base}/feeds/varsity-all.ics",
        color="#0f9d58",
    )
    add_sports(cal, games)
    if not games:
        add_sports_placeholder(cal)
    info = write_feed(cal, "varsity-all.ics", now)
    feeds.append({
        **info, "id": "varsity-all", "title": "MHS Varsity Athletics — all sports",
        "kind": "sports", "building": "mhs",
        "summary": "Every varsity game and meet across all sports.",
    })

    # --- MHS academic + varsity combined ------------------------------------
    cal = Calendar(
        name=f"MHS {year} + Varsity Athletics — Mason Family Calendar",
        description=(f"Mason High School academic calendar plus all varsity athletics "
                     f"for {year}. {DISCLAIMER}"),
        url=f"{base}/feeds/mhs-varsity.ics",
        color="#1f7ae0",
    )
    add_academic(cal, academic_events_for("mhs", academic), "mhs")
    add_sports(cal, games)
    if not games:
        add_sports_placeholder(cal)
    info = write_feed(cal, "mhs-varsity.ics", now)
    feeds.append({
        **info, "id": "mhs-varsity", "title": "Mason High School (9–12) + Varsity Athletics",
        "kind": "combined", "building": "mhs",
        "summary": "One subscription: the MHS academic calendar and every varsity game.",
    })

    # --- per-sport varsity feeds -------------------------------------------
    by_sport: dict[str, list[dict]] = {}
    for g in games:
        by_sport.setdefault(g["sport"], []).append(g)

    for sport_code, sport_games in sorted(by_sport.items()):
        label = sport_games[0]["sportLabel"]
        cal = Calendar(
            name=f"MHS Varsity {label} {year}",
            description=f"Mason High School varsity {label} schedule for {year}. {DISCLAIMER}",
            url=f"{base}/feeds/varsity-{sport_code}.ics",
            color="#0f9d58",
        )
        add_sports(cal, sport_games)
        info = write_feed(cal, f"varsity-{sport_code}.ics", now)
        feeds.append({
            **info, "id": f"varsity-{sport_code}", "title": f"Varsity {label}",
            "kind": "sport", "building": "mhs", "sport": sport_code,
            "summary": f"Varsity {label} only.",
        })

    # --- site data ----------------------------------------------------------
    manifest = {
        "generated": now.replace(microsecond=0).isoformat() + "Z",
        "year": year,
        "baseUrl": base,
        "disclaimer": DISCLAIMER,
        "district": schools["district"],
        "buildings": schools["buildings"],
        "feeds": feeds,
        "academicEvents": [
            {
                "id": e["id"], "summary": e["summary"], "start": e["start"],
                "end": e["end"], "category": e.get("category", ""),
                "audiences": e.get("audiences", ["all"]),
                "description": e.get("description", ""),
                "byAudience": e.get("byAudience", {}),
            }
            for e in academic["events"]
        ],
        "sportsEvents": [
            {
                "date": g["date"], "time": g.get("time"), "sport": g["sport"],
                "summary": game_title(g),
            }
            for g in games
        ],
        "sports": {
            "gameCount": len(games),
            "sports": sorted({g["sportLabel"] for g in games}),
            "lastScraped": scraped.get("generated"),
            "problems": scraped.get("problems", []),
            "sourcesChecked": len(scraped.get("sources", [])),
        },
        "categoryLabels": CATEGORY_LABELS,
    }

    for name in ("index.html", "styles.css", "app.js"):
        src = SITE / name
        if src.exists():
            shutil.copy2(src, DIST / name)

    (DIST / "calendar.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (DIST / ".nojekyll").write_text("", encoding="utf-8")
    (DIST / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")

    print(f"Built {len(feeds)} feeds into {FEED_DIR}")
    for f in feeds:
        print(f"  {f['file']:<28} {f['events']:>4} events  {f['bytes']:>7} bytes")
    if manifest["sports"]["problems"]:
        print("\nSports scraper notes:")
        for p in manifest["sports"]["problems"]:
            print(f"  ! {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
