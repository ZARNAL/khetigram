#!/usr/bin/env python3
"""Refresh the static Khetigram Gujarat mandi graph cache from data.gov.in.
Network failures are non-fatal: preserve the previous cache and report a warning.
"""
import json, os, urllib.parse, urllib.request, datetime, pathlib, sys, time
from urllib.error import URLError, HTTPError

API_KEY = os.environ.get("DATA_GOV_API_KEY", "").strip()
RESOURCE_IDS = [
    "35985678-0d79-46b4-9ed6-6f13308a1d24",  # historical
    "9ef84268-d588-465a-a308-a864a43d0070",  # latest prices
]
BASE = "https://api.data.gov.in/resource/"
OUT = pathlib.Path("data/graph-cache.json")
FIELDS = ["district","market","commodity","arrival_date","min_price","max_price","modal_price"]

def fetch_resource(resource):
    rows, offset = [], 0
    while True:
        params = {"api-key":API_KEY,"format":"json","limit":10000,"offset":offset,"filters[State]":"Gujarat"}
        url = BASE + resource + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent":"Khetigram-data-cache/1.0"})
        payload = None
        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(req, timeout=25) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except (URLError, HTTPError, TimeoutError, OSError) as exc:
                if attempt == 3:
                    raise RuntimeError(f"API unavailable for resource {resource}: {exc}") from exc
                wait = 5 * attempt
                print(f"Attempt {attempt} failed; retrying in {wait}s: {exc}", flush=True)
                time.sleep(wait)
        batch = payload.get("records") or []
        rows.extend(batch)
        total = int(payload.get("total") or 0)
        if not batch or len(batch) < 10000 or (total and offset + len(batch) >= total):
            break
        offset += len(batch)
        if offset >= 50000:
            print("Safety stop at 50k records per resource")
            break
    return rows

def date_key(value):
    value = str(value or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(value[:10], fmt).strftime("%d/%m/%Y")
        except ValueError:
            pass
    return value

def normalize(row):
    def pick(*keys):
        for key in keys:
            val = row.get(key)
            if val is not None and str(val).strip():
                return val
        return ""
    return {
        "district": str(pick("district","District")),
        "market": str(pick("market","Market")),
        "commodity": str(pick("commodity","Commodity")),
        "arrival_date": date_key(pick("arrival_date","Arrival_Date")),
        "min_price": pick("min_price","Min_Price"),
        "max_price": pick("max_price","Max_Price"),
        "modal_price": pick("modal_price","Modal_Price"),
    }

def identity(row):
    return tuple(str(row.get(k,"")).strip().lower() for k in FIELDS)

def write_summary(message):
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(message + "\n")

if not API_KEY:
    message = "⚠️ DATA_GOV_API_KEY secret is missing. Cache refresh skipped; existing cache preserved."
    print(message, file=sys.stderr)
    write_summary(message)
    sys.exit(0)

fresh = []
success_count = 0
failures = []
for resource in RESOURCE_IDS:
    try:
        records = fetch_resource(resource)
        fresh.extend(normalize(r) for r in records)
        success_count += 1
        print(f"Resource {resource}: fetched {len(records)} records")
    except Exception as exc:
        failures.append(str(exc))
        print(f"Warning: {exc}", file=sys.stderr)

fresh = [r for r in fresh if r["arrival_date"] and r["market"] and r["commodity"]]
existing = []
if OUT.exists():
    try:
        existing = json.loads(OUT.read_text(encoding="utf-8")).get("records", [])
    except Exception as exc:
        print(f"Warning: cache file could not be read; treating as empty: {exc}", file=sys.stderr)

if not fresh:
    message = "⚠️ **Graph cache refresh skipped:** data.gov.in could not be reached. Previous cache preserved; no new prices were downloaded."
    print(message)
    write_summary(message)
    sys.exit(0)

combined = {}
for row in existing + fresh:
    combined[identity(row)] = row
payload = {
    "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "source": "data.gov.in",
    "state": "Gujarat",
    "records": list(combined.values()),
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",",":")), encoding="utf-8")
message = f"✅ **Graph cache updated:** {len(fresh)} fresh records downloaded; {len(payload['records'])} total records retained. Successful resource calls: {success_count}/2."
if failures:
    message += f"\n⚠️ Partial refresh: {len(failures)} resource(s) failed. Existing records retained."
print(message)
write_summary(message)
