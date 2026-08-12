#!/usr/bin/env python3
"""
Render the public /archive/ website: static HTML for every article older
than the 72h live window (the complement of index.json, so between the two
every article is reachable).

Runs at DEPLOY time (pages-deploy.yml), writing into the Pages artifact —
output is never committed. Article files are permanent (see tools/prune.py);
this is how humans read the old ones.

Output layout under --out:
    index.html            month list + most recently archived articles
    <YYYY-MM>/index.html  one month, headlines grouped by day
    <id>.html             one article (id already embeds the date)

Stdlib only:  python3 tools/build_archive.py --out _site/archive
              python3 tools/build_archive.py --out /tmp/a --now 2026-08-12T12:00:00+08:00
"""
import argparse
import html
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ARTICLES_DIR = REPO / "articles"

# Must match tools/build_index.py — the archive starts exactly where the
# live index stops.
LIVE_WINDOW_HOURS = 72
HKT = timezone(timedelta(hours=8))

# How many of the newest archived articles to show on the archive front page.
FRONT_PAGE_RECENT = 20

# Closed category set (tools/build_index.py CATEGORIES) with display labels.
# Raw-slug fallback at lookup time so a future category never crashes a deploy.
CATEGORY_LABELS = {
    "politics":   ("Politics", "政治"),
    "business":   ("Business", "財經"),
    "weather":    ("Weather", "天氣"),
    "transport":  ("Transport", "交通"),
    "health":     ("Health", "健康"),
    "crime":      ("Crime", "罪案"),
    "community":  ("Community", "社區"),
    "culture":    ("Culture", "文化"),
    "sport":      ("Sport", "體育"),
    "technology": ("Technology", "科技"),
}

MONTH_NAMES_EN = ["January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November", "December"]

SITE_NAME_EN = "Hong Kong News Archive"
SITE_NAME_ZH = "香港新聞檔案"

CSS = """
:root { color-scheme: light dark;
  --bg:#ffffff; --fg:#1a1a1a; --muted:#6b6b6b; --line:#e4e4e4;
  --accent:#0a66c2; --badge:#c0392b; --chip:#f0f0f0; }
@media (prefers-color-scheme: dark) { :root {
  --bg:#121212; --fg:#e8e8e8; --muted:#9a9a9a; --line:#2c2c2c;
  --accent:#6ab0f3; --badge:#e57368; --chip:#222222; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
  font:17px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:42rem; margin:0 auto; padding:0 1.25rem 3rem; }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }
header.site { max-width:42rem; margin:0 auto; padding:1rem 1.25rem;
  display:flex; align-items:center; justify-content:space-between; gap:1rem; }
header.site .brand { font-weight:700; font-size:1rem; color:var(--fg); }
#langbtn { border:1px solid var(--line); background:var(--chip); color:var(--fg);
  border-radius:999px; padding:.3rem .9rem; font-size:.85rem; cursor:pointer; }
h1 { font-size:1.55rem; line-height:1.3; margin:1rem 0 .5rem; }
h2 { font-size:1.05rem; margin:2rem 0 .6rem; color:var(--muted);
  text-transform:uppercase; letter-spacing:.04em; }
.meta { color:var(--muted); font-size:.85rem; margin:.2rem 0 1rem; }
.meta .badge { color:var(--badge); font-weight:700; }
.dek { font-size:1.05rem; color:var(--muted); margin:0 0 1.2rem; }
.disclosure { font-size:.8rem; color:var(--muted); border-left:3px solid var(--line);
  padding-left:.75rem; margin:1.5rem 0; }
.updated { font-size:.85rem; color:var(--badge); margin:.5rem 0 1rem; }
ul.items { list-style:none; margin:0; padding:0; }
ul.items li { padding:.55rem 0; border-bottom:1px solid var(--line); }
ul.items .when { color:var(--muted); font-size:.8rem; margin-right:.5rem; }
ul.items .cat { color:var(--muted); font-size:.8rem; margin-left:.5rem; }
ul.items .badge { color:var(--badge); font-size:.8rem; font-weight:700; margin-left:.5rem; }
ul.items .dek { font-size:.9rem; margin:.15rem 0 0; }
ul.months { list-style:none; margin:0; padding:0; }
ul.months li { padding:.5rem 0; border-bottom:1px solid var(--line);
  display:flex; justify-content:space-between; }
ul.months .n { color:var(--muted); font-size:.9rem; }
footer.site { max-width:42rem; margin:0 auto; padding:2rem 1.25rem;
  color:var(--muted); font-size:.85rem; border-top:1px solid var(--line); }
article p { margin:0 0 1rem; }
[data-lang="en"] .l-zh { display:none; }
[data-lang="zh"] .l-en { display:none; }
"""

