#!/usr/bin/env python3
"""
STUDIO BRITTANY SIGNAL FEED
Pulls every source in sources.json, filters, dedupes, and writes valid RSS 2.0:
  public/all.xml            master feed (everything)
  public/<category>.xml     one feed per topic
  public/sources.opml       every raw source, for importing into any reader
  public/index.html         a tiny landing page listing the feed URLs
"""
import json, os, re, html, hashlib, time, calendar, concurrent.futures as cf
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape
import feedparser

BASE_URL = os.environ.get("FEED_BASE_URL", "https://YOUR-USERNAME.github.io/sb-signal-feed").rstrip("/")
DAYS_BACK = int(os.environ.get("DAYS_BACK", "10"))
MAX_ALL = 400          # cap for the master feed
MAX_PER_CAT = 150      # cap per topic feed
MAX_PER_SOURCE = 15    # stops one firehose source from drowning the rest
UA = "Mozilla/5.0 (compatible; SBSignalFeed/1.0)"

CATEGORIES = {
    "ai":        "AI (labs, models, tools, analysis)",
    "marketing": "Content Marketing + SEO",
    "social":    "Social Media Marketing",
    "creator":   "Creator Economy + Influencer Marketing",
    "design":    "Design, Web Design + Branding",
    "tools":     "Tools, Workflows + Systems",
}

# Broad outlets (TechCrunch social, Digiday, Product Hunt, etc.) only pass an item
# if its title or summary hits one of these. Focused sources pass everything.
KEYWORDS = [
    # AI
    r"\bai\b", "artificial intelligence", "openai", "chatgpt", "gpt", "anthropic", "claude",
    "gemini", "llm", "generative", "genai", "agent", "copilot", "midjourney", "sora",
    "firefly", "perplexity", "machine learning", "automation", "prompt",
    # marketing + content
    "content marketing", "marketing", "seo", "search", "newsletter", "email", "blog",
    "copywriting", "brand", "audience", "funnel", "conversion", "analytics", "algorithm",
    # social + creator
    "social media", "instagram", "tiktok", "threads", "pinterest", "youtube", "linkedin",
    "reels", "shorts", "creator", "influencer", "substack", "podcast", "ugc",
    # design + web
    "design", "branding", "rebrand", "logo", "identity", "typography", "font", "website",
    "web design", "ux", "ui", "figma", "framer", "webflow", "squarespace", "showit",
    # tools + systems
    "notion", "dubsado", "flodesk", "canva", "adobe", "zapier", "make.com", "workflow",
    "productivity", "template", "no-code", "nocode", "integration", "crm", "digital product",
    "etsy", "gumroad", "shopify",
]
KW = re.compile("|".join(k if k.startswith(r"\b") else re.escape(k) for k in KEYWORDS), re.I)
TAG = re.compile(r"<[^>]+>")
SPACE = re.compile(r"\s+")


def clean(text, limit=None):
    text = html.unescape(TAG.sub(" ", text or ""))
    text = SPACE.sub(" ", text).strip()
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "..."
    return text


def fetch(src):
    try:
        d = feedparser.parse(src["url"], agent=UA)
        return src, d.entries, None
    except Exception as e:  # one dead source never breaks the build
        return src, [], str(e)


