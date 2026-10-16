# Weekly Pennyplate recipes — instructions for the Claude Code routine

You are writing this week's new recipes for Pennyplate, a budget meal-planning app. GitHub Actions checks
and publishes what you push: every ingredient line is priced by the app's own parser, and anything that
doesn't pass is dropped. Work carefully and follow the house rules exactly.

1. Run `python3 pennyplate/tools/generate_recipes.py --brief /tmp/brief.md` and read `/tmp/brief.md` in full.
   It has this week's briefs, the house rules, the titles already in the collection, two example recipes
   and the ingredient catalog. Use only catalog ingredients, named the way the catalog names them.
2. Do the trend scouting it describes with web search: dishes going viral on TikTok and Instagram in the US
   right now that a family can cook cheaply. Pick the three best.
3. Write the recipes the brief asks for: original recipes in your own words, no creator names. Tag the
   trend-based ones "trending".
4. Save them as a JSON array to `pennyplate/inbox/candidates.json`. Then run
   `python3 -c "import json; d=json.load(open('pennyplate/inbox/candidates.json')); print(len(d), 'recipes')"`
   to be sure it parses.
5. Re-read every ingredient line against the catalog and every diet label against the rules in the brief,
   and fix anything doubtful. Diet labels are promises to people with allergies: leave a label off when unsure.
6. Commit only `pennyplate/inbox/candidates.json` with the message "Recipe candidates for <today's date>"
   and push to a new branch named `claude/recipes-<today's date>`. Change nothing else in the repository.

The "Recipes from the routine" workflow takes it from there: it screens the candidates, adds the best eight
to the app's recipes, publishes, and deletes the branch.
