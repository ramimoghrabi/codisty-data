# codisty-data

Data files for Codisty apps, served by GitHub Pages at **https://data.codisty.com**.
Nothing here needs a person: scheduled jobs keep it fresh.

## Pennyplate

| File | What | Updated by |
|---|---|---|
| `public/pennyplate/recipes.json` | Built-in recipes the app shows and plans with | **Weekly recipes** (Mondays) |
| `public/pennyplate/catalog.json` | 213 ingredients with US average prices | **Monthly prices** (16th and 24th) |
| `pennyplate/catalog-base.json` | The catalog at September 2026 prices. Edit ingredients here | by hand |
| `pennyplate/prices.json` | Which BLS series prices which ingredient, and the last month applied | Monthly prices |
| `pennyplate/validator/` | `pennycheck`: the app's own parser and costing, used as a gate | copy from the app (`Tools/sync-data-repo.sh`) |

The app checks for newer files (by `version`) twice a day and keeps the bundled copy if the site is unreachable.

### Weekly recipes (`.github/workflows/recipes.yml`)
1. **Trend scout**: Claude searches the web for dishes going viral on TikTok and Instagram.
2. **Writer**: Claude writes original budget versions of two trends, plus a Middle Eastern classic, a vegetarian dinner and the cuisines the collection has least of. Only catalog ingredients are allowed.
3. **pennycheck screen**: every line must match the catalog, the price ($0.45–6.50 a serving), calories and diet labels must hold up, and nothing may duplicate an existing recipe. Rejects go back to Claude with the reasons, up to twice.
4. The 5 best are appended with `"added": "<date>"` (the app shows them as **New this week**, and trend dishes as **Trending**). The version is bumped, and the job commits and deploys.

It costs about $0.50–1 a week in Claude API usage. Needs the `ANTHROPIC_API_KEY` secret.

### Monthly prices (`.github/workflows/prices.yml`)
Reads the latest BLS Average Price Data for the 30 ingredients BLS prices directly, plus the CPI for food at home for everything else. It then rescales `catalog-base.json`, checks every recipe still prices, and publishes. It does nothing until BLS has a new month. An optional `BLS_API_KEY` secret raises the API limits for the fallback path.

### Run by hand
Actions → *Weekly recipes* or *Monthly prices* → **Run workflow**. Locally:
```
swift build -c release --package-path pennyplate/validator
pennyplate/validator/.build/release/pennycheck check --catalog public/pennyplate/catalog.json --recipes public/pennyplate/recipes.json
pennyplate/validator/.build/release/pennycheck explain --catalog public/pennyplate/catalog.json --recipes public/pennyplate/recipes.json --id shakshuka
```
