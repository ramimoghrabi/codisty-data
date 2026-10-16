#!/usr/bin/env python3
"""Weekly new recipes for Pennyplate.

    python3 pennyplate/tools/generate_recipes.py --checker PATH [--ai gemini|claude] [--count 5] [--dry-run]
    python3 pennyplate/tools/generate_recipes.py --checker PATH --candidates FILE   # no AI: screen a file

1. Trend scout: the AI searches the web for dishes going viral on TikTok and
   Instagram right now.
2. Writer: the AI writes original budget versions of two of them, plus a
   Middle Eastern classic, a vegetarian dinner and dishes from the cuisines
   the collection has least of. It may use only ingredients from the price
   catalog, so every line can be priced.
3. pennycheck (the app's own parser and costing) screens every candidate:
   each line must match the catalog, the cost, calories and diet labels must
   hold up, and nothing may duplicate an existing recipe. Rejects go back to
   the AI once or twice with the reasons.
4. The best `count` are appended to public/pennyplate/recipes.json with
   today's date as "added", and the version goes up so the app downloads it.

Which AI: --ai, else the RECIPE_AI variable, else whichever key is set
(ANTHROPIC_API_KEY first, then GEMINI_API_KEY).
  gemini  Google's free tier: Gemini 2.5 Flash with Google Search finds trends,
          a newer Flash model writes. Free; Google may use prompts to improve
          its products (they contain only recipe requests).
  claude  Claude Opus 5.5 via the Anthropic API: best writing, about $0.50-1 a week.
"""
import argparse, collections, datetime, json, os, random, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CATALOG = os.path.join(ROOT, "public", "pennyplate", "catalog.json")
RECIPES = os.path.join(ROOT, "public", "pennyplate", "recipes.json")

CLAUDE_MODEL = "claude-opus-5-5"
# Re-run a declined request on Anthropic's recommended fallback model.
CLAUDE_FALLBACK = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
# Free-tier Gemini models; override with GEMINI_SCOUT_MODEL / GEMINI_WRITER_MODEL.
GEMINI_SCOUT = os.environ.get("GEMINI_SCOUT_MODEL") or "gemini-2.5-flash"      # Google Search grounding is free on 2.5
GEMINI_WRITER = os.environ.get("GEMINI_WRITER_MODEL") or "gemini-3.8-flash"
GEMINI_WRITER_FALLBACK = "gemini-2.5-flash"

CUISINES = ["american", "mexican", "italian", "asian", "indian", "middleEastern", "mediterranean", "breakfast"]
DIETS = ["vegetarian", "vegan", "glutenFree", "dairyFree", "highProtein", "pescatarian"]
EQUIPMENT = ["oven", "stovetop", "slowCooker", "airFryer", "pressureCooker", "microwave", "blender"]
TINTS = ["tomato", "amber", "sage", "lime", "berry", "clay", "olive", "sea", "plum"]

RECIPE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["recipes"],
    "properties": {"recipes": {"type": "array", "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "title", "summary", "cuisine", "diets", "meal", "servings", "minutes", "equipment", "emoji", "tint",
                     "keepsDays", "tags", "ingredients", "steps"],
        "properties": {
            "id": {"type": "string", "description": "lowercase-words-with-hyphens, unique"},
            "title": {"type": "string"},
            "summary": {"type": "string", "description": "one appetising sentence, 20-220 characters"},
            "cuisine": {"type": "string", "enum": CUISINES},
            "diets": {"type": "array", "items": {"type": "string", "enum": DIETS}},
            "meal": {"type": "string", "enum": ["breakfast", "lunch", "dinner"]},
            "servings": {"type": "integer"},
            "minutes": {"type": "integer"},
            "equipment": {"type": "array", "items": {"type": "string", "enum": EQUIPMENT}},
            "emoji": {"type": "string", "description": "exactly one food emoji"},
            "tint": {"type": "string", "enum": TINTS},
            "keepsDays": {"type": "integer"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "ingredients": {"type": "array", "items": {"type": "string"}},
            "steps": {"type": "array", "items": {"type": "string"}},
        },
    }}},
}

