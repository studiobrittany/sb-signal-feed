# SB SIGNAL FEED

Self-updating RSS feed: AI, content marketing, social, creator economy + influencer marketing, design + branding, and tools (Notion, Dubsado, Flodesk, Canva, Adobe, Zapier, Showit, Squarespace).

- `sources.json` = every source. Add one by copying an entry. `"filter": "broad"` means keyword-filtered; `"all"` means keep everything; `"days"` overrides how far back it looks.
- `build_feed.py` = the builder. Edit `KEYWORDS` to change what broad sources let through.
- GitHub Actions rebuilds every 3 hours and publishes to GitHub Pages.

Feeds (after setup): `all.xml`, `ai.xml`, `marketing.xml`, `social.xml`, `creator.xml`, `design.xml`, `tools.xml`, plus `sources.opml`.
