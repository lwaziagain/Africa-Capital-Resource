#!/usr/bin/env python3
"""Read policy rates from official bank publications; never infer them from news."""
import argparse
import json
import math
import os
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from collect import Client, read_json, write_json

SOURCES = [
    dict(id="za", country="South Africa", bank="South African Reserve Bank",
         instrument="SARB Policy Rate", dateLabel="Observation date", maxAgeDays=10,
         url="https://custom.resbank.co.za/SarbWebApi/WebIndicators/HomePageRates",
         sourceUrl="https://www.resbank.co.za/en/home/what-we-do/statistics/key-statistics/current-market-rates"),
    dict(id="ke", country="Kenya", bank="Central Bank of Kenya",
         instrument="Central Bank Rate", dateLabel="Published rate date", maxAgeDays=120,
         url="https://www.centralbank.go.ke/rates/central-bank-rate/",
         sourceUrl="https://www.centralbank.go.ke/rates/central-bank-rate/"),
    dict(id="gh", country="Ghana", bank="Bank of Ghana",
         instrument="Monetary Policy Rate", dateLabel="Effective date", maxAgeDays=120,
         url="https://www.bog.gov.gh/monetary-policy/policy-rate-trends/",
         sourceUrl="https://www.bog.gov.gh/monetary-policy/policy-rate-trends/"),
]


class RateTables(HTMLParser):
    """Keep table boundaries so unrelated figures cannot become policy rates."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.stack, self.row, self.cell = [], [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.stack.append([])
        elif self.stack and tag == "tr":
            self.row = []
        elif self.row is not None and tag in ("td", "th"):
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.stack:
                self.stack[-1].append(self.row)
            self.row = None
        elif tag == "table" and self.stack:
            self.tables.append(self.stack.pop())


def rate_number(value):
    if isinstance(value, bool):
        raise ValueError("Invalid policy rate")
    if isinstance(value, str):
        if not re.fullmatch(r"\d+(?:\.\d+)?\s*%?", value.strip()):
            raise ValueError("Invalid policy rate")
        value = value.strip().rstrip("%").strip()
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 100:
        raise ValueError("Policy rate outside expected range")
    return number


def rate_date(value):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError("Invalid rate date")


def parse_rate(raw, source, now):
    if source["id"] == "za":
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("SARB response is not a list")
        matches = [r for r in data if r.get("TimeseriesCode") == "MMRD002A"
                   and r.get("Name", "").lower() in ("sarb policy rate", "repo rate", "repurchase rate")]
        if len(matches) != 1:
            raise ValueError("SARB policy-rate series missing or ambiguous")
        points = [(rate_date(matches[0]["Date"]), rate_number(matches[0]["Value"]))]
    else:
        parser = RateTables()
        parser.feed(raw.decode("utf-8-sig"))
        points = []
        expected = ("date", "rate") if source["id"] == "ke" else ("effective date", "bog policy rate")
        for table in parser.tables:
            columns = None
            for row in table:
                labels = [x.lower().strip() for x in row]
                if all(name in labels for name in expected):
                    columns = [labels.index(name) for name in expected]
                    continue
                if columns is None or len(row) <= max(columns):
                    continue
                try:
                    day = rate_date(row[columns[0]])
                except (ValueError, TypeError):
                    # Filter/header rows are not observations.
                    continue
                points.append((day, rate_number(row[columns[1]])))
        if not points:
            raise ValueError("Official policy-rate table missing or changed")
    today = now.date().isoformat()
    points = [p for p in points if p[0] <= today]
    if not points:
        raise ValueError("No effective observation yet")
    latest = max(p[0] for p in points)
    values = {v for d, v in points if d == latest}
    if len(values) != 1:
        raise ValueError("Conflicting policy rates for the latest date")
    if (now.date() - datetime.fromisoformat(latest).date()).days > source["maxAgeDays"]:
        raise ValueError("Source table is out of date (latest: %s)" % latest)
    return {"date": latest, "value": values.pop()}


def collect_rates(output, client=None, now=None):
    client = client or Client()
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="seconds")
    path = output / "policy-rates.json"
    old = read_json(path, {"sources": []})
    if not isinstance(old, dict) or not isinstance(old.get("sources"), list):
        raise ValueError("Invalid saved policy-rate data")
    previous = {s["id"]: s for s in old["sources"]}
    rows = []
    for source in SOURCES:
        row = {**source, "checkedAt": stamp, "status": "unavailable"}
        try:
            status, _, raw, _ = client.fetch(source["url"])
            if status != 200:
                raise ValueError("Unexpected source response")
            point = parse_rate(raw, source, now)
            saved = previous.get(source["id"], {})
            if saved.get("date", "") > point["date"]:
                raise ValueError("Source returned an older record than the saved rate")
            row.update(point, status="ok", lastSuccess=stamp)
        except Exception as error:
            saved = previous.get(source["id"], {})
            if isinstance(saved.get("value"), (int, float)) and saved.get("date"):
                row.update({k: saved[k] for k in ("value", "date", "lastSuccess") if k in saved})
                row["status"] = "delayed"
            row["error"] = str(error)[:240]
        rows.append(row)
    healthy = sum(s["status"] == "ok" for s in rows)
    report = {"checkedAt": stamp, "healthySources": healthy, "totalSources": len(rows),
              "status": "ok" if healthy == len(rows) else "partial" if healthy else "error", "sources": rows}
    write_json(path, report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        lines = ["\n## Official policy rates", "", "| Country | Status | Rate (%) | Source date |", "|---|---|---:|---|"]
        lines += ["| %s | %s | %s | %s |" % (r["country"], r["status"], r.get("value", "—"), r.get("date", "—")) for r in rows]
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data"))
    result = collect_rates(parser.parse_args().output)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["healthySources"] else 1)