SCOUT_PROMPT = """Today is {today}. Search the web for food and recipe trends that are going viral on TikTok and Instagram \
in the US right now (the last three weeks or so): specific dishes, not general topics.

Pick the {n} best candidates for a budget family-dinner app: dishes a home cook can make with ordinary supermarket \
ingredients for under about $4 a serving. Skip drinks, desserts-only trends, restaurant menu items, brand products and \
anything unsafe.

For each, give: the dish's common name, why it's trending (one line, no creator names), and the core of the dish in a \
sentence (main ingredients and method). Keep it short."""

WRITER_SYSTEM = """You write recipes for Pennyplate, a US budget meal-planning app for families. Every recipe is priced \
ingredient by ingredient against a catalog of US average supermarket prices, so you may only use ingredients from \
the catalog below, and every ingredient line is read by a strict parser.

Ingredient lines: amount + unit + ingredient name + optional ", note". The name must contain one of the catalog \
names or aliases (plurals are fine). Examples:
  "1 lb ground beef"   "2 (15 oz) cans black beans, drained"   "3 cloves garlic, minced"   "1 onion, diced"
  "1 ½ cups long grain rice"   "2 tbsp olive oil"   "½ tsp ground cumin"   "4 corn tortillas"   "1 bunch cilantro"
Units: tsp, tbsp, cup, fl oz, oz, lb, g, clove, slice, bunch, pinch, can (written "1 (15 oz) can ..."), or a bare count \
("2 onions", "6 eggs"). Use weights (lb or oz) for meat, fish and cheese. Never write "to taste" except for salt and pepper. \
No brand names, no optional or "for serving" lines unless they are really part of the dish.

House style:
- Original recipes in your own words. Never copy a creator's recipe text and never name creators.
- Dinners cost about $1-4 a serving; breakfasts and lunches less. Real portions: 400-800 kcal for a dinner serving.
- servings 4 (6-8 for big-batch dishes); minutes = total time; keepsDays = days it keeps in the fridge (1-5).
- 3-8 steps, each a full sentence with times and heat levels. Oven temperatures as "425°F (220°C)".
- Diet labels are promises: vegetarian = no meat or fish (no chicken broth, fish sauce or Worcestershire); vegan = no \
animal products at all (no egg, dairy, honey); glutenFree = no wheat, flour, pasta, bread, pita, couscous, bulgur, \
oats or regular soy sauce; dairyFree = no butter, cheese, yogurt, cream or milk; highProtein = at least 25 g protein a \
serving. When in doubt, leave a label off.
- emoji: one food emoji that looks like the dish. tint: the tablecloth colour that suits it.
- tags: 1-4 lowercase words like "one-pot", "freezer", "sheet-pan", "air-fryer", "kid-friendly". Add the tag \
"trending" only to recipes based on a current trend.
- Titles must be new: not the same dish as anything in the collection."""

WRITER_PROMPT = """Write {k} new recipes, one for each brief, in this order:
{briefs}

{trends}

The collection already has these titles (don't repeat these dishes):
{titles}

Two recipes from the collection, for format and tone:
{examples}

Ingredient catalog (name: aliases | sold as). Use nothing else:
{catalog}"""

COLLECTIONS_PROMPT = """

# Collections for the week ahead

Also curate 2 or 3 themed collections for the app's Recipes tab for the next seven days. Make them timely: check
(web search) what's coming up in the US and the Arab world, such as holidays and observances (Ramadan, Eid,
Thanksgiving, Christmas, Super Bowl, back to school, Mother's Day), the season and the weather, big sports or
events. Where nothing special is on, use evergreen budget themes ("Dinners under $2", "20-minute weeknights",
"Pantry-only dinners"). Already running: {active}.

Write `pennyplate/inbox/collections.json`: a JSON array of
  {{"id": "<short-slug>-{today}", "title": "<title with one emoji>", "subtitle": "<one line>",
    "until": "{until}", "recipes": ["<recipe id>", ...]}}
with 8–14 recipe ids each, chosen from the library below or from the recipes you wrote today (use their ids).
Titles must be short (under 32 characters) and specific.

Library (id | title | cuisine | meal | diets | time):
{index}
"""

REPAIR_PROMPT = """The checker rejected these recipes:
{rejects}

Return corrected versions of only those recipes (same briefs; you may change the dish if it can't be fixed). \
Keep ids unique."""


def load(path):
    with open(path) as f:
        return json.load(f)


