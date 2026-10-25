#!/usr/bin/env python3
"""
Validate every article and (re)generate index.json deterministically.

This is the SANCTIONED WRITE PATH for index.json (tenet #5). The grok
automation NEVER hand-edits index.json — it writes article files, then
runs this script. If ANY article is malformed, this exits non-zero and
the run must abort before committing.

Stdlib only. Run from the repo root:  python3 tools/build_index.py
Use --check for strict, read-only validation before publishing articles.
"""
import argparse
import json
import re
import string
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
TAG_SEPARATORS_RE = re.compile("[" + re.escape(string.punctuation + string.whitespace) + "]+")
MAX_TAGS = 6

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
    if not isinstance(art, dict):
        return notes
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


def normalize_tags(art):
    """Normalize representable ASCII tags, preserving order and lifestyle.

    Invalid containers, non-string/non-ASCII values and empty slugs are left
    for validation. Check every input before deduplication/capping so malformed
    values cannot disappear beyond the six-tag limit.
    """
    if not isinstance(art, dict) or not isinstance(art.get("tags"), list):
        return []
    tags = art["tags"]
    normalized = []
    for tag in tags:
        if not isinstance(tag, str) or not tag.isascii():
            return []
        slug = TAG_SEPARATORS_RE.sub("-", tag.lower()).strip("-")
        if not SLUG_RE.fullmatch(slug):
            return []
        if slug not in normalized:
            normalized.append(slug)
    if len(normalized) > MAX_TAGS:
        # The producer contract requires this filter on lifestyle articles.
        # Keep it even when excess optional tags appeared before it.
        if "lifestyle" in normalized[MAX_TAGS:]:
            normalized = normalized[:MAX_TAGS - 1] + ["lifestyle"]
        else:
            normalized = normalized[:MAX_TAGS]
    if normalized == tags:
        return []
    art["tags"] = normalized
    return [f"tags {tags!r} → {normalized!r}"]


def repair_unescaped_quotes(text):
    """Escape bare ASCII double quotes inside JSON string values.

    The writer's most common slip is quoting speech with a raw `"` inside a
    body paragraph, which ends the string early and makes the whole file
    invalid JSON. A quote that would close a string is treated as closing
    only when what follows is structural: `:`, `}`, `]`, or `,` followed by
    another string/value. Any other quote is escaped. Returns the repaired
    text, or None if nothing was changed. The caller still has to parse and
    validate the result; a wrong guess simply fails as before.
    """
    out = []
    in_string = False
    escaped = False
    changed = False
    n = len(text)
    for i, ch in enumerate(text):
        if not in_string:
            out.append(ch)
            if ch == '"':
                in_string = True
            continue
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == '"':
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            nxt = text[j] if j < n else ""
            closes = nxt in ":}]" or nxt == ""
            if nxt == ",":
                k = j + 1
                while k < n and text[k] in " \t\r\n":
                    k += 1
                closes = k < n and text[k] in '"{[]}'
            if closes:
                in_string = False
            else:
                out.append("\\")
                changed = True
        out.append(ch)
    return "".join(out) if changed else None


def load_article(path):
    """Parse an article, repairing bare inner quotes if that is the only fault.

    Returns (art, note). note is None for clean files and a description of
    the repair otherwise. Raises json.JSONDecodeError (the original error)
    when the file is invalid and the repair does not produce valid JSON.
    """
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text), None
    except json.JSONDecodeError as original:
        repaired = repair_unescaped_quotes(text)
        if repaired is None:
            raise
        try:
            return json.loads(repaired), f"escaped unescaped double quotes ({original})"
        except json.JSONDecodeError:
            raise original from None


