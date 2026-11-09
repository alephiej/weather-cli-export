# weather.py — London Weather CLI

A small command-line tool that fetches historical daily weather for London
(2022) from the [Open-Meteo Archive API](https://archive-api.open-meteo.com),
caches the response locally, and prints summary reports, implementing spec
included in weather-cli-exercise.md

Built as an interview exercise; see the exercise description for the full
requirements. Python 3 + [`requests`](https://pypi.org/project/requests/),
no other dependencies.

## Usage

```sh
pip install requests

python weather.py --action report
python weather.py --action rainfall -v
python weather.py --action weather-codes --refresh --cache .cache/weather.json
```

Actions:

- `report` — dry/rainy day counts for 2022 (dry = exactly 0 mm; days with
  missing precipitation are excluded from the rainy-day ratio).
- `rainfall` — average precipitation per valid day (missing values counted as 0).
- `weather-codes` — day counts per WMO weather code, sorted by count,
  ties alphabetically; missing codes shown as `unknown`.

Options: `--refresh` (ignore cache, refetch), `--cache PATH` (default
`weather.json`), `-v/--verbose` (diagnostics on stderr). Expected operational
errors (network, bad cache, non-200 API response) print a clear message to
stderr and exit with status 1 — no tracebacks.

Run the tests with:

```sh
python -m unittest -v
```

The tests use mocked HTTP responses and temporary cache files; no network
access is needed.

## Notes beyond the spec

A few implementation decisions went past the letter of the requirements:

- **Atomic cache writes.** The cache file is written to `weather.json.tmp`
  and renamed via `os.replace()` only after a successful write, so an
  interrupted run can never leave a truncated or half-written cache behind.
- **Structural validation before caching.** The fetched payload is checked
  to have the expected shape (`daily.time` as a non-empty list, no Open-Meteo
  `error` field) *before* it is committed to the cache — a syntactically
  valid but semantically failed API response is rejected with a clear error
  instead of being poisoned into the cache.
- **Tolerant record parsing.** Parallel value arrays may be missing or
  unequal in length; invalid dates are skipped, non-numeric or negative
  precipitation values become missing values, and every deviation is logged
  in verbose mode. The record count driven by the `time` array.
- **Structured internal representation.** Parsed days are held in a
  `NamedTuple` (`Record`) rather than raw dicts, separating HTTP, parsing,
  and reporting layers — each report is a pure function over records.
- **Plain ASCII output.** All output, including the `weather-codes` report
  separators, uses plain ASCII (`-`) rather than typographic dashes —
  a deliberate deviation from the example formatting, keeping the output
  copy/paste-, diff- and terminal-safe.
