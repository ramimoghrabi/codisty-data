#!/usr/bin/env python3
"""Kawthar's living library: latmiyat, nauha, majalis, lectures, recited
duas and live shrine streams, gathered automatically.

Every few hours (GitHub Actions, .github/workflows/kawthar.yml) this:
  1. reads the official YouTube channels' RSS feeds, the podcast feeds and the
     licensed Internet Archive items listed in sources.json, plus any source
     editors added in Kawthar Studio;
  2. merges new uploads into catalog.json, so history accumulates beyond what
     a feed shows at once;
  3. tags each item (latmiya / noha / majlis / lecture / dua …, occasions,
     which supplication it recites) with the keyword rules in classify.json;
  4. checks which shrine channels are live right now;
  5. applies the editors' decisions from Kawthar Studio (hide, pin, notice);
  6. writes public/kawthar/feed.json for the app.

Nothing is downloaded or re-hosted: videos play in YouTube's embedded player,
audio streams from its original host. Standard library only.
"""
import datetime as dt
import email.utils
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PUBLIC = os.path.join(ROOT, "public", "kawthar")
# Kawthar's website and Studio (Hostinger). The feed carries these links so the
# app follows a domain change without an update.
SITE = os.environ.get("KAWTHAR_SITE", "https://orange-nightingale-935847.hostingersite.com").rstrip("/")
STUDIO = os.environ.get("KAWTHAR_STUDIO", f"{SITE}/studio/api")
UA = f"KawtharFeed/1.0 (+{SITE}; info@codisty.com)"
NOW = dt.datetime.now(dt.timezone.utc)
PER_SOURCE = 60          # items kept per source in the catalog
FEED_PER_SOURCE = 30     # videos per channel published to the app
FEED_PER_PODCAST = 12    # episodes per podcast published to the app

# Kawthar is a devotional library, not a news or politics channel. Titles that
# name political figures or parties are held back automatically; an editor can
# still approve any of them in Kawthar Studio.
POLITICAL = re.compile("|".join([
    r"خامنه", r"خامنئي", r"رهبر انقلاب", r"رهبر شهید", r"رهبری", r"سليماني", r"سلیمانی", r"soleimani", r"نصر ?الله", r"nasrallah",
    r"حزب ?الله", r"hezbollah", r"hizbullah", r"الحشد الشعبي", r"حشد شعبی", r"رئیسی", r"raisi", r"ترامب", r"ترمپ", r"\btrump\b",
    r"نتنياهو", r"netanyahu", r"صهيون", r"صهیون", r"zionis", r"اسرائيل", r"اسرائیل", r"\bisrael", r"انتخابات", r"election",
    r"الحوثي", r"houthi", r"انصار الله", r"\bhamas\b", r"حماس", r"سپاه", r"الحرس الثوري", r"\birgc\b", r"\bbiden\b", r"بايدن",
]), re.I)
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/", "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def fetch(url, tries=4, timeout=20, accept=None):
    """GET with retries. YouTube's RSS endpoint fails transiently a lot."""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en", **({"Accept": accept} if accept else {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (400, 401, 403, 410) and i >= 1:
                break
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(min(8, 1.0 * 2 ** i))
    log("  ! fetch failed", url, last)
    return None


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------- classify

RULES = load(os.path.join(HERE, "classify.json"), {})
DUA_IDS = {  # classifier ids → the app's text ids
    "jawshan-kabir": "dua-jawshan-kabir", "abu-hamza-thumali": "dua-abu-hamza-thumali", "jawshan-saghir": "dua-jawshan-saghir",
    "dua-mujeer": "dua-mujir", "dua-makarim-akhlaq": "dua-makarim-al-akhlaq", "dua-yastasheer": "dua-yastashir",
    "ziyarat-imam-reza": "ziarat-of-imam-rida-in-mashhad",
}


