#!/usr/bin/env python3
"""Real photos for Pennyplate recipes, from Openverse: openly licensed photos
(Flickr, Wikimedia and more) that allow commercial use and resizing. No key.

    python3 pennyplate/tools/photos.py queue [--limit 120]
    python3 pennyplate/tools/photos.py apply CHOICES.json

queue: for each recipe without a photo (and not skipped before), searches
       Openverse and saves the top nine options to pennyplate/photo-inbox/:
       <id>.json (the options) and <id>.jpg (a numbered contact sheet).
pick:  the "Pennyplate photo picker" routine looks at each contact sheet and
       writes choices.json: [{"id": "<recipe id>", "pick": 1-9, or 0 for none}].
apply: downloads each chosen photo, saves a 1000 px JPEG to
       public/pennyplate/photos/<id>.jpg, sets the recipe's "photo" (file,
       creator and licence credit, source page, licence link), clears the inbox
       entries and bumps the recipes version. Recipes picked 0 are remembered in
       photo-skip.json.

Anonymous Openverse use allows 20 searches a minute and 200 a day; queue paces
itself and stops on a 429, leaving the rest for the next run.
"""
import datetime, io, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
PENNY = os.path.dirname(HERE)
ROOT = os.path.dirname(PENNY)
RECIPES = os.path.join(ROOT, "public", "pennyplate", "recipes.json")
PHOTOS = os.path.join(ROOT, "public", "pennyplate", "photos")
INBOX = os.path.join(PENNY, "photo-inbox")
SKIP = os.path.join(PENNY, "photo-skip.json")
UA = "Codisty Pennyplate (info@codisty.com)"
TILE, COLS, ROWS = 300, 3, 3
SEARCH = "https://api.openverse.org/v1/images/?"


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
        return r.read()


def credit_of(r):
    """ "ultrakml · CC BY 2.0", "Public domain" """
    lic = (r.get("license") or "").lower()
    if lic in ("cc0", "pdm"):
        name = "Public domain"
    else:
        name = f"CC {lic.upper()} {r.get('license_version') or ''}".strip()
    who = r.get("creator") or (r.get("source") or "").title()
    return f"{who} · {name}" if who and name != "Public domain" else (who or name)


def query_for(recipe):
    """English words of the title: "Shorbat Adas (Lebanese Lentil Soup)" → "Lebanese Lentil Soup"."""
    title = recipe["title"]
    m = re.search(r"\(([^)]+)\)", title)
    q = m.group(1) if m else title
    q = re.sub(r"\b(easy|quick|best|budget|one-pot|sheet-pan|weeknight|homemade|copycat|viral|tiktok)\b", "", q, flags=re.I)
    return re.sub(r"\s+", " ", q.replace("&", " ")).strip()


