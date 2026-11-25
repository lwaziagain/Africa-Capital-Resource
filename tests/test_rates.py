import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect_rates import SOURCES, parse_rate, collect_rates

NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
SARB = json.dumps([{"Name": "Prime lending rate", "TimeseriesCode": "MMRD000A", "Date": "2026-11-25", "Value": 10.75},
                   {"Name": "SARB Policy Rate", "TimeseriesCode": "MMRD002A", "Date": "2026-11-25", "Value": 7.25}]).encode()
KENYA = b'<table><tr><th>Date</th><th>Rate</th></tr><tr><td>11/08/2026</td><td>8.75</td></tr><tr><td>07/10/2026</td><td>8.75</td></tr></table>'
GHANA = b'<table><tr><th>Meeting No.</th><th>MPC Dates</th><th>Effective Date</th><th>BOG Policy Rate</th></tr><tr><td>132</td><td>23-24 September</td><td>24 Sep 2026</td><td><span>14.0</span></td></tr></table>'


class Fake:
    def __init__(self, fail=False): self.fail = fail
    def fetch(self, url):
        if self.fail: raise TimeoutError("Bank unavailable")
        data = SARB if "resbank" in url else KENYA if "centralbank" in url else GHANA
        return 200, {}, data, url


class PolicyRateTests(unittest.TestCase):
    def test_sarb_selects_policy_not_prime(self):
        self.assertEqual(parse_rate(SARB, SOURCES[0], NOW), {"date": "2026-11-25", "value": 7.25})

    def test_tables_sort_dates_and_preserve_effective_date(self):
        self.assertEqual(parse_rate(KENYA, SOURCES[1], NOW)["date"], "2026-10-07")
        self.assertEqual(parse_rate(GHANA, SOURCES[2], NOW), {"date": "2026-09-24", "value": 14.0})

    def test_stale_future_and_changed_tables_rejected(self):
        for body in [KENYA.replace(b"2026", b"2020"), KENYA.replace(b"2026", b"2030"),
                     KENYA.replace(b"<th>Rate</th>", b"<th>Inflation</th>")]:
            with self.assertRaises(ValueError): parse_rate(body, SOURCES[1], NOW)

    def test_invalid_newest_rate_never_falls_back_to_old_row(self):
        body = KENYA.replace(b'07/10/2026</td><td>8.75', b'07/10/2026</td><td>unavailable')
        with self.assertRaises(ValueError): parse_rate(body, SOURCES[1], NOW)

    def test_conflicting_latest_values_rejected(self):
        body = KENYA.replace(b'</table>', b'<tr><td>07/10/2026</td><td>9.00</td></tr></table>')
        with self.assertRaises(ValueError): parse_rate(body, SOURCES[1], NOW)

    def test_failed_refresh_retains_verified_values_and_marks_delayed(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            first = collect_rates(output, Fake(), NOW)
            self.assertEqual(first["healthySources"], 3)
            second = collect_rates(output, Fake(True), NOW)
            self.assertEqual(second["status"], "error")
            for before, after in zip(first["sources"], second["sources"]):
                self.assertEqual(after["value"], before["value"])
                self.assertEqual(after["lastSuccess"], before["lastSuccess"])
                self.assertEqual(after["status"], "delayed")

    def test_initial_failure_does_not_invent_a_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            report = collect_rates(Path(directory), Fake(True), NOW)
            self.assertTrue(all("value" not in r for r in report["sources"]))


if __name__ == "__main__": unittest.main()