def catalog_lines(catalog):
    by_aisle = collections.defaultdict(list)
    for i in catalog["items"]:
        aliases = [a for a in i["aliases"] if a.lower() != i["name"].lower()][:5]
        sold = ", ".join(p["label"] for p in i["packages"])
        staple = " [staple]" if i["staple"] else ""
        by_aisle[i["aisle"]].append(f"- {i['name']}: {', '.join(aliases)} | {sold}{staple}")
    return "\n".join(f"{aisle.upper()}\n" + "\n".join(rows) for aisle, rows in by_aisle.items())


DIET_GAPS = [  # (labels, how to ask for it) — the thinnest combination gets a recipe each week
    (("vegan", "glutenFree"), "vegan and gluten-free (label both)"),
    (("vegetarian", "glutenFree"), "vegetarian and gluten-free (label both)"),
    (("vegan",), "vegan"),
    (("glutenFree", "dairyFree"), "gluten-free and dairy-free (label both)"),
    (("pescatarian",), "pescatarian, built around fish or seafood"),
    (("highProtein", "glutenFree"), "high-protein and gluten-free (label both)"),
    (("vegetarian", "highProtein"), "vegetarian and high-protein (label both)"),
]


def fits(r, diet):
    ds = set(r["diets"])
    return (diet in ds or (diet == "vegetarian" and "vegan" in ds)
            or (diet == "pescatarian" and ("vegetarian" in ds or "vegan" in ds)))


TREND_DAYS = (0, 3)     # Monday and Thursday: scout what's going viral


def trend_day(day=None):
    return (day or datetime.date.today()).weekday() in TREND_DAYS


def briefs(recipes, have_trends, rng, day=None):
    """Today's two briefs. Each day of the week has its own theme, and the
    diet and cuisine briefs always aim at what the collection is thinnest on."""
    day = day or datetime.date.today()
    dinners = [r for r in recipes if r["meal"] == "dinner"]
    counts = collections.Counter(r["cuisine"] for r in dinners)
    others = sorted([c for c in CUISINES if c not in ("middleEastern", "breakfast")], key=lambda c: (counts[c], rng.random()))
    gaps = sorted(DIET_GAPS, key=lambda g: (sum(1 for r in dinners if all(fits(r, d) for d in g[0])), rng.random()))
    trend = ("trending", "A budget version of trend #{n} above, for a family dinner (a different dish from the other trend recipe).")
    popular = ("popular", "A crowd-pleasing family dinner that's popular right now, made cheaper.")
    middle_east = ("middleEastern", "A Middle Eastern home-cooking classic (Levantine, Gulf, Egyptian, Iraqi or North African) "
                                    "not yet in the collection. Authentic name with a short English gloss in the title.")
    themes = {
        0: [trend, trend],
        1: [middle_east, ("diet", f"A satisfying dinner that is {gaps[0][1]}, any cuisine.")],
        2: [("cuisine", f"A {others[0]} dinner, ready in 30 minutes or less."),
            ("lunch", "A make-ahead lunch that packs well (meal 'lunch').") if day.isocalendar()[1] % 2
            else ("breakfast", "A cheap, filling breakfast (meal 'breakfast', cuisine 'breakfast').")],
        3: [trend, ("diet", f"A satisfying dinner that is {gaps[1][1]}, any cuisine.")],
        4: [("fakeaway", "A 'fakeaway': a takeout favourite (pizza, burgers, orange chicken, shawarma, curry…) made at home for "
                         "far less. Say which takeout dish it copies in the summary."),
            ("cuisine", f"A {others[1]} dinner everyone in a family would eat.")],
        5: [("batch", "A big-batch dinner for 6–8 that freezes well (tag 'freezer'), so cooking once covers two nights."),
            ("gadget", "A slow-cooker or air-fryer dinner (equipment slowCooker or airFryer) for a busy day.")],
        6: [("sunday", "A Sunday family dinner, one-pot or sheet-pan (tag it), that leaves leftovers for Monday's lunch."),
            middle_east],
    }
    out = []
    n = 1
    for kind, text in themes[day.weekday()]:
        if kind == "trending":
            if not have_trends:
                kind, text = popular
            else:
                text = text.format(n=n)
                n += 1
        out.append((kind, text))
    return out

