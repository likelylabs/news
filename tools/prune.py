#!/usr/bin/env python3
"""
Ledger tidy-up. Trims stale dedup entries from ledger.json.

Article files are PERMANENT — never deleted. Everything older than the 72h
live window is served human-readably at /archive/ (rendered at deploy time
by tools/build_archive.py; see pages-deploy.yml).

Run BEFORE build_index.py in each run:
    python3 tools/prune.py            # apply
    python3 tools/prune.py --dry-run  # show what would change, touch nothing

Stdlib only. Constants below are the only knobs.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LEDGER_PATH = REPO / "ledger.json"

# Keep dedup keys this long — longer than the 72h live window so a story that
# just rolled off the front page isn't re-reported as "new", and long enough
# that a long-running lifestyle subject (an exhibition that runs for weeks, a
# shop that keeps getting written up) isn't re-covered every cycle.
# (Article FILES are never deleted; only this dedup memory ages out.)
LEDGER_RETENTION_DAYS = 14

HKT = timezone(timedelta(hours=8))


def parse_dt(s):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def main():
    dry = "--dry-run" in sys.argv
    now = datetime.now(HKT)
    led_cutoff = now - timedelta(days=LEDGER_RETENTION_DAYS)

    # Trim stale ledger entries. A momentarily empty or corrupt ledger.json
    # (e.g. an interrupted/empty write from the news automation) must NOT crash
    # the whole run — skip trimming this pass and leave the file untouched so
    # the next automation write can self-heal it. Overwriting it with an empty
    # ledger here would wipe dedup state and let old stories re-report as "new".
    trimmed = 0
    try:
        ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"WARNING: ledger.json unreadable ({e}); skipping ledger trim "
              f"(left untouched for the next automation run to self-heal).",
              file=sys.stderr)
        ledger = None
    if ledger is not None:
        before = len(ledger.get("covered", []))
        kept = [e for e in ledger.get("covered", [])
                if (parse_dt(e.get("first_seen")) or now) >= led_cutoff]
        trimmed = before - len(kept)
        if not dry:
            ledger["covered"] = kept
            ledger["updated_at"] = now.isoformat(timespec="seconds")
            LEDGER_PATH.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{'[dry-run] ' if dry else ''}trimmed {trimmed} ledger entr(y/ies).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