def build():
    sources = json.load(open("sources.json"))
    items, seen, report = [], set(), []

    with cf.ThreadPoolExecutor(16) as pool:
        results = list(pool.map(fetch, sources))

    for src, entries, err in results:
        kept = 0
        cutoff = time.time() - src.get("days", DAYS_BACK) * 86400
        for e in entries:
            p = e.get("published_parsed") or e.get("updated_parsed")
            if not p:
                continue
            ts = calendar.timegm(p)
            if ts < cutoff or ts > time.time() + 86400:
                continue
            title = clean(e.get("title"))
            link = (e.get("link") or "").strip()
            if not title or not link:
                continue
            summary = clean(e.get("summary") or e.get("description"), 400)
            if src["filter"] == "broad" and not KW.search(f"{title} {summary}"):
                continue
            # Google News titles end in " - Publisher"; dedupe on the bare headline
            key = re.sub(r"\s+-\s+[^-]+$", "", title).lower()[:90]
            if link in seen or key in seen:
                continue
            seen.update({link, key})
            items.append(dict(title=title, link=link, summary=summary, ts=ts,
                              source=src["name"], category=src["category"]))
            kept += 1
            if kept >= MAX_PER_SOURCE:
                break
        report.append((src["name"], kept, err))

    items.sort(key=lambda i: i["ts"], reverse=True)
    os.makedirs("public", exist_ok=True)

    write_rss("all.xml", "Studio Brittany Signal Feed: Everything",
              "AI, content marketing, social, creator economy, design, branding, and the tools that run it all.",
              items[:MAX_ALL])
    for slug, label in CATEGORIES.items():
        write_rss(f"{slug}.xml", f"Studio Brittany Signal Feed: {label}",
                  f"Filtered stream for {label}.",
                  [i for i in items if i["category"] == slug][:MAX_PER_CAT])
    write_opml(sources)
    write_index(items)

    print(f"{len(items)} items from {sum(1 for _, k, _ in report if k)} live sources")
    for name, kept, err in report:
        if err or not kept:
            print(f"  quiet or failed: {name} ({err or 'no recent items'})")


def write_rss(filename, title, desc, items):
    now = format_datetime(datetime.now(timezone.utc))
    self_url = f"{BASE_URL}/{filename}"
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">', "<channel>",
           f"<title>{escape(title)}</title>", f"<link>{escape(BASE_URL)}/</link>",
           f"<description>{escape(desc)}</description>", "<language>en-us</language>",
           f"<lastBuildDate>{now}</lastBuildDate>", "<ttl>180</ttl>",
           f'<atom:link href="{escape(self_url)}" rel="self" type="application/rss+xml"/>']
    for i in items:
        label = CATEGORIES[i["category"]].split(" (")[0].upper()
        body = f'{i["summary"] or "(no summary)"} [via {i["source"]}]'
        guid = hashlib.sha1(i["link"].encode()).hexdigest()
        pub = format_datetime(datetime.fromtimestamp(i["ts"], timezone.utc))
        out += ["<item>",
                f'<title>{escape(i["title"])}</title>',
                f'<link>{escape(i["link"])}</link>',
                f"<description>{escape(body)}</description>",
                f"<pubDate>{pub}</pubDate>",
                f'<guid isPermaLink="false">sb-{guid}</guid>',
                f"<category>{escape(label)}</category>",
                "</item>"]
    out += ["</channel>", "</rss>"]
    open(f"public/{filename}", "w", encoding="utf-8").write("\n".join(out))


def write_opml(sources):
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<opml version="2.0">',
           "<head><title>Studio Brittany Signal Feed Sources</title></head>", "<body>"]
    for slug, label in CATEGORIES.items():
        out.append(f'<outline text="{escape(label)}" title="{escape(label)}">')
        for s in sources:
            if s["category"] == slug:
                a = {"text": s["name"], "title": s["name"], "type": "rss", "xmlUrl": s["url"]}
                out.append("  <outline " + " ".join(f'{k}="{escape(v, {chr(34): "&quot;"})}"' for k, v in a.items()) + "/>")
        out.append("</outline>")
    out += ["</body>", "</opml>"]
    open("public/sources.opml", "w", encoding="utf-8").write("\n".join(out))


def write_index(items):
    rows = "".join(f'<li><code>{BASE_URL}/{s}.xml</code> {escape(l)}</li>' for s, l in
                   [("all", "Everything")] + list(CATEGORIES.items()))
    open("public/index.html", "w", encoding="utf-8").write(
        f"<!doctype html><meta charset=utf-8><title>SB Signal Feed</title>"
        f"<body style='font-family:system-ui;max-width:720px;margin:40px auto;padding:0 16px'>"
        f"<h1>SB SIGNAL FEED</h1><p>{len(items)} items. Updated "
        f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC.</p><ul>{rows}</ul>"
        f"<p><a href='sources.opml'>sources.opml</a></p></body>")


if __name__ == "__main__":
    build()
