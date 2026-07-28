# TIDINESS.md — keeping the news repo clean

The repo has to stay tidy on its own, because it's written by an automation
several times a day, forever. These are the rules that keep it from turning
into a junk drawer. The automation follows them; the GitHub Action enforces
the structural ones.

## Layout & naming

```
articles/<YYYY-MM-DD>/<id>.json     one article, both languages
ledger.json                         dedup record (what's been covered)
index.json                          MACHINE-GENERATED manifest the app reads
schema/article.schema.json          the contract every article must match
schema/example-article.json         an illustrative sample (not a live story)
```

- **`id` = `<YYYY-MM-DD>-<slug>`.** Date is the publish date (HKT). Slug is
  lowercase, hyphenated, descriptive: `2026-07-27-typhoon-signal-8`.
- **Filename equals the id** (`<id>.json`) and lives in the folder for its
  date. The Action rejects any file that breaks this.
- **`id` is unique and permanent.** Never reuse a slug; never rename a file
  after it's published.

## The ledger is the dedup memory — always read it first

- Before writing anything, read `ledger.json`. Every past story is listed
  under `covered` with a `story_key`.
- `story_key` names the **event**, not the headline wording — so the same
  event written two different ways still collides. If a candidate's key is
  already in the ledger, **skip it.**
- After publishing, append `{ "key", "id", "first_seen", "headline_en" }`.
- Old keys age out automatically (5-day retention) — don't prune by hand.

## index.json is generated — never hand-edit it

`index.json` is rebuilt from the article files by `tools/build_index.py`,
run by the GitHub Action on every push. The automation must **not** create
or edit it. Hand-editing it is the one sure way to desync the app from
reality (tenet #5). If it ever looks wrong, re-run the Action — don't patch
the file.

## Retention is automatic

`tools/prune.py` (also run by the Action) deletes article files older than
**14 days** and trims ledger keys older than **5 days**. Git history is the
permanent archive, so nothing is truly lost. Don't delete articles manually
to "clean up" — let prune do it, and never delete a live article to hide a
mistake.

## Articles are immutable except for corrections

Once published, an article's `id` and `published_at` never change. To fix a
factual error: edit the same file, correct the fact, set `updated_at` to now
(`+08:00`), and add a final `Correction: …` paragraph to the body. That's
the only reason to touch a published file.

## Per-run checklist (what a clean run looks like)

1. Read `ledger.json` (and skim `index.json` for what's live).
2. Find genuinely new stories; assign each a `story_key`; drop any already
   in the ledger.
3. Verify facts (see GROK.md §3). Drop anything shaky.
4. Write ≤5 valid article files to `articles/<date>/`.
5. Append each to `ledger.json`.
6. Commit article files + ledger.json — **not** index.json.
7. Nothing new? Commit nothing. No empty commits, no "no news today" placeholders.

## Commit convention

- New articles: `news: <n> article(s) — <short topic list>`
  e.g. `news: 2 articles — typhoon signal 8, hang seng close`
- Correction: `fix: correction to <id>`
- The Action's own commits: `chore(index): rebuild index + prune [skip ci]`
  (leave these to the bot).

## Size sanity

- ≤ 5 articles per run.
- Headlines ≤ 90 chars; body ≥ 2 paragraphs (aim 3+ for ad placement).
- Plain text only in bodies — no markdown, no HTML, no URLs.
