"""
Validate every generated .ics in dist/feeds/.

Checks the things that actually break calendar clients in the wild:
  * CRLF line endings everywhere
  * no content line longer than 75 octets
  * balanced BEGIN/END, required properties present
  * DTEND strictly after DTSTART
  * UIDs unique inside a feed and stable-looking
  * the file round-trips through the `icalendar` library if it is installed

Exits non-zero on any error so CI stops before publishing a broken feed.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEEDS = ROOT / "dist" / "feeds"

REQUIRED_CAL_PROPS = ("VERSION:2.0", "PRODID:", "CALSCALE:GREGORIAN")
REQUIRED_EVENT_PROPS = ("UID:", "DTSTAMP:", "DTSTART", "SUMMARY:")


def unfold(raw: str) -> list[str]:
    lines = raw.split("\r\n")
    out: list[str] = []
    for line in lines:
        if line.startswith(" ") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return [l for l in out if l]


def parse_dt(value: str) -> datetime | None:
    value = value.split(":", 1)[-1].strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def validate(path: Path) -> list[str]:
    errors: list[str] = []
    raw = path.read_bytes().decode("utf-8")

    if "\r\n" not in raw:
        errors.append("no CRLF line endings found")
    stray = re.findall(r"(?<!\r)\n", raw)
    if stray:
        errors.append(f"{len(stray)} bare LF line ending(s) — must be CRLF")

    for i, line in enumerate(raw.split("\r\n"), 1):
        if len(line.encode("utf-8")) > 75:
            errors.append(f"line {i} is {len(line.encode())} octets (>75), folding failed")

    lines = unfold(raw)
    if lines[0] != "BEGIN:VCALENDAR":
        errors.append("does not start with BEGIN:VCALENDAR")
    if lines[-1] != "END:VCALENDAR":
        errors.append("does not end with END:VCALENDAR")

    body = "\r\n".join(lines)
    for prop in REQUIRED_CAL_PROPS:
        if prop not in body:
            errors.append(f"missing calendar property {prop}")

    depth = 0
    for line in lines:
        if line.startswith("BEGIN:"):
            depth += 1
        elif line.startswith("END:"):
            depth -= 1
        if depth < 0:
            errors.append("unbalanced BEGIN/END")
            break
    if depth != 0:
        errors.append(f"unbalanced BEGIN/END (depth {depth} at EOF)")

    # per-event checks
    uids: set[str] = set()
    event: list[str] = []
    in_event = False
    count = 0
    for line in lines:
        if line == "BEGIN:VEVENT":
            in_event, event = True, []
            continue
        if line == "END:VEVENT":
            in_event = False
            count += 1
            blob = "\r\n".join(event)
            for prop in REQUIRED_EVENT_PROPS:
                if prop not in blob:
                    errors.append(f"event {count}: missing {prop}")
            uid_line = next((l for l in event if l.startswith("UID:")), None)
            if uid_line:
                uid = uid_line[4:]
                if uid in uids:
                    errors.append(f"duplicate UID {uid}")
                uids.add(uid)
            ds = next((l for l in event if l.startswith("DTSTART")), None)
            de = next((l for l in event if l.startswith("DTEND")), None)
            if ds and de:
                a, b = parse_dt(ds), parse_dt(de)
                if a and b and b <= a:
                    errors.append(f"event {count}: DTEND ({b}) not after DTSTART ({a})")
            continue
        if in_event:
            event.append(line)

    # optional strict parse
    try:
        from icalendar import Calendar as ICalCalendar  # type: ignore
        cal = ICalCalendar.from_ical(raw)
        parsed = sum(1 for c in cal.walk() if c.name == "VEVENT")
        if parsed != count:
            errors.append(f"icalendar parsed {parsed} events, expected {count}")
    except ImportError:
        pass
    except Exception as exc:
        errors.append(f"icalendar could not parse the file: {exc}")

    return errors


def main() -> int:
    if not FEEDS.exists():
        print(f"No feeds directory at {FEEDS} — run scripts/build.py first.")
        return 1

    files = sorted(FEEDS.glob("*.ics"))
    if not files:
        print("No .ics files were generated.")
        return 1

    total_errors = 0
    for path in files:
        errors = validate(path)
        status = "OK  " if not errors else "FAIL"
        print(f"{status} {path.name}")
        for e in errors:
            print(f"       - {e}")
        total_errors += len(errors)

    print(f"\n{len(files)} feeds checked, {total_errors} problem(s).")
    return 1 if total_errors else 0


if __name__ == "__main__":
    sys.exit(main())
