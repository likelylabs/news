#!/usr/bin/env python3
"""
Validate every article and (re)generate index.json deterministically.

This is the SANCTIONED WRITE PATH for index.json (tenet #5). The grok
automation NEVER hand-edits index.json — it writes article files, then
runs this script. If ANY article is malformed, this exits non-zero and
the run must abort before committing.

Stdlib only. Run from the repo root:  python3 tools/build_index.py
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ARTICLES_DIR = REPO / "articles"
INDEX_PATH = REPO / "index.json"

# Articles whose published_at is within this window appear in index.json.
# Older articles stay on disk forever and are served at /archive/
# (tools/build_archive.py, which must keep the same window).
LIVE_WINDOW_HOURS = 72
HKT = timezone(timedelta(hours=8))

CATEGORIES = {
    "politics", "business", "weather", "transport", "health",
    "crime", "community", "culture", "sport", "technology",
}
ID_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9]+(-[a-z0-9]+)*$")
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DT_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\+08:00$")

TOP_KEYS = {"id", "published_at", "updated_at", "category", "tags",
            "breaking", "ai_generated", "story_key", "en", "zh"}
LANG_KEYS = {"headline", "dek", "body"}

# Length caps for the short display fields. Over-length values are trimmed
# to the max (see normalize_lengths) rather than failing the run; the min is
# still enforced by validation (truncation can't fix a too-short field).
HEADLINE_MIN, HEADLINE_MAX = 8, 90
DEK_MIN, DEK_MAX = 12, 220


def err(path, msg):
    return f"{path}: {msg}"


def truncate_text(s, max_len):
    """Trim s to at most max_len characters, ending with an ellipsis.

    Space-delimited text (English) is cut back to the last word boundary so
    we don't slice a word in half; scripts without spaces (Chinese) fall
    back to a hard cut. The ellipsis (…) counts as one character, so the
    result is always <= max_len.
    """
    if len(s) <= max_len:
        return s
    cut = s[: max_len - 1].rstrip()
    sp = cut.rfind(" ")
    if sp >= max_len // 2:  # only honour a word boundary that isn't too greedy
        cut = cut[:sp]
    cut = cut.rstrip(" ,.;:!?—–-")
    return cut + "…"


def normalize_lengths(art):
    """Auto-trim over-length headline/dek fields to their caps so one long
    value degrades gracefully instead of failing the whole index build.

    Mutates art in place and returns a list of human-readable change notes
    (empty if nothing needed trimming).
    """
    notes = []
    for lang in ("en", "zh"):
        obj = art.get(lang)
        if not isinstance(obj, dict):
            continue
        for key, cap in (("headline", HEADLINE_MAX), ("dek", DEK_MAX)):
            val = obj.get(key)
            if isinstance(val, str) and len(val) > cap:
                new = truncate_text(val, cap)
                obj[key] = new
                notes.append(f"{lang}.{key} {len(val)}→{len(new)} chars")
    return notes


def validate_localized(lang, obj, path):
    problems = []
    if not isinstance(obj, dict):
        return [err(path, f"'{lang}' must be an object")]
    extra = set(obj) - LANG_KEYS
    if extra:
        problems.append(err(path, f"'{lang}' has unexpected keys: {sorted(extra)}"))
    for k in ("headline", "dek", "body"):
        if k not in obj:
            problems.append(err(path, f"'{lang}.{k}' is required"))
    hl = obj.get("headline")
    if isinstance(hl, str):
        if not (HEADLINE_MIN <= len(hl) <= HEADLINE_MAX):
            problems.append(err(path, f"'{lang}.headline' length must be {HEADLINE_MIN}-{HEADLINE_MAX} (got {len(hl)})"))
    elif hl is not None:
        problems.append(err(path, f"'{lang}.headline' must be a string"))
    dek = obj.get("dek")
    if isinstance(dek, str):
        if not (DEK_MIN <= len(dek) <= DEK_MAX):
            problems.append(err(path, f"'{lang}.dek' length must be {DEK_MIN}-{DEK_MAX} (got {len(dek)})"))
    elif dek is not None:
        problems.append(err(path, f"'{lang}.dek' must be a string"))
    body = obj.get("body")
    if isinstance(body, list):
        if len(body) < 2:
            problems.append(err(path, f"'{lang}.body' needs >= 2 paragraphs (got {len(body)})"))
        for i, p in enumerate(body):
            if not isinstance(p, str) or not p.strip():
                problems.append(err(path, f"'{lang}.body[{i}]' must be a non-empty string"))
    elif body is not None:
        problems.append(err(path, f"'{lang}.body' must be an array of paragraphs"))
    return problems


def validate(art, path, expected_date):
    problems = []
    if not isinstance(art, dict):
        return [err(path, "top level must be an object")]
    extra = set(art) - TOP_KEYS
    if extra:
        problems.append(err(path, f"unexpected top-level keys: {sorted(extra)}"))

    aid = art.get("id")
    if not isinstance(aid, str) or not ID_RE.match(aid or ""):
        problems.append(err(path, "'id' missing or not YYYY-MM-DD-<slug>"))
    else:
        # File must live at articles/<date>/<id>.json with <date> == id's date.
        if path.stem != aid:
            problems.append(err(path, f"filename must equal id ('{aid}.json')"))
        if expected_date and not aid.startswith(expected_date + "-"):
            problems.append(err(path, f"id date must match folder '{expected_date}'"))

    pub = art.get("published_at")
    if not isinstance(pub, str) or not DT_RE.match(pub or ""):
        problems.append(err(path, "'published_at' missing or not ISO-8601 +08:00"))

    upd = art.get("updated_at")
    if upd is not None and (not isinstance(upd, str) or not DT_RE.match(upd)):
        problems.append(err(path, "'updated_at' must be ISO-8601 +08:00"))

    if art.get("category") not in CATEGORIES:
        problems.append(err(path, f"'category' must be one of {sorted(CATEGORIES)}"))

    if art.get("ai_generated") is not True:
        problems.append(err(path, "'ai_generated' must be true"))

    tags = art.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 6 or len(set(tags)) != len(tags) \
            or any(not (isinstance(t, str) and SLUG_RE.match(t)) for t in tags):
        problems.append(err(path, "'tags' must be <=6 unique lowercase slugs"))

    if "breaking" in art and not isinstance(art["breaking"], bool):
        problems.append(err(path, "'breaking' must be a boolean"))

    sk = art.get("story_key")
    if sk is not None and not (isinstance(sk, str) and SLUG_RE.match(sk)):
        problems.append(err(path, "'story_key' must be a lowercase slug"))

    for lang in ("en", "zh"):
        if lang not in art:
            problems.append(err(path, f"'{lang}' version is required"))
        else:
            problems += validate_localized(lang, art[lang], path)
    return problems


def main():
    now = datetime.now(HKT)
    cutoff = now - timedelta(hours=LIVE_WINDOW_HOURS)

    all_problems = []
    seen_ids = {}
    entries = []
    normalized = []

    for path in sorted(ARTICLES_DIR.glob("*/*.json")):
        expected_date = path.parent.name
        try:
            art = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            all_problems.append(err(path, f"invalid JSON: {e}"))
            continue

        # Auto-trim over-length headline/dek before validating so one long
        # field can't fail the whole run. The trimmed value is written back
        # to the source article so it and the index stay consistent (the
        # workflow's commit step picks up the rewritten file).
        notes = normalize_lengths(art)
        if notes:
            path.write_text(json.dumps(art, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
            normalized.extend(f"{path.relative_to(REPO)}: {n}" for n in notes)

        problems = validate(art, path, expected_date)
        all_problems += problems
        if problems:
            continue

        aid = art["id"]
        if aid in seen_ids:
            all_problems.append(err(path, f"duplicate id also in {seen_ids[aid]}"))
            continue
        seen_ids[aid] = path

        # Only articles inside the live window go into the index.
        pub_dt = datetime.fromisoformat(art["published_at"])
        if pub_dt < cutoff:
            continue

        entries.append({
            "id": aid,
            "published_at": art["published_at"],
            "updated_at": art.get("updated_at"),
            "category": art["category"],
            "tags": art.get("tags", []),
            "breaking": art.get("breaking", False),
            "path": str(path.relative_to(REPO)),
            "en": {"headline": art["en"]["headline"], "dek": art["en"]["dek"]},
            "zh": {"headline": art["zh"]["headline"], "dek": art["zh"]["dek"]},
        })

    if normalized:
        print(f"auto-trimmed {len(normalized)} over-length field(s) to the cap:")
        for n in normalized:
            print("  - " + n)

    if all_problems:
        print("VALIDATION FAILED — index NOT written:", file=sys.stderr)
        for p in all_problems:
            print("  - " + p, file=sys.stderr)
        return 1

    entries.sort(key=lambda e: e["published_at"], reverse=True)
    index = {
        "generated_at": now.isoformat(timespec="seconds"),
        "live_window_hours": LIVE_WINDOW_HOURS,
        "count": len(entries),
        "articles": entries,
    }
    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"index.json rebuilt: {len(entries)} live article(s) within {LIVE_WINDOW_HOURS}h.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
