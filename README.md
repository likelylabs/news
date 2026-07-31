# likelylabs/news

AI-written Hong Kong news that the radio app renders as a native newsreader
(with native ads inserted between paragraphs). **Private repo** — the
content is fetched by the app with a read-only token, never served publicly.

Ecosystem map and operating tenets: `~/localdev/radioapp-hq/CLAUDE.md`.

## How it works

```
 9 scheduled automations             GitHub Action (this repo)          the app
 (Grok, web/X + GitHub connector)     build-index.yml                    news section
 ───────────────────────────────     ─────────────────────────────      ───────────────
 read ledger.json  ─── dedup         on push:                           GET index.json
 search latest HK news               • prune.py  (retention)            → list view
 write articles/<date>/<id>.json     • build_index.py (validate +       GET articles/<…>.json
 append ledger.json                    regenerate index.json)           → article + native ads
 commit  ───────────────────────►    • commit index back  ──────────►  (shows "AI-generated")
```

The automation writes **articles + ledger** (its strength: research and
prose). The Action owns **index.json + retention** (deterministic
structure). They never overlap — that's the "one sanctioned write path"
tenet applied to news.

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
| `tools/prune.py` | Deletes old articles + trims the ledger. |

## App integration (contract)

1. **Auth.** Mint a **fine-grained personal access token** scoped to *only*
   this repo with **Contents: Read-only**. Store it app-side / behind Remote
   Config — **never commit it here** (tenet #10). Fetch with
   `Authorization: Bearer <token>`.
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

## Local dev

```bash
python3 tools/build_index.py   # validate all articles + rebuild index.json
python3 tools/prune.py --dry-run   # preview what retention would remove
```
Both are stdlib-only (no dependencies).
