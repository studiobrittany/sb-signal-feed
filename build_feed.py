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
    def dedupe_summary(i):
        head = re.sub(r"\s+-\s+[^-]+$", "", i["title"]).lower()[:60]
        return "" if i["summary"].lower().startswith(head) else i["summary"]
    data = [dict(t=i["title"], l=i["link"], s=dedupe_summary(i), ts=i["ts"], src=i["source"], c=i["category"])
            for i in items]
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    cats = json.dumps({k: v.split(" (")[0] for k, v in CATEGORIES.items()})
    built = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    page = INDEX_TEMPLATE.replace("__DATA__", payload).replace("__CATS__", cats) \
                         .replace("__BUILT__", built).replace("__BASE__", BASE_URL)
    open("public/index.html", "w", encoding="utf-8").write(page)


INDEX_TEMPLATE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SB Signal Feed</title>
<link rel="alternate" type="application/rss+xml" title="SB Signal Feed" href="all.xml">
<style>
:root{--bg:#f6f4ef;--card:#fff;--ink:#16151a;--mute:#6b6873;--line:#e4e0d8;--accent:#e8344e;--chip:#efece6}
@media (prefers-color-scheme:dark){:root{--bg:#121116;--card:#1b1a20;--ink:#f1eff4;--mute:#9b98a3;--line:#2c2a33;--accent:#ff5a72;--chip:#26242c}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,system-ui,sans-serif}
.wrap{max-width:860px;margin:0 auto;padding:0 16px 80px}
header{padding:36px 0 16px}
h1{font-size:28px;letter-spacing:.06em;margin:0}
.meta{color:var(--mute);font-size:13px;margin-top:6px}
.bar{position:sticky;top:0;z-index:5;background:var(--bg);padding:12px 0;border-bottom:1px solid var(--line)}
.tabs{display:flex;gap:6px;overflow-x:auto;padding-bottom:8px;scrollbar-width:none}
.tabs button{flex:none;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;padding:6px 12px;font:600 12px/1 inherit;letter-spacing:.06em;text-transform:uppercase;cursor:pointer}
.tabs button[aria-pressed=true]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.tabs span{opacity:.6;margin-left:4px;font-weight:500}
input{width:100%;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:10px;padding:10px 12px;font:inherit}
h2{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--mute);margin:28px 0 8px}
.item{display:block;text-decoration:none;color:inherit;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:8px 0}
.item:hover{border-color:var(--accent)}
.item h3{font-size:16px;margin:0 0 4px;line-height:1.35}
.item p{margin:0 0 8px;color:var(--mute);font-size:14px}
.row{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:12px;color:var(--mute)}
.chip{background:var(--chip);border-radius:6px;padding:2px 7px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;font-size:11px}
.new{color:var(--accent);font-weight:700;letter-spacing:.06em}
.empty{color:var(--mute);text-align:center;padding:40px 0}
footer{color:var(--mute);font-size:12px;margin-top:40px;word-break:break-all}
footer a{color:inherit}
</style></head><body><div class="wrap">
<header><h1>SB SIGNAL FEED</h1><div class="meta" id="meta"></div></header>
<div class="bar"><div class="tabs" id="tabs"></div><input id="q" type="search" placeholder="search titles, summaries, sources"></div>
<main id="list"></main>
<footer>RSS: <a href="all.xml">__BASE__/all.xml</a> &middot; topic feeds: ai, marketing, social, creator, design, tools (.xml) &middot; <a href="sources.opml">sources.opml</a></footer>
</div>
<script>
const DATA=__DATA__, CATS=__CATS__, BUILT=new Date("__BUILT__");
let cat="all", q="", lastVisit=0;
try{lastVisit=+localStorage.getItem("sbLastVisit")||0;localStorage.setItem("sbLastVisit",Date.now())}catch(e){}
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const dayKey=ts=>{const d=new Date(ts*1000),t=new Date();t.setHours(0,0,0,0);const y=new Date(t);y.setDate(t.getDate()-1);
 if(d>=t)return"Today";if(d>=y)return"Yesterday";return d.toLocaleDateString(undefined,{weekday:"long",month:"short",day:"numeric"})};
document.getElementById("meta").textContent=DATA.length+" articles · updated "+BUILT.toLocaleString(undefined,{month:"short",day:"numeric",hour:"numeric",minute:"2-digit"});
function tabs(){const counts={all:DATA.length};DATA.forEach(i=>counts[i.c]=(counts[i.c]||0)+1);
 document.getElementById("tabs").innerHTML=[["all","Everything"],...Object.entries(CATS)].map(([k,v])=>
 `<button data-c="${k}" aria-pressed="${k===cat}">${esc(v)}<span>${counts[k]||0}</span></button>`).join("")}
function render(){const ql=q.toLowerCase();
 const rows=DATA.filter(i=>(cat==="all"||i.c===cat)&&(!ql||(i.t+" "+i.s+" "+i.src).toLowerCase().includes(ql)));
 if(!rows.length){document.getElementById("list").innerHTML='<div class="empty">nothing here. suspicious.</div>';return}
 let html="",cur="";
 rows.forEach(i=>{const k=dayKey(i.ts);if(k!==cur){html+=`<h2>${k}</h2>`;cur=k}
  const isNew=lastVisit&&i.ts*1000>lastVisit;
  html+=`<a class="item" href="${esc(i.l)}" target="_blank" rel="noopener"><h3>${esc(i.t)}</h3>${i.s?`<p>${esc(i.s)}</p>`:""}
  <div class="row"><span class="chip">${esc(CATS[i.c])}</span><span>${esc(i.src.replace("Google News: ",""))}</span>
  <span>${new Date(i.ts*1000).toLocaleTimeString(undefined,{hour:"numeric",minute:"2-digit"})}</span>${isNew?'<span class="new">NEW</span>':""}</div></a>`});
 document.getElementById("list").innerHTML=html}
document.getElementById("tabs").addEventListener("click",e=>{const b=e.target.closest("button");if(!b)return;cat=b.dataset.c;tabs();render();window.scrollTo(0,0)});
document.getElementById("q").addEventListener("input",e=>{q=e.target.value;render()});
tabs();render();
</script></body></html>"""


if __name__ == "__main__":
    build()
