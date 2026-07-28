# likelylabs/news

**Private.** AI-written Hong Kong news that the radio app renders as a native
newsreader (with native ads). Read `~/localdev/radioapp-hq/CLAUDE.md` for the
ecosystem map and the eleven tenets before changing anything.

## Pipeline

- **Write path:** 3–4 scheduled **Grok** automations (web/X + GitHub
  connector) write `articles/<date>/<id>.json` + append `ledger.json`. The
  brief is `GROK.md`; the paste-in prompt and schedule are in `AUTOMATION.md`.
- **Enforce path:** the `build-index` GitHub Action validates every article,
  prunes old ones, and regenerates `index.json`. Rules in `TIDINESS.md`.

## Non-negotiables

- **`index.json` is machine-generated — never hand-edit it** (tenet #5).
- **No secrets in the repo** (tenet #10). The app's read-only token lives
  behind Remote Config, not here.
- Every article carries `ai_generated: true`; the **app must disclose** the
  content is AI-generated.
- This repo is PRIVATE and app-facing — no internal strategy, analytics, or
  business notes. Those live in `radioapp-hq`.
