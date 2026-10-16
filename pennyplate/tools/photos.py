#!/usr/bin/env python3
"""Real photos for Pennyplate recipes, from Pexels (free for commercial use).

    python3 pennyplate/tools/photos.py queue [--limit 120]   # GitHub Actions, needs PEXELS_API_KEY
    python3 pennyplate/tools/photos.py apply CHOICES.json    # GitHub Actions, needs PEXELS_API_KEY

queue: for each recipe without a photo (and not skipped before), searches Pexels
       and saves the top six options to pennyplate/photo-inbox/: <id>.json (the
       options) and <id>.jpg (a numbered contact sheet).
pick:  the "Pennyplate photo picker" routine looks at each contact sheet and
       writes choices.json: [{"id": "<recipe id>", "pick": 1-6, or 0 for none}].
apply: downloads each chosen photo, saves a 1000 px JPEG to
       public/pennyplate/photos/<id>.jpg, sets the recipe's "photo" (file,
       photographer credit, Pexels page), clears the inbox entries and bumps the
       recipes version. Recipes picked 0 are remembered in photo-skip.json.
"""
import datetime, io, json, os, re, sys, urllib.parse, urllib.request

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
PENNY = os.path.dirname(HERE)
ROOT = os.path.dirname(PENNY)
RECIPES = os.path.join(ROOT, "public", "pennyplate", "recipes.json")
PHOTOS = os.path.join(ROOT, "public", "pennyplate", "photos")
INBOX = os.path.join(PENNY, "photo-inbox")
SKIP = os.path.join(PENNY, "photo-skip.json")
UA = "Codisty Pennyplate (info@codisty.com)"
TILE, COLS, ROWS = 360, 3, 2


def key():
    k = os.environ.get("PEXELS_API_KEY", "")
    if not k:
        raise SystemExit("PEXELS_API_KEY is not set (add it as a repository secret)")
    return k


def get(url, auth=False):
    headers = {"User-Agent": UA}
    if auth:
        headers["Authorization"] = key()
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
        return r.read()


def query_for(recipe):
    """English words of the title: "Shorbat Adas (Lebanese Lentil Soup)" → "Lebanese Lentil Soup"."""
    title = recipe["title"]
    m = re.search(r"\(([^)]+)\)", title)
    q = m.group(1) if m else title
    q = re.sub(r"\b(easy|quick|best|budget|one-pot|sheet-pan|weeknight|homemade|copycat|viral|tiktok)\b", "", q, flags=re.I)
    return re.sub(r"\s+", " ", q).strip() + " food"


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
    for r in todo:
        q = query_for(r)
        doc = json.loads(get("https://api.pexels.com/v1/search?" + urllib.parse.urlencode({"query": q, "per_page": COLS * ROWS}), auth=True))
        photos = doc.get("photos", [])[:COLS * ROWS]
        if not photos:
            print(f"  {r['id']}: nothing for {q!r}")
            continue
        thumbs = [Image.open(io.BytesIO(get(p["src"]["medium"]))) for p in photos]
        contact_sheet(thumbs).save(os.path.join(INBOX, f"{r['id']}.jpg"), quality=82)
        options = [{"n": i + 1, "alt": p.get("alt") or "", "photographer": p["photographer"], "page": p["url"], "src": p["src"]["large2x"]}
                   for i, p in enumerate(photos)]
        with open(os.path.join(INBOX, f"{r['id']}.json"), "w") as f:
            json.dump({"id": r["id"], "title": r["title"], "summary": r["summary"],
                       "ingredients": r["ingredients"], "query": q, "options": options}, f, ensure_ascii=False, indent=1)
        print(f"  queued {r['id']} ({len(photos)} options for {q!r})")
    print(f"queued {len(todo)} recipes")


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
            by_id[rid]["photo"] = {"file": f"{rid}.jpg", "credit": o["photographer"], "page": o["page"]}
            added += 1
            print(f"  {rid}: photo {pick} by {o['photographer']}")
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
