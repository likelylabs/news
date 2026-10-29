#!/usr/bin/env python3
"""
Ledger tidy-up. Rebuilds ledger.json from the article files and trims stale
dedup entries.

Article files are PERMANENT — never deleted. Everything older than the 72h
live window is served human-readably at /archive/ (rendered at deploy time
by tools/build_archive.py; see pages-deploy.yml).

The ledger is derived data: every article carries its story_key, id,
published_at and headline, which is everything a ledger entry holds. The news
automation rewrites ledger.json by hand and has left it as a placeholder
string, a bare list, or truncated to one run's entries. So this script never
trusts the file's shape: it keeps whatever well-formed entries it can read,
adds an entry for every in-window article that is missing one, and always
writes the canonical {"covered": [...], "updated_at": ...} form.

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
ARTICLES_DIR = REPO / "articles"

# Keep dedup keys this long — longer than the 72h live window so a story that
# just rolled off the front page isn't re-reported as "new", and long enough
# that a long-running lifestyle subject (an exhibition that runs for weeks, a
# shop that keeps getting written up) isn't re-covered every cycle.
# (Article FILES are never deleted; only this dedup memory ages out.)
LEDGER_RETENTION_DAYS = 14

HKT = timezone(timedelta(hours=8))


def parse_dt(s):
    try:
        dt = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    # A naive timestamp can't be compared with the aware cutoff.
    return dt if dt.tzinfo else None


def read_entries():
    """Return the well-formed entries in ledger.json, whatever its shape.

    Accepts the canonical {"covered": [...]} or a bare list. Anything else
    (missing, empty, placeholder text, invalid JSON) yields no entries and a
    warning; the articles still rebuild the ledger in main().
    """
    try:
        ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"WARNING: ledger.json unreadable ({e}); rebuilding from articles.",
              file=sys.stderr)
        return []
    if isinstance(ledger, dict):
        ledger = ledger.get("covered")
    if not isinstance(ledger, list):
        print("WARNING: ledger.json has no covered list; rebuilding from articles.",
              file=sys.stderr)
        return []
    return [e for e in ledger
            if isinstance(e, dict) and isinstance(e.get("key"), str)
            and isinstance(e.get("id"), str)]


def article_entries():
    """One ledger entry per readable article. Unreadable or incomplete
    articles are skipped here; build_index.py reports them."""
    entries = []
    for path in sorted(ARTICLES_DIR.glob("*/*.json")):
        try:
            art = json.loads(path.read_text(encoding="utf-8"))
            entry = {
                "key": art["story_key"],
                "id": art["id"],
                "first_seen": art["published_at"],
                "headline_en": art["en"]["headline"],
            }
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            continue
        if all(isinstance(v, str) and v for v in entry.values()):
            entries.append(entry)
    return entries


def main():
    dry = "--dry-run" in sys.argv
    now = datetime.now(HKT)
    led_cutoff = now - timedelta(days=LEDGER_RETENTION_DAYS)

    def fresh(e):
        return (parse_dt(e.get("first_seen")) or now) >= led_cutoff

    # Existing entries win over derived ones (same id), so a hand-written key
    # is never replaced; derived entries only fill gaps.
    covered, seen_ids = [], set()
    for e in read_entries():
        if e["id"] not in seen_ids:
            seen_ids.add(e["id"])
            covered.append(e)
    restored = [e for e in article_entries() if e["id"] not in seen_ids and fresh(e)]
    covered += restored
    kept = [e for e in covered if fresh(e)]
    trimmed = len(covered) - len(kept)
    kept.sort(key=lambda e: parse_dt(e.get("first_seen")) or now)

    if not dry:
        ledger = {"covered": kept, "updated_at": now.isoformat(timespec="seconds")}
        LEDGER_PATH.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    prefix = "[dry-run] " if dry else ""
    print(f"{prefix}trimmed {trimmed} ledger entr(y/ies).")
    print(f"{prefix}restored {len(restored)} ledger entr(y/ies) from articles.")
    for e in restored:
        print(f"  + {e['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
