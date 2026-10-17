# Kawthar — living library

Data for the Kawthar app's Listen tab: latmiyat, nauha, majalis, lectures,
recited duas and live shrine streams, gathered automatically.

- `sources.json` — verified official YouTube channels, podcast feeds and
  licensed Internet Archive items (seeded from `Kawthar/Tools/data/make_sources.py`).
- `classify.json` — keyword rules that tag items (kind, occasion, which dua).
- `build_feed.py` — runs every 3 hours (`.github/workflows/kawthar.yml`):
  reads the sources, accumulates `catalog.json`, tags, checks which shrines
  are live, applies the editors' decisions from Kawthar Studio
  (`codisty.com/kawthar-studio/api/overrides.json` and `sources.json`), and
  writes `public/kawthar/feed.json` (the app) and `public/kawthar/catalog.json`
  (the Studio). Mondays it also searches Apple Podcasts for new Shia shows,
  which wait in the Studio for approval.

Nothing is re-hosted: videos play in YouTube's embedded player from the
official channel, audio streams from its original host. Titles naming
political figures or parties are held for an editor.
