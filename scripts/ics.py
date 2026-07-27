"""
Minimal, dependency-free RFC 5545 (iCalendar) writer.

Deliberately small and strict:
  * CRLF line endings
  * content lines folded at 75 octets (folding counts bytes, not characters)
  * TEXT values escaped per section 3.3.11
  * all-day events use VALUE=DATE with an EXCLUSIVE DTEND
  * timed events carry a real VTIMEZONE so Outlook and Apple agree with Google

Everything downstream (build.py) just hands this module dicts.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta

PRODID = "-//Mason Family Calendar//Unofficial MCS Calendar Feeds//EN"

# A correct VTIMEZONE for America/New_York using the post-2007 US DST rules.
# Embedding this (rather than relying on the client) is what keeps 7:00 PM
# kickoff at 7:00 PM in Outlook desktop, which does not resolve bare TZIDs.
VTIMEZONE_NEW_YORK = """BEGIN:VTIMEZONE
TZID:America/New_York
X-LIC-LOCATION:America/New_York
BEGIN:DAYLIGHT
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE""".split("\n")


def escape_text(value: str) -> str:
    """Escape a TEXT value per RFC 5545 3.3.11."""
    if value is None:
        return ""
    out = str(value)
    out = out.replace("\\", "\\\\")
    out = out.replace(";", "\\;")
    out = out.replace(",", "\\,")
    out = out.replace("\r\n", "\n").replace("\r", "\n")
    out = out.replace("\n", "\\n")
    return out


def fold(line: str) -> list[str]:
    """
    Fold a content line to <=75 octets, continuing with a single leading space.
    Folds on byte boundaries without splitting a UTF-8 sequence.
    """
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return [line]

    pieces: list[str] = []
    limit = 75
    start = 0
    while start < len(raw):
        end = min(start + limit, len(raw))
        # never split a multi-byte character
        while end > start and end < len(raw) and (raw[end] & 0xC0) == 0x80:
            end -= 1
        pieces.append(raw[start:end].decode("utf-8"))
        start = end
        limit = 74  # continuation lines lose one octet to the leading space
    return [pieces[0]] + [" " + p for p in pieces[1:]]


def _stamp(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def make_uid(namespace: str, *parts: str) -> str:
    """Deterministic UID. Same event -> same UID across rebuilds, so clients update in place."""
    digest = hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:24]
    return f"{digest}@{namespace}"


class Calendar:
    def __init__(self, name: str, description: str, *, url: str = "",
                 timezone: str = "America/New_York", refresh_hours: int = 12,
                 color: str = ""):
        self.name = name
        self.description = description
        self.url = url
        self.timezone = timezone
        self.refresh_hours = refresh_hours
        self.color = color
        self.events: list[dict] = []
        self._needs_vtimezone = False

    def add_all_day(self, *, uid: str, summary: str, start: date, end_inclusive: date,
                    description: str = "", categories: str = "",
                    last_modified: datetime | None = None, url: str = ""):
        self.events.append({
            "kind": "date",
            "uid": uid,
            "summary": summary,
            "start": start,
            "end": end_inclusive + timedelta(days=1),  # DTEND is exclusive
            "description": description,
            "categories": categories,
            "last_modified": last_modified,
            "url": url,
            "location": "",
        })

    def add_timed(self, *, uid: str, summary: str, start: datetime,
                  duration_minutes: int = 120, description: str = "",
                  location: str = "", categories: str = "",
                  last_modified: datetime | None = None, url: str = ""):
        self._needs_vtimezone = True
        self.events.append({
            "kind": "datetime",
            "uid": uid,
            "summary": summary,
            "start": start,
            "end": start + timedelta(minutes=duration_minutes),
            "description": description,
            "categories": categories,
            "last_modified": last_modified,
            "url": url,
            "location": location,
        })

    def serialize(self, now: datetime) -> str:
        lines: list[str] = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            f"PRODID:{PRODID}",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            f"X-WR-CALNAME:{escape_text(self.name)}",
            f"X-WR-CALDESC:{escape_text(self.description)}",
            f"X-WR-TIMEZONE:{self.timezone}",
            f"NAME:{escape_text(self.name)}",
            f"DESCRIPTION:{escape_text(self.description)}",
            f"REFRESH-INTERVAL;VALUE=DURATION:PT{self.refresh_hours}H",
            f"X-PUBLISHED-TTL:PT{self.refresh_hours}H",
        ]
        if self.color:
            lines.append(f"COLOR:{self.color}")
        if self.url:
            lines.append(f"URL:{self.url}")
        if self._needs_vtimezone and self.timezone == "America/New_York":
            lines.extend(VTIMEZONE_NEW_YORK)

        dtstamp = _stamp(now)
        for ev in sorted(self.events, key=lambda e: (str(e["start"]), e["summary"])):
            lines.append("BEGIN:VEVENT")
            lines.append(f"UID:{ev['uid']}")
            lines.append(f"DTSTAMP:{dtstamp}")
            if ev["kind"] == "date":
                lines.append("DTSTART;VALUE=DATE:" + ev["start"].strftime("%Y%m%d"))
                lines.append("DTEND;VALUE=DATE:" + ev["end"].strftime("%Y%m%d"))
                lines.append("X-MICROSOFT-CDO-ALLDAYEVENT:TRUE")
                lines.append("X-MICROSOFT-CDO-BUSYSTATUS:FREE")
                lines.append("TRANSP:TRANSPARENT")
            else:
                tz = self.timezone
                lines.append(f"DTSTART;TZID={tz}:" + ev["start"].strftime("%Y%m%dT%H%M%S"))
                lines.append(f"DTEND;TZID={tz}:" + ev["end"].strftime("%Y%m%dT%H%M%S"))
                lines.append("TRANSP:OPAQUE")
            lines.append(f"SUMMARY:{escape_text(ev['summary'])}")
            if ev["description"]:
                lines.append(f"DESCRIPTION:{escape_text(ev['description'])}")
            if ev["location"]:
                lines.append(f"LOCATION:{escape_text(ev['location'])}")
            if ev["categories"]:
                lines.append(f"CATEGORIES:{escape_text(ev['categories'])}")
            if ev["url"]:
                lines.append(f"URL:{ev['url']}")
            lm = ev["last_modified"] or now
            lines.append(f"LAST-MODIFIED:{_stamp(lm)}")
            lines.append("SEQUENCE:0")
            lines.append("STATUS:CONFIRMED")
            lines.append("END:VEVENT")

        lines.append("END:VCALENDAR")

        folded: list[str] = []
        for line in lines:
            folded.extend(fold(line))
        return "\r\n".join(folded) + "\r\n"