def strip_strict(schema):
    """The schema without additionalProperties, for APIs that don't take it."""
    if isinstance(schema, dict):
        return {k: strip_strict(v) for k, v in schema.items() if k != "additionalProperties"}
    if isinstance(schema, list):
        return [strip_strict(v) for v in schema]
    return schema


class Claude:
    name = "Claude"

    def __init__(self):
        import anthropic
        self.anthropic = anthropic
        self.client = anthropic.Anthropic(max_retries=4)
        self.messages = []
        self.tokens = {"in": 0, "out": 0, "searches": 0}

    def _stream(self, **kw):
        with self.client.beta.messages.stream(model=CLAUDE_MODEL, **CLAUDE_FALLBACK, **kw) as s:
            m = s.get_final_message()
        u = m.usage
        self.tokens["in"] += u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0)
        self.tokens["out"] += u.output_tokens
        stu = getattr(u, "server_tool_use", None)
        self.tokens["searches"] += (getattr(stu, "web_search_requests", 0) or 0) if stu else 0
        return m

    @staticmethod
    def _text(message):
        """The answer's text — after the last fallback switch, if a fallback model took over."""
        blocks = list(message.content)
        last = max((i for i, b in enumerate(blocks) if b.type == "fallback"), default=-1)
        return "".join(b.text for b in blocks[last + 1:] if b.type == "text")

    def scout(self, prompt):
        messages = [{"role": "user", "content": prompt}]
        try:
            for _ in range(4):
                m = self._stream(max_tokens=16000, thinking={"type": "adaptive"}, output_config={"effort": "medium"},
                                 tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 6}], messages=messages)
                if m.stop_reason == "pause_turn":          # the server's search loop wants another turn
                    messages = messages[:1] + [{"role": "assistant", "content": m.content}]
                    continue
                if m.stop_reason == "refusal":
                    print("trend scout: declined", file=sys.stderr)
                    return ""
                return self._text(m).strip()
        except self.anthropic.APIError as e:
            print(f"trend scout failed ({e}); writing without trends", file=sys.stderr)
        return ""

    def write(self, prompt):
        self.messages.append({"role": "user", "content": prompt})
        m = self._stream(max_tokens=64000, thinking={"type": "adaptive"},
                         output_config={"effort": "high", "format": {"type": "json_schema", "schema": RECIPE_SCHEMA}},
                         system=WRITER_SYSTEM, messages=self.messages)
        if m.stop_reason == "refusal":
            raise SystemExit("the writer declined this week's request")
        if m.stop_reason == "max_tokens":
            raise SystemExit("the writer ran out of room; raise max_tokens")
        self.messages.append({"role": "assistant", "content": m.content})
        return json.loads(self._text(m))["recipes"]

    def usage(self):
        t = self.tokens
        cost = t["in"] / 1e6 * 4 + t["out"] / 1e6 * 20 + t["searches"] * 0.01
        return f"Claude ({CLAUDE_MODEL}): {t['in']:,} in / {t['out']:,} out tokens, {t['searches']} searches, ≈ ${cost:.2f}"


class Gemini:
    name = "Gemini"

    def __init__(self):
        from google import genai
        from google.genai import types
        self.genai, self.types = genai, types
        self.client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
        self.writer = GEMINI_WRITER
        self.contents = []
        self.tokens = {"in": 0, "out": 0}

    def _call(self, model, contents, config):
        r = self.client.models.generate_content(model=model, contents=contents, config=config)
        u = r.usage_metadata
        if u:
            self.tokens["in"] += u.prompt_token_count or 0
            self.tokens["out"] += (u.candidates_token_count or 0) + (getattr(u, "thoughts_token_count", 0) or 0)
        return r

    def scout(self, prompt):
        t = self.types
        try:
            r = self._call(GEMINI_SCOUT, prompt, t.GenerateContentConfig(tools=[t.Tool(google_search=t.GoogleSearch())]))
            return (r.text or "").strip()
        except Exception as e:                       # trends are a bonus; write without them
            print(f"trend scout failed ({e}); writing without trends", file=sys.stderr)
            return ""

    def write(self, prompt):
        t = self.types
        self.contents.append(t.Content(role="user", parts=[t.Part(text=prompt)]))
        config = t.GenerateContentConfig(system_instruction=WRITER_SYSTEM, response_mime_type="application/json",
                                         response_json_schema=strip_strict(RECIPE_SCHEMA))
        try:
            r = self._call(self.writer, self.contents, config)
        except self.genai.errors.ClientError as e:
            if self.writer == GEMINI_WRITER_FALLBACK or e.code not in (400, 404):
                raise
            print(f"{self.writer} unavailable ({e.code}); using {GEMINI_WRITER_FALLBACK}", file=sys.stderr)
            self.writer = GEMINI_WRITER_FALLBACK
            r = self._call(self.writer, self.contents, config)
        if not r.candidates or not r.text:
            raise SystemExit(f"Gemini returned nothing ({getattr(r, 'prompt_feedback', None)})")
        self.contents.append(r.candidates[0].content)
        return json.loads(r.text)["recipes"]

    def usage(self):
        return f"Gemini ({GEMINI_SCOUT} + {self.writer}, free tier): {self.tokens['in']:,} in / {self.tokens['out']:,} out tokens, $0"