# Runs before paint: pick language from localStorage, else browser locale.
LANG_JS = """
(function(){
  var l;
  try { l = localStorage.getItem("lang"); } catch (e) {}
  if (l !== "en" && l !== "zh") {
    l = (navigator.language || "").toLowerCase().indexOf("zh") === 0 ? "zh" : "en";
  }
  document.documentElement.dataset.lang = l;
})();
function toggleLang(){
  var l = document.documentElement.dataset.lang === "zh" ? "en" : "zh";
  document.documentElement.dataset.lang = l;
  try { localStorage.setItem("lang", l); } catch (e) {}
}
"""


def esc(s):
    return html.escape(str(s), quote=True)


def bi(en_text, zh_text, tag="span", cls=""):
    """One logical string, both languages, one visible at a time."""
    extra = f" {cls}" if cls else ""
    return (f'<{tag} class="l-en{extra}" lang="en">{esc(en_text)}</{tag}>'
            f'<{tag} class="l-zh{extra}" lang="zh-Hant-HK">{esc(zh_text)}</{tag}>')


def category_label(slug):
    return CATEGORY_LABELS.get(slug, (slug, slug))


def month_label(ym):
    y, m = ym.split("-")
    en = f"{MONTH_NAMES_EN[int(m) - 1]} {y}"
    zh = f"{y}年{int(m)}月"
    return en, zh


def day_label(d):
    en = f"{d.day} {MONTH_NAMES_EN[d.month - 1]} {d.year}"
    zh = f"{d.year}年{d.month}月{d.day}日"
    return en, zh


def page(title_en, title_zh, body_html, root=""):
    """Shared shell. `root` is the relative prefix back to the archive root."""
    return f"""<!DOCTYPE html>
<html lang="en" data-lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title_en)} · {esc(SITE_NAME_EN)}</title>
<style>{CSS}</style>
<script>{LANG_JS}</script>
</head>
<body>
<header class="site">
  <a class="brand" href="{root}./">{bi(SITE_NAME_EN, SITE_NAME_ZH)}</a>
  <button id="langbtn" onclick="toggleLang()">{bi("中文", "EN")}</button>
</header>
<main>
{body_html}
</main>
<footer class="site">{bi(
    "All articles are AI-generated summaries of publicly reported Hong Kong news.",
    "所有文章均由人工智能根據公開報導的香港新聞生成。")}</footer>
</body>
</html>
"""


def load_articles(now):
    """Return (archived articles newest-first, warning count)."""
    cutoff = now - timedelta(hours=LIVE_WINDOW_HOURS)
    items, warnings = [], 0
    seen = {}
    for path in sorted(ARTICLES_DIR.glob("*/*.json")):
        try:
            art = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"WARNING: skipping unreadable {path.name}: {e}", file=sys.stderr)
            warnings += 1
            continue
        art_id = art.get("id") or path.stem
        try:
            pub = datetime.fromisoformat(art["published_at"])
        except (KeyError, TypeError, ValueError):
            # Fall back to the date baked into the id/folder (noon HKT).
            try:
                pub = datetime.strptime(art_id[:10], "%Y-%m-%d").replace(
                    hour=12, tzinfo=HKT)
                print(f"WARNING: {path.name}: bad published_at, using id date",
                      file=sys.stderr)
                warnings += 1
            except ValueError:
                print(f"WARNING: skipping {path.name}: no usable date",
                      file=sys.stderr)
                warnings += 1
                continue
        if pub >= cutoff:
            continue  # still in the live index window
        if art_id in seen:
            print(f"WARNING: duplicate id {art_id}; keeping {path}", file=sys.stderr)
            warnings += 1
        seen[art_id] = (pub, art)
    items = [(pub, art_id, art) for art_id, (pub, art) in seen.items()]
    items.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return items, warnings


def lang_block(art, lang):
    d = art.get(lang) or {}
    return d.get("headline", ""), d.get("dek", ""), d.get("body", [])


def item_li(pub, art_id, art, with_dek=False):
    cat_en, cat_zh = category_label(art.get("category", ""))
    h_en, dek_en, _ = lang_block(art, "en")
    h_zh, dek_zh, _ = lang_block(art, "zh")
    badge = f'<span class="badge">{bi("Breaking", "突發")}</span>' if art.get("breaking") else ""
    dek = f'<p class="dek">{bi(dek_en, dek_zh)}</p>' if with_dek else ""
    return (f'<li><span class="when">{pub.strftime("%H:%M")}</span>'
            f'<a href="{esc(art_id)}.html">{bi(h_en, h_zh)}</a>'
            f'<span class="cat">{bi(cat_en, cat_zh)}</span>{badge}{dek}</li>')


