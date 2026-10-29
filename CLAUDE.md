# likelylabs/news

**Public** (GitHub Pages at `news.likelylabs.com`). AI-written Hong Kong news
that the radio app renders as a native newsreader (with native ads); articles
older than the 72h live window are served at `/archive/`. Read
`~/localdev/radioapp-hq/CLAUDE.md` for the ecosystem map and the eleven
tenets before changing anything.

## Pipeline

- **Write path:** 9 scheduled **Grok** automations (web/X + GitHub
  connector) write `articles/<date>/<id>.json` only. The
  brief is `GROK.md`; the paste-in prompt and schedule are in `AUTOMATION.md`.
- **Enforce path:** the `build-index` GitHub Action validates every article,
  rebuilds `ledger.json` from the articles (14-day window), and regenerates
  `index.json`. Article files are permanent
  — never deleted. Rules in `TIDINESS.md`.
- **Push path:** none in this repo. The radio app's weather Worker pulls the
  published `index.json` every 5 minutes and sends at most one notification
  per new batch; `breaking: true` now pushes to readers' phones (rules in
  `GROK.md` §1c, summary in README "Push notifications"). Never add a send
  step, a token or an Actions secret here.

## Non-negotiables

- **`index.json` is machine-generated — never hand-edit it** (tenet #5).
- **No secrets in the repo** (tenet #10). The content is public; nothing
  here should ever need a token.
- Every article carries `ai_generated: true`; the **app must disclose** the
  content is AI-generated (the `/archive/` pages carry their own disclosure).
- This repo is PUBLIC and app-facing — no internal strategy, analytics, or
  business notes. Those live in `radioapp-hq`.
