#!/usr/bin/env python3
"""
Pulls the latest MECC PTO events from the live sync endpoint (kept up to date
by an automated Google-Drive-monitoring job) and merges them into
data/mecc-pto-2026-27.json, preserving the static metadata fields (year,
source, audience, notes).

If PTO_SYNC_URL is not set (secret missing), this is a no-op -- the build
proceeds with whatever is already committed in data/mecc-pto-2026-27.json,
exactly like before this script existed.

Run as part of the build workflow, before scripts/build.py:
    PTO_SYNC_URL='...' python scripts/fetch_pto_sync.py
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "mecc-pto-2026-27.json"


def main() -> int:
    sync_url = os.environ.get("PTO_SYNC_URL", "").strip()
    if not sync_url:
        print("PTO_SYNC_URL not set -- skipping live sync, using committed data as-is.")
        return 0

    try:
        req = urllib.request.Request(sync_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"WARNING: could not fetch PTO sync data ({e}); keeping existing file.")
        return 0

    events = payload.get("events")
    if not isinstance(events, list) or not events:
        print("WARNING: sync payload had no events; keeping existing file.")
        return 0

    current = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    before = json.dumps(current.get("events", []), sort_keys=True)

    current["events"] = events
    current["unscheduled"] = payload.get("unscheduled", current.get("unscheduled", []))

    after = json.dumps(current["events"], sort_keys=True)

    DATA_FILE.write_text(
        json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    if before == after:
        print(f"Synced {len(events)} PTO events -- no changes.")
    else:
        print(f"Synced {len(events)} PTO events -- data file updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())