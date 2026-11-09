# Exercise: London Weather Python CLI

## Overview

Build a command-line tool, `weather.py`, that fetches historical daily weather
for London from the public Open-Meteo Archive API and produces useful summaries.

The tool should be user-friendly, resilient to network issues, cache successful
responses locally, and support a verbosity mode for debugging.

## API

```text
https://archive-api.open-meteo.com/v1/archive
```

Use these query parameters:

```text
latitude=51.5072
longitude=-0.1276
start_date=2022-01-01
end_date=2022-12-31
daily=temperature_2m_max,precipitation_sum,weather_code
timezone=UTC
```

No API key is required.

## Goals

- Fetch and cache the raw Open-Meteo JSON response.
- Consider daily weather records for the year 2022.
- Print different reports based on an `--action` argument.
- Support `--verbose` logging and basic resilience: timeout and retry.

## Usage examples

```text
python weather.py --action report
python weather.py --action rainfall -v
python weather.py --action weather-codes --refresh --cache .cache/weather.json
```

## CLI arguments

- `--action {report,rainfall,weather-codes}`: required.
- `--verbose` or `-v`: optional; increases logging detail.
- `--refresh`: optional; ignores the cache and fetches fresh data.
- `--cache PATH`: optional cache-file path; defaults to `weather.json`.

## Actions and outputs

### `report`

Print a 2022 summary:

- total days with a valid date;
- dry days, where precipitation is exactly `0`;
- rainy days, where precipitation is greater than `0`;
- rainy-day ratio as a percentage.

The denominator must exclude days whose precipitation value is missing or
invalid.

Example output:

```text
Total: 365 | Dry: 241 | Rainy: 124 | Rainy-day ratio: 34%
```

### `rainfall`

Print average precipitation per valid day. Treat missing precipitation values as
`0`.

Example output:

```text
Average rainfall per day: 1.82 mm
```

### `weather-codes`

Count daily records by Open-Meteo `weather_code`.

- Sort descending by count.
- Use `unknown` if a weather code is missing.
- For equal counts, sort codes alphabetically.

Example output:

```text
0 — 152
3 — 98
61 — 42
unknown — 1
```

## Behaviour details

### Data source

Perform an HTTP `GET` against the API endpoint with the specified query
parameters.

The API returns daily values in parallel arrays, for example:

```json
{
  "daily": {
    "time": ["2022-01-01", "2022-01-02"],
    "temperature_2m_max": [12.3, 11.8],
    "precipitation_sum": [0.0, 1.4],
    "weather_code": [3, 61]
  }
}
```

Convert these arrays into daily records safely. Arrays may be missing or have
unequal lengths.

### Caching

- Save the complete raw JSON response to the cache file after a successful
  fetch.
- Use the cache by default if it exists.
- `--refresh` must ignore any existing cache and fetch current data.
- If cached JSON is invalid, show a clear error and exit with a non-zero status.

### Robustness

- HTTP timeout: 15 seconds.
- Retry once if the request times out.
- For non-200 responses, print a clear error and exit with a non-zero status.
- Handle missing `daily`, missing arrays, invalid dates, and invalid numeric
  values safely.
- Do not print a traceback for expected operational errors.

### Verbose mode

With `-v` or `--verbose`, log useful diagnostic messages to `stderr`, such as:

- whether data came from cache or the API;
- the cache path used;
- retry attempts;
- skipped malformed records;
- number of records processed.

Normal report output should remain on `stdout`.

## Implementation expectations

- Python standard library plus `requests` is sufficient.
- Use `argparse`.
- Keep HTTP, cache, parsing, filtering, and reporting logic in small, testable
  functions.
- Add unit tests using mocked HTTP responses and temporary cache files.

Tests should cover:

- successful fetch and cache write;
- cache reuse;
- `--refresh`;
- timeout then successful retry;
- non-200 response;
- invalid cached JSON;
- missing or mismatched daily arrays;
- all three reports.

## Network note

The API is publicly available and requires no API key.