def render_article(pub, art_id, art):
    cat_en, cat_zh = category_label(art.get("category", ""))
    h_en, dek_en, body_en = lang_block(art, "en")
    h_zh, dek_zh, body_zh = lang_block(art, "zh")
    d_en, d_zh = day_label(pub.date())
    when = pub.strftime("%H:%M")
    ym = art_id[:7]
    m_en, m_zh = month_label(ym)

    badge = f' · <span class="badge">{bi("Breaking", "突發")}</span>' if art.get("breaking") else ""
    updated = ""
    upd = art.get("updated_at")
    if upd:
        try:
            ud = datetime.fromisoformat(upd)
            u_en, u_zh = day_label(ud.date())
            updated = (f'<p class="updated">{bi("Updated " + u_en, "更新於" + u_zh)}</p>')
        except (TypeError, ValueError):
            pass

    paras_en = "".join(f"<p>{esc(p)}</p>" for p in body_en)
    paras_zh = "".join(f"<p>{esc(p)}</p>" for p in body_zh)
    body_html = f"""
<article>
  <h1>{bi(h_en, h_zh)}</h1>
  <p class="meta">{bi(d_en, d_zh)} {when} · {bi(cat_en, cat_zh)}{badge}</p>
  {updated}
  <p class="dek">{bi(dek_en, dek_zh)}</p>
  <div class="l-en" lang="en">{paras_en}</div>
  <div class="l-zh" lang="zh-Hant-HK">{paras_zh}</div>
  <p class="disclosure">{bi(
      "This article was generated by AI from public news sources.",
      "本文由人工智能根據公開新聞來源生成。")}</p>
  <p><a href="{ym}/">{bi("← " + m_en, "← " + m_zh)}</a> ·
     <a href="./">{bi("Archive home", "檔案首頁")}</a></p>
</article>"""
    return page(h_en, h_zh, body_html)


def render_month(ym, month_items):
    m_en, m_zh = month_label(ym)
    parts = [f"<h1>{bi(m_en, m_zh)}</h1>"]
    current_day = None
    for pub, art_id, art in month_items:  # already newest-first
        day = pub.date()
        if day != current_day:
            if current_day is not None:
                parts.append("</ul>")
            d_en, d_zh = day_label(day)
            parts.append(f"<h2>{bi(d_en, d_zh)}</h2><ul class=\"items\">")
            current_day = day
        li = item_li(pub, art_id, art)
        # Month pages live one level down; article links need a ../ prefix.
        parts.append(li.replace(f'href="{esc(art_id)}.html"',
                                f'href="../{esc(art_id)}.html"', 1))
    if current_day is not None:
        parts.append("</ul>")
    parts.append(f'<p style="margin-top:2rem"><a href="../">{bi("← Archive home", "← 檔案首頁")}</a></p>')
    return page(m_en, m_zh, "\n".join(parts), root="../")


def render_index(items, months):
    parts = [f"<h1>{bi(SITE_NAME_EN, SITE_NAME_ZH)}</h1>",
             f'<p class="meta">{bi("Articles older than 3 days, kept forever.", "三天前的舊聞，永久保存。")}</p>']
    if not items:
        parts.append(f"<p>{bi('No archived articles yet.', '暫時未有已存檔的文章。')}</p>")
        return page("Archive", "檔案", "\n".join(parts))
    parts.append(f"<h2>{bi('Recently archived', '最近存檔')}</h2><ul class=\"items\">")
    for pub, art_id, art in items[:FRONT_PAGE_RECENT]:
        parts.append(item_li(pub, art_id, art, with_dek=True))
    parts.append("</ul>")
    parts.append(f"<h2>{bi('By month', '按月瀏覽')}</h2><ul class=\"months\">")
    for ym in sorted(months, reverse=True):
        m_en, m_zh = month_label(ym)
        n = len(months[ym])
        parts.append(f'<li><a href="{ym}/">{bi(m_en, m_zh)}</a>'
                     f'<span class="n">{n}</span></li>')
    parts.append("</ul>")
    return page("Archive", "檔案", "\n".join(parts))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="output directory (created if missing)")
    ap.add_argument("--now", help="ISO override of 'now' for testing")
    args = ap.parse_args()

    now = datetime.fromisoformat(args.now) if args.now else datetime.now(HKT)
    if now.tzinfo is None:
        now = now.replace(tzinfo=HKT)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    items, warnings = load_articles(now)

    months = {}
    for pub, art_id, art in items:
        months.setdefault(art_id[:7], []).append((pub, art_id, art))

    out.joinpath("index.html").write_text(render_index(items, months), encoding="utf-8")
    for ym, month_items in months.items():
        mdir = out / ym
        mdir.mkdir(exist_ok=True)
        mdir.joinpath("index.html").write_text(render_month(ym, month_items), encoding="utf-8")
    for pub, art_id, art in items:
        out.joinpath(f"{art_id}.html").write_text(render_article(pub, art_id, art), encoding="utf-8")

    print(f"archive: {len(items)} article(s), {len(months)} month(s), {warnings} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
