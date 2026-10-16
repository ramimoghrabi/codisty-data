# Daily Pennyplate recipes — instructions for the Claude Code routine

You are writing today's new recipes for Pennyplate, a budget meal-planning app (two new recipes a day, each
day with its own theme). GitHub Actions checks and publishes what you push: every ingredient line is priced
by the app's own parser, and anything that doesn't pass is dropped. Work carefully and follow the house
rules exactly.

1. Run `python3 pennyplate/tools/generate_recipes.py --brief /tmp/brief.md` and read `/tmp/brief.md` in full.
   It has today's briefs, the house rules, the titles already in the collection, two example recipes and the
   ingredient catalog. Use only catalog ingredients, named the way the catalog names them.
2. If the brief asks for trend scouting, do it with web search: dishes going viral on TikTok and Instagram in
   the US right now that a family can cook cheaply. Pick the best. Otherwise skip it.
3. Write the recipes the brief asks for: original recipes in your own words, no creator names. Tag
   trend-based ones "trending".
4. Save them as a JSON array to `pennyplate/inbox/candidates.json` and check it parses:
   `python3 -c "import json; print(len(json.load(open('pennyplate/inbox/candidates.json'))), 'recipes')"`
5. Re-read every ingredient line against the catalog and every diet label against the rules in the brief, and
   fix anything doubtful. Diet labels are promises to people with allergies: leave a label off when unsure.
6. If the brief ends with "Collections for the week ahead", do that too and save
   `pennyplate/inbox/collections.json` (check it parses the same way).
7. Commit only the files in `pennyplate/inbox/` you wrote, with the message "Recipes for <today's date>", and
   push to a new branch named `claude/recipes-<today's date>`. Change nothing else in the repository.

The "Recipes from the routine" workflow takes it from there: it screens the candidates, adds the best two to
the app's recipes, publishes the collections, and deletes the branch.