def norm(s):
    s = unicodedata.normalize("NFKC", html.unescape(s or "")).lower()
    s = re.sub(r"[ً-ٰٟـۖ-ۭ]", "", s)
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ٱ", "ا"), ("ى", "ي"), ("ی", "ي"), ("ک", "ك"), ("ة", "ه"),
                 ("ۀ", "ه"), ("ؤ", "و"), ("ئ", "ي"), ("’", ""), ("'", ""), ("‘", "")):
        s = s.replace(a, b)
    s = re.sub(r"[-_|#:،,.!?()\[\]{}\"«»/\\]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def compile_terms(terms):
    out = []
    for t in sorted(terms, key=len, reverse=True):
        n = norm(t)
        if not n:
            continue
        if " " in n:
            out.append(re.compile(re.escape(n)))
        else:
            out.append(re.compile(r"(?<![\w؀-ۿ])" + re.escape(n) + r"(?![\w؀-ۿ])"))
    return out


KIND = {k: compile_terms(v) for k, v in RULES.get("kind", {}).items()}
KIND_WEAK = {k: compile_terms(v) for k, v in RULES.get("kind_weak", {}).items()}
OCC = {k: compile_terms(v) for k, v in RULES.get("occasion", {}).items()}
DUA = {DUA_IDS.get(k, k): compile_terms(v) for k, v in RULES.get("dua", {}).items()}
PRIORITY = RULES.get("_meta", {}).get("kind_priority", ["live", "quran", "ziyarah", "dua", "latmiya", "noha", "majlis", "madh"])


OG_IMAGE = re.compile(r'<meta property="og:image" content="([^"]+)"')


def channel_avatar(channel):
    """A YouTube channel's profile picture, for the reciter circles in the app."""
    raw = fetch(f"https://www.youtube.com/channel/{channel}", tries=2, accept="text/html")
    if not raw:
        return None
    m = OG_IMAGE.search(raw.decode("utf-8", "replace"))
    if not m or "yt3." not in m.group(1):
        return None
    return re.sub(r"=s\d+-", "=s300-", m.group(1).replace("&amp;", "&"))


def classify(title, source):
    text = norm(title)
    for name in (source.get("name_en"), source.get("name_ar")):
        n = norm(name or "")
        if n:
            text = text.replace(n, " ")
    hits = [k for k in PRIORITY if any(p.search(text) for p in KIND.get(k, []))]
    dua = next((d for d, ps in DUA.items() if any(p.search(text) for p in ps)), None)
    if dua:
        hits.insert(0, "ziyarah" if dua.startswith("ziyarat") or dua.startswith("ziarat") else "dua")
    if not hits:
        hits = [k for k in PRIORITY if any(p.search(text) for p in KIND_WEAK.get(k, []))]
    kind = hits[0] if hits else source.get("kind", "majlis")
    # The source's own nature wins where the title is ambiguous.
    if source.get("kind") in ("lecture", "quran", "kids") and kind not in ("dua", "ziyarah", "live"):
        kind = source["kind"]
    if kind == "ziyarah":
        kind = "dua"
    occ = [o for o, ps in OCC.items() if any(p.search(text) for p in ps)]
    return kind, occ, dua


# ---------------------------------------------------------------- sources

def iso(d):
    return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def youtube_items(src):
    raw = fetch(f"https://www.youtube.com/feeds/videos.xml?channel_id={src['channel']}")
    if not raw:
        return None
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    out = []
    for e in root.findall("a:entry", NS):
        vid = e.findtext("yt:videoId", namespaces=NS)
        link = (e.find("a:link", NS).get("href") if e.find("a:link", NS) is not None else "") or ""
        if not vid or "/shorts/" in link:
            continue  # Shorts don't belong in a listening library
        title = (e.findtext("a:title", namespaces=NS) or "").strip()
        stats = e.find("media:group/media:community/media:statistics", NS)
        out.append({
            "id": f"yt:{vid}", "source": src["id"], "type": "youtube", "title": title, "video": vid,
            "published": e.findtext("a:published", namespaces=NS) or iso(NOW),
            "views": int(stats.get("views", 0)) if stats is not None else 0,
        })
    return out


def parse_duration(s):
    if not s:
        return None
    s = s.strip()
    if s.isdigit():
        return int(s)
    parts = [int(p) for p in s.split(":") if p.isdigit()]
    secs = 0
    for p in parts:
        secs = secs * 60 + p
    return secs or None


def podcast_items(src):
    raw = fetch(src["feed"], tries=3)
    if not raw:
        return None
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    chan = root.find("channel")
    if chan is None:
        return None
    art = src.get("image") or ""
    img = chan.find("itunes:image", NS)
    if img is not None and img.get("href"):
        art = img.get("href")
    art = small_art(art)
    out = []
    for it in chan.findall("item")[:PER_SOURCE]:
        enc = it.find("enclosure")
        if enc is None or not (enc.get("type", "").startswith("audio") or enc.get("url", "").split("?")[0].endswith((".mp3", ".m4a"))):
            continue
        url = enc.get("url")
        if not url or not url.startswith("https://"):
            continue  # iOS App Transport Security: https only
        guid = it.findtext("guid") or url
        date = it.findtext("pubDate")
        try:
            pub = iso(email.utils.parsedate_to_datetime(date)) if date else iso(NOW)
        except (TypeError, ValueError):
            pub = iso(NOW)
        ep_img = it.find("itunes:image", NS)
        out.append({
            "id": "pod:" + re.sub(r"[^A-Za-z0-9]+", "", guid)[-40:], "source": src["id"], "type": "audio",
            "title": (it.findtext("title") or "").strip(), "audio": url, "published": pub,
            "duration": parse_duration(it.findtext("itunes:duration", namespaces=NS)),
            "thumb": small_art(ep_img.get("href") if ep_img is not None and ep_img.get("href") else art) or None,
        })
    return out


def small_art(url):
    """Podcast hosts publish 3000px artwork; the app shows it at 500 at most."""
    return (url or "").replace("-t3000x3000.", "-t500x500.").replace("/3000x3000bb.", "/600x600bb.")


def archive_items(item):
    out = []
    for f in item["files"]:
        if not f["url"].lower().split("?")[0].endswith((".mp3", ".m4a", ".ogg")):
            continue
        name = re.sub(r"\.(mp3|m4a|ogg)$", "", f["name"], flags=re.I).replace("_", " ")
        out.append({
            "id": "ia:" + re.sub(r"[^A-Za-z0-9]+", "", item["identifier"] + f["name"])[-48:],
            "source": "archive", "type": "audio", "title": f"{item['title']} — {name}" if name.lower() not in item["title"].lower() else item["title"],
            "audio": f["url"].replace("http://", "https://"), "published": "2000-01-01T00:00:00Z",
            "duration": int(float(f["length"])) if f.get("length") and re.match(r"^[\d.]+$", str(f["length"])) else None,
            "kind_hint": item.get("kind"), "licence": item.get("license"),
        })
    return out


LIVE_RE = re.compile(r'"isLive"\s*:\s*true')
VID_RE = re.compile(r'<link rel="canonical" href="https://www\.youtube\.com/watch\?v=([\w-]{11})"')


def live_video(channel):
    """The video id a channel is broadcasting live right now, if any."""
    raw = fetch(f"https://www.youtube.com/channel/{channel}/live", tries=2, accept="text/html")
    if not raw:
        return None
    page = raw.decode("utf-8", "replace")
    m = VID_RE.search(page)
    if m and LIVE_RE.search(page) and '"isLiveContent":true' in page:
        return m.group(1)
    return None


# ---------------------------------------------------------------- discovery

DISCOVER_TERMS = ["shia", "ahlulbayt", "ahl al-bayt", "majlis", "majalis", "muharram", "karbala", "imam hussain", "imam husayn",
                  "noha", "nauha", "nohay", "latmiya", "latmiyat", "ziyarat", "dua kumayl", "nahjul balagha", "azadari", "majlis e aza",
                  "اهل البيت", "مجالس حسينية", "محاضرات حسينية", "لطميات", "عاشوراء", "نعي", "مجلس عزاء", "رادود", "قصائد حسينية",
                  "شیعه", "مداحی", "مجالس عزا", "نوحه", "عزاداری", "روضه", "روضه خوانی", "نوحہ", "مجلس عزا", "مصائب اهل البيت"]
DISCOVER_COUNTRIES = ["us", "iq", "kw", "pk", "gb", "lb"]

# A show is judged on its name, its description and its episode titles.
# Strong signs are specific to the Ahl al-Bayt; weak ones (majlis, noha,
# shia, muharram…) are also business podcasts, people's names and actors.
STRONG = re.compile(r"ahl ?ul ?bayt|ahl[ -]al[ -]bayt|ahlulbait|imam (hussain|husayn|husain|hussein)|husayni|hussaini|husaini|karbala|"
                    r"latmiy|nauha|nohay|noha ?khwan|azadari|majlis[- ]e[- ]aza|marsiya|ithna|twelver|"
                    r"أهل البيت|اهل البيت|الإمام الحسين|الامام الحسين|الحسين\b|كربلاء|لطمي|حسينية|رادود|عزاء|عاشوراء|الزهراء|"
                    r"شیعه|امام حسین|نوحه|مداحی|عزاداری|هیئت|روضه|مرثیه|اہل بیت|مجلس عزا|نوحہ|مرثیہ", re.I)
WEAK = re.compile(r"shia|shi'a|shiite|majlis|majalis|muharram|zahra|mahdi|ziyarat|ashura|imam ali|\bduas?\b|"
                  r"مجلس|مجالس|شيع|المهدي|الإمام علي|زيارة|دعاء", re.I)
NEGATIVE = re.compile(r"ahmadi|khuddam|bohra|dawat|fatemi|ismaili|aga khan|hanbali|salaf|sunnah|wahhab|divine mysteries|"
                      r"mahdi has appeared|aba al[- ]sadiq|abdullah hashem|labeouf|real estate|business|marketing|money|market|techno|"
                      r"surgeon|mandarin|hospitality|corporate|metabolic|burnout|christ|church|bible|rabbi|chassid|natak|premchand|"
                      r"\bRA\b|\(ra\)|radi ?allahu|رضي الله عنه|"
                      r"صحيح البخاري|صحيح مسلم|السلف|ابن تيمية|الوهاب", re.I)


def guess_language(text):
    if re.search(r"[ٹڈڑںےہ]", text):
        return "ur"
    if re.search(r"[پچژگکی]", text):
        return "fa"
    if re.search(r"[\u0600-\u06FF]", text):
        return "ar"
    return "en"


def judge(c):
    """auto: clearly a Shia show, published straight away (Studio can hide it).
    review: plausible, waits for an editor. reject: not a Shia show."""
    who = f"{c.get('name_en', '')} {c.get('author', '')}"
    if NEGATIVE.search(who):
        return "reject", {}
    raw = fetch(c["feed"], tries=2, timeout=20)
    if not raw:
        return "review", {}
    try:
        chan = ET.fromstring(raw).find("channel")
    except ET.ParseError:
        return "reject", {}
    if chan is None:
        return "reject", {}
    desc = " ".join(filter(None, [chan.findtext("description"), chan.findtext("itunes:summary", namespaces=NS)]))[:2000]
    eps = chan.findall("item")[:30]
    titles = [(e.findtext("title") or "") for e in eps]
    audio = sum(1 for e in eps if e.find("enclosure") is not None and (e.find("enclosure").get("url") or "").startswith("https://"))
    if NEGATIVE.search(desc) or sum(1 for t in titles if NEGATIVE.search(t)) > 2 or audio < 3:
        return "reject", {}
    n = max(1, len(titles))
    strong = sum(1 for t in titles if STRONG.search(t)) / n
    any_sign = sum(1 for t in titles if STRONG.search(t) or WEAK.search(t)) / n
    named = bool(STRONG.search(who))
    lang = guess_language(" ".join([who, desc] + titles))
    kinds = {}
    for t in titles:
        k, _, _ = classify(t, {"kind": "majlis"})
        kinds[k] = kinds.get(k, 0) + 1
    info = {"kind": max(kinds, key=kinds.get) if kinds else "majlis", "languages": [lang],
            "score": round(strong + any_sign / 2 + (0.5 if named else 0), 2)}
    if (named and (any_sign >= 0.2 or STRONG.search(desc))) or strong >= 0.4:
        return "auto", info
    if named or any_sign >= 0.25 or STRONG.search(desc):
        return "review", info
    return "reject", info


def discover(known_feeds, dismissed):
    """New podcast shows that might be Shia, to be judged."""
    found = {}
    for term in DISCOVER_TERMS:
        for cc in DISCOVER_COUNTRIES:
            url = "https://itunes.apple.com/search?media=podcast&limit=50&country=%s&term=%s" % (cc, urllib.request.quote(term))
            raw = fetch(url, tries=2, timeout=15)
            time.sleep(3.1)  # iTunes Search allows ~20 calls a minute
            if not raw:
                continue
            try:
                results = json.loads(raw).get("results", [])
            except ValueError:
                continue
            for r in results:
                feed = r.get("feedUrl")
                pid = f"pod-{r.get('collectionId')}"
                text = " ".join(str(r.get(k, "")) for k in ("collectionName", "artistName"))
                if not feed or feed in known_feeds or pid in dismissed or pid in found:
                    continue
                if not (STRONG.search(text) or WEAK.search(text)) or NEGATIVE.search(text):
                    continue
                if r.get("trackCount", 0) < 3:
                    continue
                found[pid] = {"id": pid, "type": "podcast", "feed": feed, "name_en": r.get("collectionName", ""),
                              "author": r.get("artistName", ""), "image": small_art(r.get("artworkUrl600", "")),
                              "episodes": r.get("trackCount", 0), "latest": (r.get("releaseDate") or "")[:10], "country": cc,
                              "url": r.get("collectionViewUrl", ""), "found": iso(NOW)}
    return found


# ---------------------------------------------------------------- main

def main():
    seed = load(os.path.join(HERE, "sources.json"), {"sources": [], "archive": []})
    studio = load_remote(f"{STUDIO}/sources.json", {"sources": []})
    overrides = load_remote(f"{STUDIO}/overrides.json", {})
    sources = {s["id"]: s for s in seed["sources"]}
    for s in studio.get("sources", []):
        if s.get("approved", True):
            sources[s["id"]] = {**sources.get(s["id"], {}), **s}
    hidden_sources = set(overrides.get("hidden_sources", []))
    enabled = set(overrides.get("enabled_sources", []))  # re-enable a default-excluded source

    catalog = load(os.path.join(HERE, "catalog.json"), {"items": {}, "live": {}})
    items = catalog.get("items", {})

    # Shows the discovery judged clearly Shia join automatically.
    for sid, s in catalog.get("auto_sources", {}).items():
        sources.setdefault(sid, s)

    # Partner audio uploaded in Kawthar Studio, with the rights holder's permission.
    uploads = load_remote(f"{STUDIO}/uploads.json", None)
    if uploads is not None:
        for s in uploads.get("sources", []):
            sources[s["id"]] = {**s, "type": "partner"}
        live_ids = {u["id"] for u in uploads.get("items", [])}
        for iid in [i for i in items if i.startswith("up:") and i not in live_ids]:
            items.pop(iid)
        for u in uploads.get("items", []):
            old = items.get(u["id"], {})
            items[u["id"]] = {**old, **u, "type": "audio", "fixed_kind": u.get("kind"), "first_seen": old.get("first_seen", iso(NOW))}

    # Channel pictures for the reciter circles, refreshed every two weeks.
    avatars = catalog.setdefault("avatars", {})
    stale = [s for s in sources.values() if s.get("type") == "youtube" and s.get("channel") and not s.get("image")
             and days_ago(avatars.get(s["id"], {}).get("checked", "2000-01-01T00:00:00Z")) > 14][:40]
    with ThreadPoolExecutor(max_workers=3) as pool:
        for s, url in zip(stale, pool.map(lambda s: channel_avatar(s["channel"]), stale)):
            avatars[s["id"]] = {"url": url or avatars.get(s["id"], {}).get("url"), "checked": iso(NOW)}
    for s in sources.values():
        if not s.get("image") and avatars.get(s["id"], {}).get("url"):
            s["image"] = avatars[s["id"]]["url"]
    def gather(s):
        if s["type"] == "youtube" and not s.get("live_only"):
            return s, youtube_items(s)
        if s["type"] == "podcast":
            return s, podcast_items(s)
        return s, []

    def merge(got):
        for it in got:
            old = items.get(it["id"], {})
            items[it["id"]] = {**old, **it, "first_seen": old.get("first_seen", iso(NOW))}

    # A few at a time: polite to the hosts, and one slow feed doesn't stall
    # the run. YouTube throttles bursts from cloud runners with 404s, so the
    # ones that fail get a second, slower pass.
    failed = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for s, got in pool.map(gather, list(sources.values())):
            if got is None:
                failed.append(s)
            else:
                merge(got)
    failures = 0
    for s in failed:
        time.sleep(3)
        _, got = gather(s)
        if got is None:
            failures += 1
            log("  - no update from", s["id"])  # keep what we had
        else:
            merge(got)
    for a in seed.get("archive", []):
        for it in archive_items(a):
            items.setdefault(it["id"], {**it, "first_seen": iso(NOW)})

    # Keep the newest PER_SOURCE per source in the catalog.
    by_source = {}
    for it in items.values():
        by_source.setdefault(it["source"], []).append(it)
    kept = {}
    for sid, its in by_source.items():
        for it in sorted(its, key=lambda x: x["published"], reverse=True)[:PER_SOURCE]:
            kept[it["id"]] = it
    items = kept

    # Classify (always re-run, so better rules apply to old items).
    archive_src = {"id": "archive", "name_en": "Internet Archive", "kind": "majlis"}
    for it in items.values():
        src = sources.get(it["source"], archive_src)
        if it.get("kind_hint"):
            src = {**src, "kind": it["kind_hint"]}
        kind, occ, dua = classify(it["title"], src)
        it["kind"] = it.get("fixed_kind") or kind
        it["occasions"] = occ
        it["dua"] = dua
        it["lang"] = (src.get("languages") or ["ar"])[0]

    # Live streams.
    live = []
    shrines = [s for s in sources.values() if s.get("live") and s["id"] not in hidden_sources]
    with ThreadPoolExecutor(max_workers=4) as pool:
        found = dict(zip([s["id"] for s in shrines], pool.map(lambda s: live_video(s["channel"]), shrines)))
    for s in shrines:
        # A shrine that isn't live this minute keeps its last stream id: their
        # 24/7 streams keep the same id for long stretches.
        vid = found.get(s["id"]) or catalog.get("live", {}).get(s["id"]) or s.get("live_video")
        catalog.setdefault("live", {})[s["id"]] = vid
        live.append({"id": s["id"], "name_en": s["name_en"], "name_ar": s.get("name_ar"), "channel": s["channel"], "video": vid,
                     "place_en": s.get("place_en"), "place_ar": s.get("place_ar")})
    # Shrines broadcasting now first; Karbala and Najaf lead.
    order = ["karbala", "abbas", "alkafeel", "imam-husayn", "imam-ali", "kadhimiya", "askari", "reza", "masumeh", "kufa", "saudi"]
    live.sort(key=lambda l: (l["video"] is None, next((i for i, k in enumerate(order) if k in l["id"]), 99)))

    # Weekly (Mondays) or on request: look for new shows.
    if os.environ.get("KAWTHAR_DISCOVER") == "1" or (NOW.weekday() == 0 and NOW.hour < 3):
        known = {s.get("feed") for s in sources.values() if s.get("feed")}
        dismissed = set(studio.get("dismissed", []))
        new = discover(known, dismissed)
        candidates = catalog.get("candidates", {})
        for pid, c in new.items():
            candidates.setdefault(pid, c)
        # Judge every show not judged yet: publish, keep for review, or drop.
        auto = catalog.setdefault("auto_sources", {})
        counts = {"auto": 0, "review": 0, "reject": 0}
        for pid, c in list(candidates.items()):
            if c.get("verdict"):
                continue
            verdict, info = judge(c)
            counts[verdict] += 1
            if verdict == "reject":
                candidates.pop(pid)
                dismissed.add(pid)
                catalog.setdefault("rejected", []).append(pid)
            elif verdict == "auto" and pid not in dismissed:
                candidates.pop(pid)
                auto[pid] = {"id": pid, "type": "podcast", "feed": c["feed"], "name_en": c["name_en"], "name_ar": "",
                             "image": c.get("image"), "url": c.get("url"), "auto": True, **info}
                sources.setdefault(pid, auto[pid])
            else:
                c.update(info, verdict="review")
        catalog["candidates"] = candidates
        log(f"discovery: {len(new)} new shows; judged {counts}")
    rejected = set(catalog.get("rejected", []))
    for pid in list(catalog.get("candidates", {})):
        if pid in rejected:
            catalog["candidates"].pop(pid)
    for pid in list(catalog.get("candidates", {})):
        if pid in sources or pid in set(studio.get("dismissed", [])):
            catalog["candidates"].pop(pid)

    catalog["items"] = items
    catalog["updated"] = iso(NOW)
    with open(os.path.join(HERE, "catalog.json"), "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    # ---- the published feed ----
    hidden_items = set(overrides.get("hidden_items", []))
    approved = set(overrides.get("approved_items", []))
    pub_sources = [s for s in sources.values() if s["id"] not in hidden_sources and not s.get("live_only")
                   and (not s.get("default_off") or s["id"] in enabled)]
    allowed = {s["id"] for s in pub_sources} | {"archive"}
    feed_items = []
    per = {}
    for it in sorted(items.values(), key=lambda x: x["published"], reverse=True):
        if it["id"] in hidden_items or it["source"] not in allowed:
            continue
        if POLITICAL.search(it["title"]) and it["id"] not in approved:
            it["held"] = "political"
            continue
        per[it["source"]] = per.get(it["source"], 0) + 1
        kind_of_source = sources.get(it["source"], {}).get("type")
        cap = 500 if kind_of_source == "partner" else FEED_PER_PODCAST if it["type"] == "audio" else FEED_PER_SOURCE
        if per[it["source"]] > cap and not it.get("dua"):
            continue
        out = {k: it[k] for k in ("id", "source", "type", "title", "published", "kind") if k in it}
        for k in ("video", "audio", "thumb", "duration", "lang", "dua"):
            if it.get(k):
                out[k] = it[k]
        if it.get("occasions"):
            out["occasions"] = it["occasions"]
        feed_items.append(out)

    recent = [it for it in feed_items if it["type"] == "youtube" and days_ago(it["published"]) <= 21]
    by_views = sorted(recent, key=lambda it: items[it["id"]].get("views", 0), reverse=True)
    featured, seen = [], set()
    for it in by_views:  # most watched lately, one per source
        if it["source"] in seen or it["kind"] in ("kids", "quran"):
            continue
        seen.add(it["source"])
        featured.append(it["id"])
        if len(featured) == 10:
            break

    def shelf(sid, en, ar, pred, n=24):
        ids = [it["id"] for it in feed_items if pred(it)][:n]
        return {"id": sid, "title_en": en, "title_ar": ar, "items": ids} if len(ids) >= 3 else None

    shelves = [s for s in [
        shelf("latmiyat", "New latmiyat", "أحدث اللطميات", lambda i: i["kind"] == "latmiya"),
        shelf("nauha", "Nauha & noha", "النوحيات", lambda i: i["kind"] == "noha"),
        shelf("rawda", "Rowzeh & masa'ib", "المصائب والروضة", lambda i: i["kind"] == "rawda"),
        shelf("majalis", "Majalis", "المجالس الحسينية", lambda i: i["kind"] == "majlis"),
        shelf("madh", "Celebrations — mawalid", "المواليد والأفراح", lambda i: i["kind"] == "madh"),
        shelf("english", "Lectures in English", "محاضرات بالإنجليزية", lambda i: i["kind"] in ("lecture", "majlis") and i.get("lang") == "en"),
        shelf("arabic-lectures", "Arabic lectures", "محاضرات بالعربية", lambda i: i["kind"] in ("lecture", "majlis") and i.get("lang") == "ar"),
        shelf("urdu", "Urdu majalis & nauha", "باللغة الأردية", lambda i: i.get("lang") == "ur"),
        shelf("farsi", "Persian", "بالفارسية", lambda i: i.get("lang") == "fa"),
        shelf("duas", "Recited duas & ziyarat", "الأدعية والزيارات", lambda i: i["kind"] == "dua"),
        shelf("quran", "Quran recitation", "تلاوات القرآن", lambda i: i["kind"] == "quran"),
        shelf("podcasts", "Podcasts", "بودكاست", lambda i: i["type"] == "audio"),
        shelf("kids", "For children", "للأطفال", lambda i: i["kind"] == "kids"),
    ] if s]

    feed = {
        "version": 1, "generated": iso(NOW),
        "sources": [{k: s.get(k) for k in ("id", "type", "name_en", "name_ar", "kind", "languages", "country", "image", "url") if s.get(k) is not None}
                    for s in pub_sources] + [{"id": "archive", "type": "archive", "name_en": "Internet Archive", "name_ar": "أرشيف الإنترنت",
                                              "kind": "majlis", "languages": ["ur"], "url": "https://archive.org"}],
        "items": feed_items,
        "live": live,
        "shelves": shelves,
        "featured": overrides.get("pinned", []) + featured,
        "links": {"site": f"{SITE}/", "privacy": f"{SITE}/privacy-policy/", "terms": f"{SITE}/terms-of-use/",
                  "support": f"{SITE}/support/", "overrides": f"{STUDIO}/overrides.json"},
    }
    if overrides.get("notice"):
        feed["notice"] = overrides["notice"]
    os.makedirs(PUBLIC, exist_ok=True)
    with open(os.path.join(PUBLIC, "feed.json"), "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, separators=(",", ":"))
    # The full catalog (hidden items included) for Kawthar Studio.
    with open(os.path.join(PUBLIC, "catalog.json"), "w", encoding="utf-8") as f:
        json.dump({"updated": catalog["updated"], "sources": list(sources.values()), "items": list(items.values()),
                   "live": live, "candidates": list(catalog.get("candidates", {}).values())}, f, ensure_ascii=False, separators=(",", ":"))
    log(f"items {len(feed_items)} (catalog {len(items)}), live {sum(1 for l in live if l['video'])}/{len(live)}, "
        f"shelves {len(shelves)}, featured {len(featured)}, source failures {failures}")


def days_ago(stamp):
    try:
        return (NOW - dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))).days
    except ValueError:
        return 9999


def load_remote(url, default):
    raw = fetch(url, tries=2, timeout=15)
    try:
        data = json.loads(raw) if raw else None
    except ValueError:
        data = None
    print(f"studio {url}: {'ok' if data is not None else 'UNREACHABLE, using defaults'}")
    return default if data is None else data


if __name__ == "__main__":
    main()
