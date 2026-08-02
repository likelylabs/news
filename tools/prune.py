#!/usr/bin/env python3
"""
Retention / tidy-up. Deletes article files older than the on-disk window
and trims stale entries from ledger.json. Git history remains the archive.

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
ARTICLES_DIR = REPO / "articles"
LEDGER_PATH = REPO / "ledger.json"

# Keep article files on disk this long, then delete (git history is the archive).
# Must be >= index live window (72h) so nothing vanishes from a live index early.
ARTICLE_RETENTION_DAYS = 14
# Keep dedup keys this long — longer than the live window so a story that just
# rolled off the front page isn't re-reported as "new".
LEDGER_RETENTION_DAYS = 5

HKT = timezone(timedelta(hours=8))


def parse_dt(s):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def main():
    dry = "--dry-run" in sys.argv
    now = datetime.now(HKT)
    art_cutoff = now - timedelta(days=ARTICLE_RETENTION_DAYS)
    led_cutoff = now - timedelta(days=LEDGER_RETENTION_DAYS)

    # 1) Prune old article files.
    removed = 0
    for path in sorted(ARTICLES_DIR.glob("*/*.json")):
        try:
            art = json.loads(path.read_text(encoding="utf-8"))
            pub = parse_dt(art.get("published_at"))
        except (json.JSONDecodeError, OSError):
            pub = None
        if pub is not None and pub < art_cutoff:
            print(f"{'would delete' if dry else 'delete'}: {path.relative_to(REPO)}")
            if not dry:
                path.unlink()
            removed += 1

    # Remove empty date folders.
    if not dry:
        for d in sorted(ARTICLES_DIR.glob("*/")):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()

    # 2) Trim stale ledger entries. A momentarily empty or corrupt ledger.json
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

    print(f"{'[dry-run] ' if dry else ''}pruned {removed} article file(s), "
          f"trimmed {trimmed} ledger entr(y/ies).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