def choose_ai(name):
    name = (name or os.environ.get("RECIPE_AI") or "auto").lower()
    if name == "auto":
        if os.environ.get("ANTHROPIC_API_KEY"):
            name = "claude"
        elif os.environ.get("GEMINI_API_KEY"):
            name = "gemini"
        else:
            raise SystemExit("No AI key. Add GEMINI_API_KEY (free, from aistudio.google.com) or ANTHROPIC_API_KEY "
                             "as a repository secret, or screen your own recipes with --candidates.")
    if name == "claude":
        return Claude()
    if name == "gemini":
        return Gemini()
    raise SystemExit(f"unknown AI {name!r}: use gemini or claude")


def screen(checker, candidates):
    with tempfile.TemporaryDirectory() as d:
        cand, out = os.path.join(d, "candidates.json"), os.path.join(d, "out.json")
        with open(cand, "w") as f:
            json.dump(candidates, f, ensure_ascii=False)
        r = subprocess.run([checker, "screen", "--catalog", CATALOG, "--recipes", RECIPES, "--candidates", cand, "--out", out],
                           capture_output=True, text=True)
        print(r.stdout, end="")
        if r.returncode != 0:
            raise SystemExit(f"pennycheck failed: {r.stderr}")
        return load(out)


def pick(accepted, count):
    trending = [r for r in accepted if "trending" in r.get("tags", [])]
    rest = [r for r in accepted if r not in trending]
    chosen = trending[:3] + rest
    chosen += [r for r in trending[3:] if r not in chosen]
    return chosen[:count]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checker", help="path to the pennycheck binary (needed except with --brief)")
    ap.add_argument("--count", type=int, default=2, help="recipes to keep (two a day)")
    ap.add_argument("--rounds", type=int, default=2, help="repair rounds for rejected recipes")
    ap.add_argument("--candidates", help="screen this JSON array instead of asking an AI")
    ap.add_argument("--ai", help="gemini or claude (default: RECIPE_AI, else whichever key is set)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--brief", metavar="FILE", help="write this week's full instructions for a writer (the Claude Code routine) and stop")
    a = ap.parse_args()

    if a.brief:
        book = load(RECIPES)
        today = datetime.date.today()
        trends = trend_day(today)
        plan = briefs(book["recipes"], trends, random.Random(today.isoformat()), today)
        examples = [r for r in book["recipes"] if r["id"] in ("chana-masala", "shish-tawook")]
        with open(a.brief, "w") as f:
            if trends:
                f.write("# Trend scouting\n\n" + SCOUT_PROMPT.format(today=today.strftime("%B %-d, %Y"), n=3))
            else:
                f.write("# Trend scouting\n\nNot today: no trend briefs. Skip web searching for trends.")
            f.write("\n\n# House rules\n\n" + WRITER_SYSTEM)
            f.write("\n\n# Today\n\n" + WRITER_PROMPT.format(
                k=len(plan) + 1,
                briefs="\n".join(f"{i + 1}. {b}" for i, (_, b) in enumerate(plan)) +
                       f"\n{len(plan) + 1}. A spare: another dinner that fits either brief above.",
                trends="(Use the trends you found.)" if trends else "",
                titles="; ".join(r["title"] for r in book["recipes"]),
                examples="\n".join(json.dumps(r, ensure_ascii=False) for r in examples),
                catalog=catalog_lines(load(CATALOG))))
            f.write("\n\n# Output\n\nA JSON array of recipe objects (not wrapped in an object), each with exactly these fields: "
                    + ", ".join(RECIPE_SCHEMA["properties"]["recipes"]["items"]["required"])
                    + f".\nAllowed values — cuisine: {', '.join(CUISINES)}; diets: {', '.join(DIETS)}; meal: breakfast, lunch, dinner; "
                    + f"equipment: {', '.join(EQUIPMENT)}; tint: {', '.join(TINTS)}.\n")
            active = [c for c in load(os.path.join(os.path.dirname(HERE), "collections.json")) or []
                      if c.get("until", "") >= today.isoformat()] if os.path.exists(os.path.join(os.path.dirname(HERE), "collections.json")) else []
            if today.weekday() == 0 or len(active) < 2:
                index = "\n".join(f"{r['id']} | {r['title']} | {r['cuisine']} | {r['meal']} | {','.join(r['diets']) or '-'} | {r['minutes']} min"
                                   for r in book["recipes"])
                f.write(COLLECTIONS_PROMPT.format(today=today.isoformat(), until=(today + datetime.timedelta(days=7)).isoformat(),
                                                  active="; ".join(c["title"] for c in active) or "none", index=index))
        print(f"wrote {a.brief}")
        return
    if not a.checker:
        ap.error("--checker is required")

    catalog, book = load(CATALOG), load(RECIPES)
    today = datetime.date.today().isoformat()
    rng = random.Random(today)
    accepted, stats, trends, ai = [], {}, "", None

    if a.candidates:
        result = screen(a.checker, load(a.candidates))
        accepted, stats = result["accepted"], result["stats"]
    else:
        ai = choose_ai(a.ai)
        print(f"writing with {ai.name}")
        trends = ai.scout(SCOUT_PROMPT.format(today=datetime.date.today().strftime("%B %-d, %Y"), n=3)) if trend_day() else ""
        plan = briefs(book["recipes"], bool(trends), rng)
        examples = [r for r in book["recipes"] if r["id"] in ("chana-masala", "shish-tawook")]
        prompt = WRITER_PROMPT.format(
            k=len(plan),
            briefs="\n".join(f"{i + 1}. {b}" for i, (_, b) in enumerate(plan)),
            trends=f"Trends this week (from a web search):\n{trends}" if trends else "",
            titles="; ".join(r["title"] for r in book["recipes"]),
            examples="\n".join(json.dumps(r, ensure_ascii=False) for r in examples),
            catalog=catalog_lines(catalog))
        for round_ in range(a.rounds + 1):
            candidates = ai.write(prompt)
            # Last round's winners are screened again first, so new ones can't duplicate them.
            result = screen(a.checker, accepted + candidates)
            accepted, stats = result["accepted"], result["stats"]
            if len(accepted) >= a.count or not result["rejected"] or round_ == a.rounds:
                break
            prompt = REPAIR_PROMPT.format(rejects="\n".join(f"- {r['title']}: " + "; ".join(r["reasons"]) for r in result["rejected"]))

    chosen = pick(accepted, a.count)
    usage = ai.usage() if ai else "no AI (screened a file)"
    print(usage)
    if not chosen:
        raise SystemExit("no recipe passed the checker this week")

    for r in chosen:
        r["added"] = today
    book["recipes"] += chosen
    book["version"] += 1
    book["updated"] = today
    if not a.dry_run:
        with open(RECIPES, "w") as f:
            json.dump(book, f, ensure_ascii=False, separators=(",", ":"))

    lines = [f"### {len(chosen)} new recipes (recipes v{book['version']})", "", "| | recipe | cuisine | per serving | kcal |", "|---|---|---|---|---|"]
    for r in chosen:
        s = stats.get(r["id"], {})
        flag = "🔥" if "trending" in r["tags"] else ""
        lines.append(f"| {r['emoji']} {flag} | {r['title']} | {r['cuisine']} | ${s.get('perServing', 0):.2f} | {s.get('kcal', 0):.0f} |")
    if trends:
        lines += ["", "<details><summary>Trends found</summary>", "", trends, "", "</details>"]
    lines += ["", usage]
    summary = "\n".join(lines)
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(summary + "\n")


if __name__ == "__main__":
    main()
