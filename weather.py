#!/usr/bin/env python3

import requests
import argparse
import json
import logging
import os
import sys
import datetime as dt
import math
from collections import Counter
from typing import NamedTuple, Optional

API_URL = "https://archive-api.open-meteo.com/v1/archive"
PARAMS = {
    "latitude": "51.5072",
    "longitude": "-0.1276",
    "start_date": "2022-01-01",
    "end_date": "2022-12-31",
    "daily": "temperature_2m_max,precipitation_sum,weather_code",
    "timezone": "UTC",
}
TIMEOUT = 15
YEAR = 2022

log = logging.getLogger("weather-cli")

class WeatherError(Exception):
    """Expected operational error, reported without traceback."""


class Record(NamedTuple):
    date: dt.date
    precip: Optional[float]
    code: Optional[str]

# --------------- HTTP ---------------------------

def fetch_json(url=API_URL, params=None, timeout=TIMEOUT, retries=1):
    """Get the API output, retry only on timeout, as per requirements, otherwise fail cleanly."""
    params = PARAMS if params is None else params
    for attempt in range(retries+1):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
        except requests.Timeout:
            if attempt < retries:
                log.info("request timed out, retrying (%d/%d)", attempt + 1, retries)
                continue
            raise WeatherError(f"request timed out after {attempt + 1} attempt(s)")
        except requests.RequestException as exc:
            raise WeatherError(f"network error: {exc}")
        if resp.status_code != 200:
            raise WeatherError(f"API returned HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError:
            raise WeatherError("API returned invalid JSON")
    raise WeatherError("unreachable")

# --------------- Caching ------------------------

def load_cache(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as exc:
        raise WeatherError(f"cache file {path} contains invalid JSON {exc}")
    except OSError as exc:
        raise WeatherError(f"cannot read cache file: {path}: {exc}")


def save_cache(path, data):
    tmp = f"{path}.tmp"
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
    except OSError as exc:
        raise WeatherError(f"cannot write cache file {path}: {exc}")


def is_valid_payload(raw):
    """Structural validation: enough data that parse_records can process."""
    daily = raw.get("daily") if isinstance(raw, dict) else None
    return (
        isinstance(raw, dict)
        and not raw.get("error")
        and isinstance(daily, dict)
        and isinstance(daily.get("time"), list)
        and len(daily.get("time")) > 0
    )

def load_or_fetch(cache_path, refresh=False):
    if not refresh and os.path.exists(cache_path):
        log.info(f"using cache {cache_path}")
        return load_cache(cache_path)
    log.info(f"fetching from API (cache path: {cache_path})")
    data = fetch_json()
    if not is_valid_payload(data):
        raise WeatherError("API response has unexpected structure")
    save_cache(cache_path, data)
    return data

# --------------- Parsing ------------------------

def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return float(value)

def _code(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return None

def _at(seq, i):
    return seq[i] if isinstance(seq, list) and i < len(seq) else None

def parse_records(raw):
    """Turn Open-Meteo parallel arrays into Records for YEAR.

    The `time` array drives the record count; shorter/missing value arrays
    yield None for the absent entries. Entries with an invalid date are skipped.
    """
    daily = raw.get("daily") if isinstance(raw, dict) else None
    if not isinstance(daily, dict):
        log.info("no 'daily' object in data")
        return []
    times = daily.get("time")
    if not isinstance(times, list):
        log.info("no 'time' array in data")
        return []
    precip = daily.get("precipitation_sum")
    codes = daily.get("weather_code")
    records, skipped = [], 0
    for i, t in enumerate(times):
        try:
            date = dt.date.fromisoformat(t)
        except (TypeError, ValueError):
            skipped += 1
            log.info("skipping record %d: invalid date %r", i, t)
            continue
        if date.year != YEAR:
            skipped += 1
            continue
        records.append(Record(date, _number(_at(precip, i)), _code(_at(codes, i))))
    log.info("processed %d records (%d skipped)", len(records), skipped)
    return records

# --------------- Reports ------------------------

def report(records):
    """Calculates number of rainy and dry days and provides rainy day percentage."""
    valid = [r.precip for r in records if r.precip is not None]
    dry = sum(1 for p in valid if p == 0)
    rainy = len(valid) - dry
    ratio = round(100 * rainy / len(valid)) if valid else 0
    return f"Total: {len(records)} | Dry: {dry} | Rainy: {rainy} | Rainy-day ratio: {ratio}%"


def rainfall(records):
    """Calculates average rainfall. 
    Sums only valid percipitation values, divided by count of number of valid values"""
    avg = sum(r.precip or 0.0 for r in records) / len(records) if records else 0.0
    return f"Average rainfall per day: {avg:.2f} mm"


def weather_codes(records):
    counts = Counter(r.code if r.code is not None else "unknown" for r in records)
    rows = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return "\n".join(f"{code} - {n}" for code, n in rows)

# --------------- CLI ----------------------------

REPORTS = {"report": report, "rainfall": rainfall, "weather-codes": weather_codes}

def build_parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--action", required=True, choices=REPORTS)
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--refresh", action="store_true",
                   help="Ignore the cache and fetch fresh data")
    p.add_argument("--cache", default="weather.json", metavar="PATH")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        stream=sys.stderr, format="%(message)s",
        level=logging.INFO if args.verbose else logging.WARNING,
        force=True,
    )
    try:
        raw = load_or_fetch(args.cache, args.refresh)
        output = REPORTS[args.action](parse_records(raw))
    except WeatherError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
