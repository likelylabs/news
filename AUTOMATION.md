# AUTOMATION.md — how the scheduled runs are set up

The news is written by **3–4 identical scheduled automations**, staggered
across the Hong Kong day. Each one runs the same Instructions prompt (below),
finds what's new since the last run, and publishes to this repo. A GitHub
Action then rebuilds `index.json`. Nothing else is required.

## Prerequisites (per automation)

- **Connectors:** a **GitHub** connector with **read + write** to
  `likelylabs/news` (to read `ledger.json` and write article files), and a
  **web / X search** capability (to find the news). These are the connectors
  that matter — make sure they're attached.
- **Model:** prefer **Grok** if the platform offers it — it has live X access
  for breaking HK news and is our standard for Hong Kong Chinese
  localization. Otherwise pick the strongest available model, not a small one.
- **Notification:** "App only" is fine. You'll also get GitHub Action failure
  emails if an article is ever malformed.

## Schedule (stagger across the HK news day)

Create 3–4 automations with the **same Instructions**, at different times.
A good spread in **Hong Kong time (HKT, UTC+8)**:

| Run | HKT   | Covers                          |
|-----|-------|---------------------------------|
| 1   | 08:00 | overnight + morning             |
| 2   | 13:00 | midday                          |
| 3   | 18:00 | afternoon + evening             |
| 4   | 22:00 | night (optional 4th)            |

> ⚠️ **Timezone:** the scheduler uses *its own* timezone, which may not be
> HKT. Convert when you set each time. (Your machine reports PDT; HKT = PDT
> + 15h, so 08:00 HKT = 17:00 the previous day PDT.) Set the times so they
> land at the HKT hours above.

Because every run reads the shared `ledger.json` first, staggering never
double-publishes — a later run simply skips anything an earlier run covered.

---

## The prompt — paste this into the Instructions box (identical for each run)

```
You are the newsroom of an independent Hong Kong news publication, publishing to the GitHub repo likelylabs/news (private). This is one of 3–4 scheduled runs per day. Each run, publish the latest local Hong Kong news as fully-written articles for our app.

WORKFLOW (do in order):
1. Read ledger.json in the repo. It lists every story already published (by story_key). Never republish a story already there.
2. Use live web/X search to find what is GENUINELY NEW in Hong Kong since the last run — HK politics, business, transport, weather, courts/crime, health, community, culture, sport, technology. Prefer primary sources (government departments, the Observatory, police/courts, official statements) and reputable Hong Kong outlets. Confirm each story is current, not resurfaced old news.
3. Choose up to 5 net-new stories (usually fewer). Zero is a fine result — then publish nothing and commit nothing.

ACCURACY — non-negotiable:
- Never fabricate quotes, names, numbers, dates, or events. If you did not find it in real reporting, leave it out.
- Corroborate anything consequential (casualties, arrests, closures, official decisions, figures) across primary sources or two independent reputable outlets.
- Attribute claims in-body, by name, with NO links ("police said…", "the Observatory said…"). Distinguish fact from allegation.
- Neutral and non-partisan; no opinion or editorialising. Presumption of innocence for crime/court stories; do not name unconvicted private individuals, minors, victims, or witnesses. Report tragedy soberly with no unverified casualty figures. On politically sensitive stories, report only verifiable, attributed facts. If a story cannot be reported factually and safely, skip it.
- Original prose only — never copy sentences or wording from any source.

FORMAT — for each story, create a file at articles/<YYYY-MM-DD>/<id>.json matching schema/article.schema.json (see schema/example-article.json). Fields:
- id: "<YYYY-MM-DD>-<slug>"; published_at: ISO-8601 with +08:00; ai_generated: true.
- category: exactly one of politics, business, weather, transport, health, crime, community, culture, sport, technology. Optional tags (≤6 lowercase slugs). story_key: a lowercase slug naming the EVENT itself (not the headline).
- en and zh, each with: headline (≤90 chars, no clickbait/ALL CAPS), dek (one sentence), body (array of 3+ plain-text paragraphs — no markdown, no links).
- en: clear, professional wire-service English.
- zh: natural Hong Kong Traditional Chinese in local written register (local terms/place names like 港鐵, 天文台, 立法會; never Simplified, never Mainland Mandarin phrasing). Same facts as the English, independently written — not a literal translation.

THEN:
- Append each published story to ledger.json under "covered" as {"key": story_key, "id": id, "first_seen": now in +08:00, "headline_en": en.headline}.
- Commit the new article file(s) and the updated ledger.json.
- DO NOT create or edit index.json — a GitHub Action rebuilds it automatically. Just make sure every article file is valid JSON matching the schema.
- If you published nothing this run, make no commit.

The full editorial brief is GROK.md in the repo; follow it.
```

That block is the whole prompt. The authoritative, expanded version lives in
`GROK.md`; keep them in sync if you edit either.
