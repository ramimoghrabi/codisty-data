#!/usr/bin/env python3
"""Weekly prices-outside-the-US data for Pennyplate.

    python3 pennyplate/tools/update_world.py [--refresh-levels]

Writes public/pennyplate/world.json:
  rates   currency units per US dollar (ExchangeRate-API open access, daily ECB-based rates)
  levels  how food prices compare with the US, by country (ISO alpha-2), from the
          World Bank's International Comparison Program: the "Food" price level
          index divided by the US's. 0.93 means groceries cost about 7% less than
          in the US once converted to dollars.

The app multiplies US prices by levels[country] × rates[currency] and labels them
as estimates; users can still enter their own prices.
"""
import datetime, json, os, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PENNY = os.path.dirname(HERE)
ROOT = os.path.dirname(PENNY)
OUT = os.path.join(ROOT, "public", "pennyplate", "world.json")
LEVELS = os.path.join(PENNY, "levels.json")
UA = "Codisty Pennyplate data (info@codisty.com)"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def fetch_levels():
    """ICP food price level index per country, relative to the US."""
    iso = {}
    for c in get("https://api.worldbank.org/v2/country?format=json&per_page=400")[1]:
        if c.get("iso2Code"):
            iso[c["id"]] = c["iso2Code"]
    doc = get("https://api.worldbank.org/v2/sources/90/country/all/series/1101100/classification/PX.WL/time/YR2021/data?format=json&per_page=500")
    rows = doc["source"]["data"] if isinstance(doc["source"], dict) else doc["source"][0]["data"]
    pli = {}
    for r in rows:
        v = {x["concept"]: x["id"] for x in r["variable"]}
        if r.get("value") and v["Country"] in iso:
            pli[iso[v["Country"]]] = r["value"]
    us = pli["US"]
    levels = {k: round(v / us, 3) for k, v in sorted(pli.items())}
    return {"source": "World Bank ICP 2021, Food price level index (US = 1)", "fetched": datetime.date.today().isoformat(), "levels": levels}


def fetch_rates():
    d = get("https://open.er-api.com/v6/latest/USD")
    if d.get("result") != "success":
        raise RuntimeError(f"exchange rates: {d.get('error-type')}")
    return d["rates"], d.get("time_last_update_utc", "")


def main():
    if "--refresh-levels" in sys.argv or not os.path.exists(LEVELS):
        with open(LEVELS, "w") as f:
            json.dump(fetch_levels(), f, indent=1)
    levels = json.load(open(LEVELS))
    rates, stamp = fetch_rates()
    old = json.load(open(OUT)) if os.path.exists(OUT) else {"version": 0}
    doc = {"version": old["version"] + 1, "updated": datetime.date.today().isoformat(),
           "ratesSource": "Exchange rates by ExchangeRate-API (exchangerate-api.com)", "ratesDate": stamp,
           "levelsSource": levels["source"],
           "rates": {k: round(v, 6) for k, v in sorted(rates.items())}, "levels": levels["levels"]}
    with open(OUT, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    sample = ", ".join(f"{c} {doc['levels'].get(c, 1) * doc['rates'].get(cur, 0):.2f} {cur}"
                       for c, cur in [("GB", "GBP"), ("CA", "CAD"), ("AE", "AED"), ("DE", "EUR"), ("EG", "EGP")])
    print(f"world.json v{doc['version']}: {len(doc['rates'])} currencies, {len(doc['levels'])} countries. $1 of US groceries ≈ {sample}")


if __name__ == "__main__":
    main()
