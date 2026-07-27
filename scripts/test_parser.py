"""
Tests for the athletics PDF row parser and the ICS writer.

Run: python scripts/test_parser.py

The sample lines below are taken from the real Mason athletics schedule PDFs
(2025-26 season) so the parser is exercised against the actual formats the
athletics site produces, not invented ones.
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ics import Calendar, escape_text, fold, make_uid  # noqa: E402
from scrape_sports import (  # noqa: E402
    classify_gender,
    classify_level,
    classify_sport,
    parse_row,
    parse_time,
)

FAILURES: list[str] = []


def check(label: str, got, want):
    if got != want:
        FAILURES.append(f"{label}\n     got:  {got!r}\n     want: {want!r}")


SEASON_START = date(2025, 8, 1)

# --------------------------------------------------------------------------
# row parsing
# --------------------------------------------------------------------------

ROWS = [
    (
        "08/02/25 Saturday Girls Soccer Alumni Game Home 5:00 PM",
        {"date": "2025-08-02", "time": "17:00", "opponent": "Girls Soccer Alumni Game", "homeAway": "Home"},
    ),
    (
        "09/13/25 Saturday Walnut Hills High School Away 12:00 PM",
        {"date": "2025-09-13", "time": "12:00", "opponent": "Walnut Hills High School", "homeAway": "Away"},
    ),
    (
        "10/06/25 Monday Little Miami JH/HS Away 7:00 PM",
        {"date": "2025-10-06", "time": "19:00", "opponent": "Little Miami JH/HS", "homeAway": "Away"},
    ),
    (
        "Friday, August 8, 2025 Lebanon High School Home 7:00 PM",
        {"date": "2025-08-08", "time": "19:00", "opponent": "Lebanon High School", "homeAway": "Home"},
    ),
    (
        "Thursday, August 14, 2025 St. Xavier High School Home 7:00 PM",
        {"date": "2025-08-14", "time": "19:00", "opponent": "St. Xavier High School", "homeAway": "Home"},
    ),
    (
        # no printed year — inferred from the season window
        "Sept. 19  Hamilton High School  Away  7:00 PM",
        {"date": "2025-09-19", "time": "19:00", "opponent": "Hamilton High School", "homeAway": "Away"},
    ),
    (
        # January of a fall/winter season rolls into the next calendar year
        "Jan 9  Sycamore High School  Home  7:30 PM",
        {"date": "2026-01-09", "time": "19:30", "opponent": "Sycamore High School", "homeAway": "Home"},
    ),
    (
        # midnight/noon edge on the AM/PM conversion
        "03/14/26 Saturday Centerville Invitational Away 12:00 PM",
        {"date": "2026-03-14", "time": "12:00", "opponent": "Centerville Invitational", "homeAway": "Away"},
    ),
    (
        # time missing entirely -> still a valid game, TBA
        "10/24/25 Friday Sycamore High School Home TBA",
        {"date": "2025-10-24", "time": None, "opponent": "Sycamore High School TBA", "homeAway": "Home"},
    ),
]

for line, want in ROWS:
    got = parse_row(line, 2025, SEASON_START)
    check(f"parse_row({line!r})", got, want)

NON_ROWS = [
    "Date Day Opponent Location Time",
    "Mason High School",
    "Varsity Schedule 8/1/2025 to 11/30/2025",   # header: has dates but is noise
    "",
    "Page 1 of 2",
    "Head Coach: Jane Smith",
]
for line in NON_ROWS:
    got = parse_row(line, 2025, SEASON_START)
    check(f"parse_row({line!r}) is None", got, None)

# --------------------------------------------------------------------------
# time parsing
# --------------------------------------------------------------------------

check("parse_time 12:00 AM", parse_time("12:00 AM"), (0, 0))
check("parse_time 12:30 PM", parse_time("12:30 PM"), (12, 30))
check("parse_time 7:15 p.m.", parse_time("7:15 p.m."), (19, 15))
check("parse_time none", parse_time("TBA"), None)

# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------

check("sport football", classify_sport("Varsity Football Schedule 2025.pdf"), "football")
check("sport water polo", classify_sport("WPschedule2025info.pdf"), "water-polo")
check("sport swim", classify_sport("Boys_Girls S&D Schedule.pdf"), "swim-dive")
check("sport cross country", classify_sport("Cross Country Schedule 2025.pdf"), "cross-country")
check("sport none", classify_sport("Coach Directory"), None)

check("level varsity", classify_level("Boys Varsity Soccer Schedule 2025"), "Varsity")
check("level jv", classify_level("Boys JV Green Soccer"), "JV")
check("level freshman", classify_level("Freshman Football Schedule"), "Freshman")
check("level all", classify_level("Baseball - All Levels"), "All Levels")

check("gender both", classify_gender("Boys and Girls Bowling"), "Boys & Girls")
check("gender girls", classify_gender("Girls Varsity Volleyball"), "Girls")
check("gender none", classify_gender("Football"), "")

# --------------------------------------------------------------------------
# ICS writer
# --------------------------------------------------------------------------

check("escape comma", escape_text("a, b"), "a\\, b")
check("escape semicolon", escape_text("a; b"), "a\\; b")
check("escape backslash", escape_text("a\\b"), "a\\\\b")
check("escape newline", escape_text("a\nb"), "a\\nb")

long_line = "DESCRIPTION:" + ("x" * 300)
folded = fold(long_line)
check("fold first line <=75", len(folded[0].encode()) <= 75, True)
check("fold continuations start with space", all(l.startswith(" ") for l in folded[1:]), True)
check("fold round-trips", folded[0] + "".join(l[1:] for l in folded[1:]), long_line)

# multi-byte safety: an em dash must never be split across a fold boundary
mb = "SUMMARY:" + ("Journey Day — No In-Person Learning " * 6)
mb_folded = fold(mb)
check("fold keeps utf-8 intact", "".join([mb_folded[0]] + [l[1:] for l in mb_folded[1:]]), mb)
check("fold multibyte <=75 octets", all(len(l.encode()) <= 75 for l in mb_folded), True)

check("uid stable", make_uid("ns", "a", "b"), make_uid("ns", "a", "b"))
check("uid distinct", make_uid("ns", "a", "b") != make_uid("ns", "a", "c"), True)

cal = Calendar("Test", "Test feed")
cal.add_all_day(uid="u1@x", summary="One day", start=date(2026, 8, 13), end_inclusive=date(2026, 8, 13))
cal.add_all_day(uid="u2@x", summary="Two days", start=date(2026, 8, 13), end_inclusive=date(2026, 8, 14))
cal.add_timed(uid="u3@x", summary="Game", start=datetime(2026, 9, 4, 19, 0), duration_minutes=120)
out = cal.serialize(datetime(2026, 7, 27, 12, 0, 0))

check("all-day DTEND exclusive (single)", "DTSTART;VALUE=DATE:20260813\r\nDTEND;VALUE=DATE:20260814" in out, True)
check("all-day DTEND exclusive (span)", "DTSTART;VALUE=DATE:20260813\r\nDTEND;VALUE=DATE:20260815" in out, True)
check("timed uses TZID", "DTSTART;TZID=America/New_York:20260904T190000" in out, True)
check("timed DTEND +2h", "DTEND;TZID=America/New_York:20260904T210000" in out, True)
check("VTIMEZONE emitted", "BEGIN:VTIMEZONE" in out and "TZID:America/New_York" in out, True)
check("CRLF only", "\n" not in out.replace("\r\n", ""), True)
check("ends correctly", out.rstrip("\r\n").endswith("END:VCALENDAR"), True)

# a calendar with no timed events must NOT carry a VTIMEZONE it never uses
cal2 = Calendar("NoTZ", "d")
cal2.add_all_day(uid="a@x", summary="x", start=date(2026, 1, 1), end_inclusive=date(2026, 1, 1))
check("no VTIMEZONE when unused", "BEGIN:VTIMEZONE" in cal2.serialize(datetime(2026, 1, 1)), False)

# --------------------------------------------------------------------------

if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S):\n")
    for f in FAILURES:
        print(f"  - {f}\n")
    sys.exit(1)

print("All parser and ICS tests passed.")
