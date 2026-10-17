#!/usr/bin/env python3
"""The shelves at the top of the app's Recipes tab: public/pennyplate/feed.json.

    python3 pennyplate/tools/update_feed.py --checker PATH

Three kinds, rebuilt whenever recipes or prices change:
  curated  themed collections the recipe routine writes for the week ahead
           ("Ramadan iftar on a budget", "Game day under $2"), kept until they expire
  deals    "Cheaper this month": recipes built on the ingredients whose US average
           price fell most in the latest BLS month
  season   "In season": recipes using this month's produce

The version only goes up when the shelves actually change, so phones download
the file only then.
"""
import argparse, datetime, json, os, random, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
PENNY = os.path.dirname(HERE)
ROOT = os.path.dirname(PENNY)
PUBLIC = os.path.join(ROOT, "public", "pennyplate")
COLLECTIONS = os.path.join(PENNY, "collections.json")

# US produce at its cheapest and best, by month (catalog ids).
SEASON = {
    1: ["orange", "lemon", "lime", "cabbage", "kale", "leek", "sweet-potato", "cauliflower"],
    2: ["orange", "lemon", "cabbage", "kale", "leek", "cauliflower", "broccoli"],
    3: ["spinach", "leek", "broccoli", "cabbage", "green-onion", "radish"],
    4: ["asparagus", "spinach", "green-onion", "radish", "arugula", "mint"],
    5: ["asparagus", "berries", "radish", "spinach", "arugula", "zucchini"],
    6: ["berries", "zucchini", "cucumber", "cherry-tomato", "green-beans", "basil"],
    7: ["corn-cob", "tomato", "zucchini", "bell-pepper", "berries", "cucumber", "basil", "eggplant"],
    8: ["corn-cob", "tomato", "eggplant", "bell-pepper", "cherry-tomato", "zucchini", "jalapeno"],
    9: ["tomato", "eggplant", "apple", "corn-cob", "bell-pepper", "sweet-potato"],
    10: ["butternut", "sweet-potato", "apple", "brussels", "cauliflower", "kale", "cabbage", "mushroom"],
    11: ["butternut", "sweet-potato", "pumpkin-puree", "brussels", "cauliflower", "apple", "cabbage"],
    12: ["orange", "brussels", "sweet-potato", "cabbage", "kale", "butternut", "leek"],
}
SEASON_LOOK = {12: "❄️", 1: "❄️", 2: "❄️", 3: "🌱", 4: "🌱", 5: "🌱", 6: "☀️", 7: "☀️", 8: "☀️", 9: "🍂", 10: "🍂", 11: "🍂"}


def load(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checker", required=True)
    a = ap.parse_args()
    today = datetime.date.today()
    book = load(os.path.join(PUBLIC, "recipes.json"))
    catalog = {i["id"]: i for i in load(os.path.join(PUBLIC, "catalog.json"))["items"]}
    prices = load(os.path.join(PENNY, "prices.json"), {})
    uses = json.loads(subprocess.run([a.checker, "uses", "--catalog", os.path.join(PUBLIC, "catalog.json"),
                                      "--recipes", os.path.join(PUBLIC, "recipes.json")], capture_output=True, text=True, check=True).stdout)
    by_id = {r["id"]: r for r in book["recipes"]}
    dinners = [r for r in book["recipes"] if r["meal"] == "dinner"]
    shelves = []

    # Curated collections still running.
    kept = []
    for c in load(COLLECTIONS, []):
        if c.get("until", "9999") < today.isoformat():
            continue
        ids = [i for i in c["recipes"] if i in by_id][:14]
        if len(ids) >= 4:
            kept.append(c)
            shelves.append({"id": c["id"], "kind": "curated", "title": c["title"], "subtitle": c.get("subtitle", ""), "recipes": ids})
    with open(COLLECTIONS, "w") as f:
        json.dump(kept, f, ensure_ascii=False, indent=1)

    # Cheaper this month.
    moves = (prices.get("moves") or {}).get("items", {})
    falling = [(i, m) for i, m in sorted(moves.items(), key=lambda kv: kv[1]) if m <= -0.01 and i in catalog][:4]
    if falling:
        names = {i for i, _ in falling}
        picks = [r for r in dinners if names & set(uses.get(r["id"], {}).get("ids", []))]
        picks.sort(key=lambda r: (-len(names & set(uses[r["id"]]["ids"])), uses[r["id"]]["perServing"]))
        if len(picks) >= 4:
            label = ", ".join(f"{catalog[i]['name'].lower()} {m * 100:.0f}%".replace("-", "−") for i, m in falling[:3])
            shelves.append({"id": f"deals-{prices['moves']['period']}", "kind": "deals", "title": "Cheaper this month 📉",
                            "subtitle": f"Latest US prices: {label}",
                            "recipes": [r["id"] for r in picks[:12]]})

    # In season.
    produce = set(SEASON[today.month])
    seasonal = [r for r in dinners if produce & set(uses.get(r["id"], {}).get("ids", []))]
    rng = random.Random(f"{today.year}-{today.month}")
    rng.shuffle(seasonal)
    seasonal.sort(key=lambda r: -len(produce & set(uses[r["id"]]["ids"])))
    if len(seasonal) >= 4:
        month = today.strftime("%B")
        shelves.append({"id": f"season-{today:%Y-%m}", "kind": "season", "title": f"In season: {month} {SEASON_LOOK[today.month]}",
                        "subtitle": "Fresh, cheap and at its best right now", "recipes": [r["id"] for r in seasonal[:12]]})

    features = load(os.path.join(PENNY, "features.json"), {})   # switches the app reads, e.g. {"instacart": true}
    path = os.path.join(PUBLIC, "feed.json")
    old = load(path, {"version": 0, "shelves": []})
    if old.get("shelves") == shelves and old.get("features", {}) == features:
        print("feed unchanged")
        return
    doc = {"version": old.get("version", 0) + 1, "updated": today.isoformat(), "shelves": shelves, "features": features}
    with open(path, "w") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print(f"feed v{doc['version']}: " + "; ".join(f"{s['title']} ({len(s['recipes'])})" for s in shelves))


if __name__ == "__main__":
    main()
