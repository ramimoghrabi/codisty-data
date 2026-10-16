# Pennyplate photo picker — instructions for the Claude Code routine

Recipes in the Pennyplate app can show a real food photo. For each recipe waiting for one, GitHub has
put up to nine openly licensed photo options (from Openverse: Flickr, Wikimedia and others) in
`pennyplate/photo-inbox/`:
  - `<recipe-id>.jpg`: a contact sheet with the options numbered 1–9
  - `<recipe-id>.json`: the recipe (title, summary, ingredients) and each option's title and credit

1. List `pennyplate/photo-inbox/*.json` (ignore `choices.json`). If there are none, stop: there's nothing
   to do and nothing to push.
2. For each recipe: read its JSON, then open its contact sheet image and look at it carefully.
   Pick the number of the photo that best shows **this dish** as a cook would serve it at home:
   - the same kind of dish with its main ingredients visible (a lentil soup for a lentil soup, tacos for
     tacos); close variations are fine
   - appetising and well lit; food is the subject
   - no faces or people as the subject, no text or logos, no raw ingredients alone, no places, menus or
     packaging, no restaurant-style dish that looks nothing like the recipe
   - a sharp, reasonably modern-looking photo; skip blurry, dark or tiny-looking ones
   If none of them is clearly the same dish, pick 0. A wrong photo is worse than no photo; the app
   then keeps its designed plate picture.
3. Write `pennyplate/photo-inbox/choices.json` as a JSON array: `[{"id": "<recipe-id>", "pick": 3}, ...]` (pick is 1–9, or 0 for none)
   with one entry for every recipe you looked at.
4. Commit only `pennyplate/photo-inbox/choices.json` with the message "Photo picks for <today's date>"
   and push to a new branch named `claude/photos-<today's date>`. Change nothing else.

The "Recipe photos" workflow downloads the chosen photos, adds them to the app's recipes and publishes.
