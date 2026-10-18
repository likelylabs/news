# likelylabs/news

AI-written Hong Kong news that the radio app renders as a native newsreader
(with native ads inserted between paragraphs). **Public GitHub Pages site**
at `https://news.likelylabs.com` — the apps fetch `/index.json` and article
JSON directly; `/archive/` is the human-readable archive of everything
older than the 72h live window.

Ecosystem map and operating tenets: `~/localdev/radioapp-hq/CLAUDE.md`.

## How it works

```
 9 scheduled automations             GitHub Action (this repo)          the app
 (Grok, web/X + GitHub connector)     build-index.yml                    news section
 ───────────────────────────────     ─────────────────────────────      ───────────────
 read ledger.json  ─── dedup         on push:                           GET index.json
 search latest HK news               • prune.py  (ledger trim)          → list view
 write articles/<date>/<id>.json     • build_index.py (validate +       GET articles/<…>.json
 append ledger.json                    regenerate index.json)           → article + native ads
 commit  ───────────────────────►    • commit index back  ──────────►  (shows "AI-generated")
```

The automation writes **articles + ledger** (its strength: research and
prose). The Action owns **index.json + the ledger trim** (deterministic
structure). They never overlap — that's the "one sanctioned write path"
tenet applied to news. Article files are permanent — never deleted.

## Files

| Path | What it is |
|------|-----------|
| `GROK.md` | The full editorial brief the automation follows. |
| `AUTOMATION.md` | How the scheduled runs are set up + the paste-ready prompt. |
| `TIDINESS.md` | File-hygiene rules (naming, dedup, retention, corrections). |
| `schema/article.schema.json` | The contract every article must match. |
| `schema/example-article.json` | Illustrative sample article (not a live story). |
| `index.json` | Machine-generated manifest the app reads first. Do not hand-edit. |
| `ledger.json` | Dedup memory — which stories have been covered. |
| `articles/<date>/<id>.json` | The articles. |
| `tools/build_index.py` | Validates articles + rebuilds `index.json`. |
| `tools/prune.py` | Trims old ledger keys (article files are never deleted). |
| `tools/build_archive.py` | Renders the `/archive/` HTML site at deploy time (output never committed). |

## App integration (contract)

1. **Auth.** None — the content is public GitHub Pages at
   `https://news.likelylabs.com`; the apps fetch it directly.
2. **List.** `GET .../index.json` → newest-first array of
   `{ id, published_at, category, tags, breaking, path, en:{headline,dek}, zh:{headline,dek} }`.
   Render the list from this; it's small.
3. **Detail.** On tap, `GET .../<path>` for the full article. `body` is an
   array of paragraphs — insert native ads between them.
4. **Disclosure (required).** Every article has `ai_generated: true`. The app
   **must** visibly disclose that these articles are AI-generated (App/Play
   policy + honesty). Show `updated_at` as "Corrected" when present.
5. **Language.** Show `en` or `zh` per the app's locale. `zh` is Hong Kong
   Traditional Chinese.
6. **Push.** A news notification's tap carries `action: news` +
   `article_id` (and `article_path`); open that article. See
   [Push notifications](#push-notifications).

## Push notifications

Nothing in this repo sends push notifications, and nothing here holds a
key, token, service account or Actions secret for them. The repo is public,
and it stays that way. The sender is the radio app's weather Worker: every 5
minutes it pulls the published `index.json`, compares article ids with the
ones it has already seen, and sends **at most one notification per new
batch it finds**. A newsroom run lands as one commit, so that is normally one
per run:

- to readers subscribed to **breaking news** (on by default), only when the
  run contains an article flagged `breaking: true`;
- to readers who opted into **every update**, one per run.

A notification is the article's `headline` (title) and `dek` (text), in
English or Hong Kong Chinese (`zh`) by the reader's language, and a tap
opens that article (`action: news` + `article_id` in the data payload). It
only ever points at an article already live in `index.json`. Nothing is sent
23:00–07:00 HKT, and a daily cap applies. Editorial rules for the flag and
for lock-screen copy: `GROK.md` §1c. Sender, topics and policy:
`~/localdev/radioapp-hq/PUSH-TOPICS.md`.

## Local dev

```bash
python3 tools/build_index.py --check   # strict preflight; never writes files
python3 -m unittest discover -s tests -v   # publishing regression suite
python3 tools/build_index.py   # validate all articles + rebuild index.json
python3 tools/prune.py --dry-run   # preview which ledger keys would be trimmed
python3 tools/build_archive.py --out /tmp/archive-preview   # render the /archive/ site
```
All are stdlib-only (no dependencies).

The builder repairs safe ASCII tag formatting, deduplicates/caps tags, and
trims overlong display fields before validating. Unrepairable articles still
fail publication; source repairs are written only after the entire corpus
passes. See `TIDINESS.md`. Pull requests run the tests and read-only preflight;
every main index build runs the regression suite before publishing.
