#!/usr/bin/env python3
"""Monthly price update for Pennyplate.

    python3 pennyplate/tools/update_prices.py [--force]

Fetches the latest BLS Average Price Data for the 30 items BLS prices
directly, and the CPI "food at home" index for everything else, then
rescales catalog-base.json (September 2026 prices) and writes
public/pennyplate/catalog.json with a new version number. The app picks the
new file up on its next launch.

Does nothing when BLS hasn't published a newer month than the one applied.
Sources: download.bls.gov flat files, falling back to the BLS public API.
"""
import json, os, sys, datetime, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
PENNY = os.path.dirname(HERE)
ROOT = os.path.dirname(PENNY)
PUBLIC = os.path.join(ROOT, "public", "pennyplate", "catalog.json")
UA = "Codisty Pennyplate price updater (info@codisty.com)"

# A month's move outside this band is more likely a data glitch than prices.
LOW, HIGH = 0.6, 1.8
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fetch(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def latest_from_flat(series, url):
    """{series: (period 'YYYY-MM', value)} from a BLS flat file."""
    wanted, out = set(series), {}
    for line in fetch(url).decode("utf-8", "replace").splitlines():
        parts = line.split("\t")
        if len(parts) < 4 or parts[0].strip() not in wanted:
            continue
        sid, year, per = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if not per.startswith("M") or per == "M13":
            continue
        try:
            value = float(parts[3])
        except ValueError:
            continue
        period = f"{year}-{per[1:]}"
        if sid not in out or period > out[sid][0]:
            out[sid] = (period, value)
    return out


def latest_from_api(series):
    out = {}
    year = datetime.date.today().year
    key = os.environ.get("BLS_API_KEY", "")
    for i in range(0, len(series), 25):
        body = {"seriesid": series[i:i + 25], "startyear": str(year - 1), "endyear": str(year)}
        if key:
            body["registrationkey"] = key
        doc = json.loads(fetch("https://api.bls.gov/publicAPI/v2/timeseries/data/", json.dumps(body).encode()))
        if doc.get("status") != "REQUEST_SUCCEEDED":
            raise RuntimeError(f"BLS API: {doc.get('message')}")
        for s in doc["Results"]["series"]:
            for d in s["data"]:
                if not d["period"].startswith("M") or d["period"] == "M13" or d["value"] in ("-", ""):
                    continue
                period = f"{d['year']}-{d['period'][1:]}"
                if s["seriesID"] not in out or period > out[s["seriesID"]][0]:
                    out[s["seriesID"]] = (period, float(d["value"]))
    return out


def latest(series):
    ap = [s for s in series if s.startswith("APU")]
    cu = [s for s in series if s.startswith("CU")]
    try:
        out = latest_from_flat(ap, "https://download.bls.gov/pub/time.series/ap/ap.data.0.Current")
        out.update(latest_from_flat(cu, "https://download.bls.gov/pub/time.series/cu/cu.data.11.USFoodBeverage"))
        if set(series) - set(out):
            raise RuntimeError(f"missing from flat files: {sorted(set(series) - set(out))}")
        return out
    except (urllib.error.URLError, RuntimeError, TimeoutError) as e:
        print(f"flat files unavailable ({e}); using the BLS API", file=sys.stderr)
        return latest_from_api(series)


def main():
    force = "--force" in sys.argv
    prices = json.load(open(os.path.join(PENNY, "prices.json")))
    base = json.load(open(os.path.join(PENNY, "catalog-base.json")))
    current = json.load(open(PUBLIC))

    cpi_series = prices["cpi"]["series"]
    series = sorted({m["series"] for m in prices["bls"].values()} | {cpi_series})
    values = latest(series)
    period = values[cpi_series][0]
    print(f"latest CPI month {period}; applied {prices['applied']}")
    if period <= prices["applied"] and not force:
        print("nothing new")
        return False

    cpi_ratio = values[cpi_series][1] / prices["cpi"]["base"]
    rows, stale = [], []
    items = []
    for item in base["items"]:
        item = json.loads(json.dumps(item))
        m = prices["bls"].get(item["id"])
        if m:
            p, v = values[m["series"]]
            if p < period:
                stale.append(f"{item['id']} ({p})")
            ratio = v / m["base"]
        else:
            ratio = cpi_ratio
        ratio = min(max(ratio, LOW), HIGH)
        for pk in item["packages"]:
            if pk["price"] > 0:                       # water stays free
                pk["price"] = max(0.05, round(pk["price"] * ratio, 2))
        if m:
            rows.append((item["id"], ratio))
        items.append(item)

    y, mo = period.split("-")
    label = f"{MONTHS[int(mo) - 1]} {y}"
    doc = {"version": current["version"] + 1, "updated": datetime.date.today().isoformat(),
           "source": f"US BLS Average Price Data ({label}); other items follow the CPI for food at home", "items": items}
    with open(PUBLIC, "w") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    prices["applied"] = period
    with open(os.path.join(PENNY, "prices.json"), "w") as f:
        json.dump(prices, f, indent=1)

    lines = [f"### Prices updated to {label} (catalog v{doc['version']})", "",
             f"Food-at-home CPI vs Sep 2026: **{(cpi_ratio - 1) * 100:+.1f}%**", "", "| item | vs Sep 2026 |", "|---|---|"]
    lines += [f"| {i} | {(r - 1) * 100:+.1f}% |" for i, r in sorted(rows, key=lambda x: -abs(x[1] - 1))[:12]]
    if stale:
        lines += ["", "Not yet published this month (used their latest): " + ", ".join(stale)]
    summary = "\n".join(lines)
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(summary + "\n")
    return True


if __name__ == "__main__":
    changed = main()
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"changed={'true' if changed else 'false'}\n")