def valid_timestamp(value):
    if not isinstance(value, str) or not DT_RE.fullmatch(value):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


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
    elif "headline" in obj:
        problems.append(err(path, f"'{lang}.headline' must be a string"))
    dek = obj.get("dek")
    if isinstance(dek, str):
        if not (DEK_MIN <= len(dek) <= DEK_MAX):
            problems.append(err(path, f"'{lang}.dek' length must be {DEK_MIN}-{DEK_MAX} (got {len(dek)})"))
    elif "dek" in obj:
        problems.append(err(path, f"'{lang}.dek' must be a string"))
    body = obj.get("body")
    if isinstance(body, list):
        if len(body) < 2:
            problems.append(err(path, f"'{lang}.body' needs >= 2 paragraphs (got {len(body)})"))
        for i, p in enumerate(body):
            if not isinstance(p, str) or not p.strip():
                problems.append(err(path, f"'{lang}.body[{i}]' must be a non-empty string"))
    elif "body" in obj:
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
    if not isinstance(aid, str) or not ID_RE.fullmatch(aid):
        problems.append(err(path, "'id' missing or not YYYY-MM-DD-<slug>"))
    else:
        # File must live at articles/<date>/<id>.json with <date> == id's date.
        if path.stem != aid:
            problems.append(err(path, f"filename must equal id ('{aid}.json')"))
        if expected_date and not aid.startswith(expected_date + "-"):
            problems.append(err(path, f"id date must match folder '{expected_date}'"))

    pub = art.get("published_at")
    if not valid_timestamp(pub):
        problems.append(err(path, "'published_at' missing or not a valid ISO-8601 timestamp with +08:00"))

    upd = art.get("updated_at")
    if "updated_at" in art and not valid_timestamp(upd):
        problems.append(err(path, "'updated_at' must be a valid ISO-8601 timestamp with +08:00"))

    category = art.get("category")
    if not isinstance(category, str) or category not in CATEGORIES:
        problems.append(err(path, f"'category' must be one of {sorted(CATEGORIES)}"))

    if art.get("ai_generated") is not True:
        problems.append(err(path, "'ai_generated' must be true"))

    tags = art.get("tags", [])
    if not isinstance(tags, list) or len(tags) > MAX_TAGS \
            or any(not (isinstance(t, str) and SLUG_RE.fullmatch(t)) for t in tags) \
            or len(set(tags)) != len(tags):
        problems.append(err(path, "'tags' must be <=6 unique lowercase slugs"))

    if "breaking" in art and not isinstance(art["breaking"], bool):
        problems.append(err(path, "'breaking' must be a boolean"))

    sk = art.get("story_key")
    if "story_key" in art and not (isinstance(sk, str) and SLUG_RE.fullmatch(sk)):
        problems.append(err(path, "'story_key' must be a lowercase slug"))

    for lang in ("en", "zh"):
        if lang not in art:
            problems.append(err(path, f"'{lang}' version is required"))
        else:
            problems += validate_localized(lang, art[lang], path)
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="strictly validate original articles without normalizing or writing files")
    args = parser.parse_args(argv)
    now = datetime.now(HKT)
    cutoff = now - timedelta(hours=LIVE_WINDOW_HOURS)

    all_problems = []
    seen_ids = {}
    entries = []
    normalized = []
    pending_writes = []

    for path in sorted(ARTICLES_DIR.glob("*/*.json")):
        expected_date = path.parent.name
        try:
            art, json_note = load_article(path)
        except json.JSONDecodeError as e:
            all_problems.append(err(path, f"invalid JSON: {e}"))
            continue
        if json_note and args.check:
            all_problems.append(err(path, f"invalid JSON (build would repair: {json_note})"))
            continue

        # Normalize only during builds. Hold all rewrites in memory until
        # the entire corpus passes, keeping failed runs read-only.
        if not args.check:
            notes = ([json_note] if json_note else []) + normalize_lengths(art) + normalize_tags(art)
            if notes:
                pending_writes.append((path, json.dumps(art, ensure_ascii=False, indent=2) + "\n"))
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

    if all_problems:
        print("VALIDATION FAILED — no files written:", file=sys.stderr)
        for p in all_problems:
            print("  - " + p, file=sys.stderr)
        return 1

    if args.check:
        print(f"Validated {len(seen_ids)} article(s); no files written.")
        return 0

    for path, content in pending_writes:
        path.write_text(content, encoding="utf-8")
    if normalized:
        print(f"auto-normalized {len(normalized)} field(s):")
        for n in normalized:
            print("  - " + n)

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