def contact_sheet(thumbs):
    sheet = Image.new("RGB", (COLS * TILE, ROWS * TILE), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 44)
    except OSError:
        font = ImageFont.load_default(size=44)
    for i, img in enumerate(thumbs):
        img = img.convert("RGB")
        s = min(img.size)
        img = img.crop(((img.width - s) // 2, (img.height - s) // 2, (img.width + s) // 2, (img.height + s) // 2)).resize((TILE - 8, TILE - 8))
        x, y = (i % COLS) * TILE + 4, (i // COLS) * TILE + 4
        sheet.paste(img, (x, y))
        draw.rectangle([x, y, x + 58, y + 58], fill="black")
        draw.text((x + 15, y + 4), str(i + 1), fill="white", font=font)
    return sheet


def queue(limit):
    os.makedirs(INBOX, exist_ok=True)
    book = json.load(open(RECIPES))
    skip = set(json.load(open(SKIP))) if os.path.exists(SKIP) else set()
    waiting = {f[:-5] for f in os.listdir(INBOX) if f.endswith(".json") and f != "choices.json"}
    todo = [r for r in book["recipes"] if not r.get("photo") and r["id"] not in skip and r["id"] not in waiting][:limit]
    done = 0
    for r in todo:
        q = query_for(r)
        params = {"q": q, "license_type": "commercial,modification", "mature": "false", "page_size": COLS * ROWS}
        doc = None
        for attempt in range(3):              # Openverse has the odd 5xx; retry, then move on
            try:
                doc = json.loads(get(SEARCH + urllib.parse.urlencode(params)))
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    break
                print(f"  {r['id']}: Openverse error {e.code}, try {attempt + 1} of 3")
                time.sleep(10 * (attempt + 1))
            except Exception as e:
                print(f"  {r['id']}: {type(e).__name__}, try {attempt + 1} of 3")
                time.sleep(10 * (attempt + 1))
        time.sleep(3.5)                       # stay under 20 searches a minute
        if doc is None:
            if attempt < 2:                   # left the loop early: the daily limit
                print("  Openverse daily limit reached; the rest wait for the next run")
                break
            continue
        results = doc.get("results", [])[:COLS * ROWS]
        thumbs, options = [], []
        for res in results:
            try:
                thumbs.append(Image.open(io.BytesIO(get(res.get("thumbnail") or res["url"]))))
                time.sleep(0.3)
            except Exception:
                continue
            options.append({"n": len(options) + 1, "title": res.get("title") or "", "credit": credit_of(res),
                            "page": res.get("foreign_landing_url") or res["url"], "license": res.get("license_url") or "",
                            "src": res["url"]})
        if not options:
            print(f"  {r['id']}: nothing for {q!r}")
            continue
        contact_sheet(thumbs).save(os.path.join(INBOX, f"{r['id']}.jpg"), quality=82)
        with open(os.path.join(INBOX, f"{r['id']}.json"), "w") as f:
            json.dump({"id": r["id"], "title": r["title"], "summary": r["summary"],
                       "ingredients": r["ingredients"], "query": q, "options": options}, f, ensure_ascii=False, indent=1)
        done += 1
        print(f"  queued {r['id']} ({len(options)} options for {q!r})")
    print(f"queued {done} recipes")


def apply(choices_path):
    choices = json.load(open(choices_path))
    book = json.load(open(RECIPES))
    by_id = {r["id"]: r for r in book["recipes"]}
    skip = set(json.load(open(SKIP))) if os.path.exists(SKIP) else set()
    os.makedirs(PHOTOS, exist_ok=True)
    added = 0
    for c in choices:
        rid, pick = c.get("id"), int(c.get("pick", 0))
        opts_path = os.path.join(INBOX, f"{rid}.json")
        if rid not in by_id or not os.path.exists(opts_path):
            print(f"  {rid}: not waiting for a photo, ignored")
            continue
        options = json.load(open(opts_path))["options"]
        if 1 <= pick <= len(options):
            o = options[pick - 1]
            img = Image.open(io.BytesIO(get(o["src"]))).convert("RGB")
            img.thumbnail((1000, 1000))
            img.save(os.path.join(PHOTOS, f"{rid}.jpg"), quality=80, optimize=True, progressive=True)
            by_id[rid]["photo"] = {"file": f"{rid}.jpg", "credit": o["credit"], "page": o["page"], "license": o["license"]}
            added += 1
            print(f"  {rid}: photo {pick}, {o['credit']}")
        else:
            skip.add(rid)
            print(f"  {rid}: no good match; keeps its plate art")
        for ext in ("json", "jpg"):
            p = os.path.join(INBOX, f"{rid}.{ext}")
            if os.path.exists(p):
                os.remove(p)
    with open(SKIP, "w") as f:
        json.dump(sorted(skip), f, indent=1)
    if added:
        book["version"] += 1
        book["updated"] = datetime.date.today().isoformat()
        with open(RECIPES, "w") as f:
            json.dump(book, f, ensure_ascii=False, separators=(",", ":"))
    print(f"added {added} photos")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(f"### {added} recipe photos added (recipes v{book['version']})\n")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "queue":
        limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 120
        queue(limit)
    elif len(sys.argv) == 3 and sys.argv[1] == "apply":
        apply(sys.argv[2])
    else:
        raise SystemExit(__doc__)
