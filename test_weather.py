import contextlib
import datetime as dt
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import requests

import weather

SAMPLE = {
    "daily": {
        "time": ["2022-01-01", "2022-01-02", "2022-01-03", "2022-01-04"],
        "temperature_2m_max": [1, 2, 3, 4],
        "precipitation_sum": [0.0, 1.4, 0.0, 3.0],
        "weather_code": [3, 61, 3, 0],
    }
}


def response(status=200, data=None):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = SAMPLE if data is None else data
    return r


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = weather.main(argv)
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = os.path.join(self.tmp.name, "w.json")


class FetchAndCache(Base):
    @mock.patch("weather.requests.get")
    def test_fetch_and_cache_write(self, get):
        get.return_value = response()
        code, out, _ = run(["--action", "report", "--cache", self.cache])
        self.assertEqual(code, 0)
        self.assertIn("Total: 4 | Dry: 2 | Rainy: 2 | Rainy-day ratio: 50%", out)
        with open(self.cache) as fh:
            self.assertEqual(json.load(fh), SAMPLE)
        _, kwargs = get.call_args
        self.assertEqual(kwargs["timeout"], 15)
        self.assertEqual(kwargs["params"]["start_date"], "2022-01-01")

    @mock.patch("weather.requests.get")
    def test_cache_reuse(self, get):
        with open(self.cache, "w") as fh:
            json.dump(SAMPLE, fh)
        code, out, _ = run(["--action", "rainfall", "--cache", self.cache])
        self.assertEqual(code, 0)
        get.assert_not_called()
        self.assertIn("1.10 mm", out)

    @mock.patch("weather.requests.get")
    def test_refresh_ignores_cache(self, get):
        with open(self.cache, "w") as fh:
            json.dump({"daily": {}}, fh)
        get.return_value = response()
        code, _, _ = run(["--action", "report", "--refresh", "--cache", self.cache])
        self.assertEqual(code, 0)
        get.assert_called_once()
        with open(self.cache) as fh:
            self.assertEqual(json.load(fh), SAMPLE)

    @mock.patch("weather.requests.get")
    def test_timeout_then_success(self, get):
        get.side_effect = [requests.Timeout(), response()]
        code, _, err = run(["--action", "report", "-v", "--cache", self.cache])
        self.assertEqual(code, 0)
        self.assertEqual(get.call_count, 2)
        self.assertIn("retrying", err)

    @mock.patch("weather.requests.get")
    def test_timeout_twice_fails(self, get):
        get.side_effect = requests.Timeout()
        code, out, err = run(["--action", "report", "--cache", self.cache])
        self.assertEqual(code, 1)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(out, "")
        self.assertIn("timed out", err)
        self.assertFalse(os.path.exists(self.cache))

    @mock.patch("weather.requests.get")
    def test_non_200(self, get):
        get.return_value = response(500)
        code, out, err = run(["--action", "report", "--cache", self.cache])
        self.assertEqual(code, 1)
        self.assertEqual(get.call_count, 1)  # no retry on HTTP errors
        self.assertIn("HTTP 500", err)
        self.assertNotIn("Traceback", err)
        self.assertFalse(os.path.exists(self.cache))

    def test_invalid_cached_json(self):
        with open(self.cache, "w") as fh:
            fh.write("{not json")
        with mock.patch("weather.requests.get") as get:
            code, _, err = run(["--action", "report", "--cache", self.cache])
        self.assertEqual(code, 1)
        get.assert_not_called()
        self.assertIn("invalid JSON", err)
        self.assertNotIn("Traceback", err)

    @mock.patch("weather.requests.get")
    def test_verbose_logs_to_stderr_only(self, get):
        get.return_value = response()
        _, out, err = run(["--action", "report", "-v", "--cache", self.cache])
        self.assertIn("fetching from API", err)
        self.assertIn(self.cache, err)
        self.assertIn("processed 4 records", err)
        self.assertNotIn("processed", out)


class Parsing(unittest.TestCase):
    def test_missing_daily(self):
        self.assertEqual(weather.parse_records({}), [])
        self.assertEqual(weather.parse_records({"daily": []}), [])
        self.assertEqual(weather.parse_records([]), [])

    def test_missing_time(self):
        self.assertEqual(weather.parse_records({"daily": {"weather_code": [1]}}), [])

    def test_missing_arrays(self):
        recs = weather.parse_records({"daily": {"time": ["2022-03-01"]}})
        self.assertEqual(len(recs), 1)
        self.assertIsNone(recs[0].precip)
        self.assertIsNone(recs[0].code)

    def test_mismatched_lengths(self):
        recs = weather.parse_records({"daily": {
            "time": ["2022-03-01", "2022-03-02", "2022-03-03"],
            "precipitation_sum": [1.0],
            "weather_code": [1, 2, 3, 4, 5],
        }})
        self.assertEqual([r.precip for r in recs], [1.0, None, None])
        self.assertEqual([r.code for r in recs], ["1", "2", "3"])

    def test_invalid_values_and_dates(self):
        recs = weather.parse_records({"daily": {
            "time": ["2022-03-01", "garbage", None, "2021-12-31", "2022-03-02"],
            "precipitation_sum": ["x", 1, 1, 1, -2.0],
            "weather_code": [None, 1, 1, 1, "7"],
        }})
        self.assertEqual(len(recs), 2)  # bad dates and non-2022 dropped
        self.assertEqual([r.precip for r in recs], [None, None])
        self.assertEqual([r.code for r in recs], [None, None])


def recs(precips, codes=None):
    codes = codes or [None] * len(precips)
    raw = {"daily": {
        "time": [(dt.date(2022, 1, 1) + dt.timedelta(days=i)).isoformat()
                 for i in range(len(precips))],
        "precipitation_sum": precips,
        "weather_code": codes,
    }}
    return weather.parse_records(raw)


class Reports(unittest.TestCase):
    def test_report_excludes_invalid_precip(self):
        out = weather.report(recs([0.0, 2.0, None, "bad", 0, 1]))
        self.assertEqual(out, "Total: 6 | Dry: 2 | Rainy: 2 | Rainy-day ratio: 50%")

    def test_report_rounding(self):
        self.assertIn("34%", weather.report(recs([1.0] * 124 + [0.0] * 241)))

    def test_report_empty(self):
        self.assertEqual(weather.report([]),
                         "Total: 0 | Dry: 0 | Rainy: 0 | Rainy-day ratio: 0%")

    def test_rainfall_missing_as_zero(self):
        out = weather.rainfall(recs([2.0, None, 1.0, None]))
        self.assertEqual(out, "Average rainfall per day: 0.75 mm")

    def test_rainfall_empty(self):
        self.assertEqual(weather.rainfall([]), "Average rainfall per day: 0.00 mm")

    def test_weather_codes_sorting(self):
        out = weather.weather_codes(recs(
            [0] * 8, [3, 61, 3, 0, 61, None, 3, 45]))
        self.assertEqual(out.splitlines(), [
            "3 - 3", "61 - 2", "0 - 1", "45 - 1", "unknown - 1"])

    def test_weather_codes_alpha_ties_are_string_order(self):
        out = weather.weather_codes(recs([0, 0], [61, 3]))
        self.assertEqual(out.splitlines(), ["3 - 1", "61 - 1"])


if __name__ == "__main__":
    unittest.main()
