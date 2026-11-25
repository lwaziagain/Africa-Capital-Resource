#!/usr/bin/env python3
"""Collect publisher RSS/Atom metadata. Standard library only; never calls an AI."""
import argparse
import csv
import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

UTC = timezone.utc
AGENT = "ACSFeedCollector"
USER_AGENT = AGENT + "/1.0 (+https://www.africacapitalsource.com/)"
MAX_BYTES = 3 * 1024 * 1024
TRACKING = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src"}
CATEGORIES = {
    "crypto": r"\b(bitcoin|crypto|blockchain|ethereum|stablecoin|tokenisation)\b",
    "startups": r"\b(startup|start-up|venture capital|seed funding|series [a-f]|funding round)\b",
    "banking": r"\b(bank|banks|banking|fintech|payments|mobile money|remittance)\b",
    "etfs": r"\b(etf|etfs|unit trusts|exchange.traded fund)\b",
    "economy": r"\b(inflation|gdp|central bank|monetary policy|interest rate|budget|treasury)\b",
    "tech": r"\b(technology|software|artificial intelligence|telecom|data cent(?:re|er)|cyber|broadband|ai)\b",
    "infrastructure": r"\b(rail|railway|ports|infrastructure|logistics|solar|electricity|power grid)\b",
    "markets": r"\b(stock market|stocks|shares|jse|bourse|bond yields|forex|currency)\b",
    "personal-finance": r"\b(personal finance|retirement|pension|household savings)\b",
}
COUNTRIES = {
    "South Africa": ("Southern Africa", r"\b(south africa|south african|johannesburg|pretoria|cape town)\b"),
    "Nigeria": ("West Africa", r"\b(nigeria|nigerian|lagos|abuja)\b"),
    "Kenya": ("East Africa", r"\b(kenya|kenyan|nairobi)\b"),
    "Ghana": ("West Africa", r"\b(ghana|ghanaian|accra)\b"),
    "Egypt": ("North Africa", r"\b(egypt|egyptian|cairo)\b"),
    "Morocco": ("North Africa", r"\b(morocco|moroccan|casablanca)\b"),
    "Tanzania": ("East Africa", r"\b(tanzania|tanzanian|dar es salaam)\b"),
    "Uganda": ("East Africa", r"\b(uganda|ugandan|kampala)\b"),
    "Rwanda": ("East Africa", r"\b(rwanda|rwandan|kigali)\b"),
    "Ethiopia": ("East Africa", r"\b(ethiopia|ethiopian|addis ababa)\b"),
    "Namibia": ("Southern Africa", r"\b(namibia|namibian|windhoek)\b"),
    "Zambia": ("Southern Africa", r"\b(zambia|zambian|lusaka)\b"),
    "Zimbabwe": ("Southern Africa", r"\b(zimbabwe|zimbabwean|harare)\b"),
    "Mozambique": ("Southern Africa", r"\b(mozambique|mozambican|maputo)\b"),
    "Angola": ("Southern Africa", r"\b(angola|angolan|luanda)\b"),
    "Botswana": ("Southern Africa", r"\b(botswana|gaborone)\b"),
    "Cameroon": ("Central Africa", r"\b(cameroon|cameroonian|douala)\b"),
    "Senegal": ("West Africa", r"\b(senegal|senegalese|dakar)\b"),
    "Tunisia": ("North Africa", r"\b(tunisia|tunisian|tunis)\b"),
    "Mauritius": ("Southern Africa", r"\b(mauritius|mauritian|port louis)\b"),
}


def now_iso():
    return datetime.now(UTC).isoformat(timespec="seconds")


def read_json(path, default=None):
    if not path.exists():
        return default
    # A corrupt archive must stop the run, never silently become an empty archive.
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def canonical_url(value, base=""):
    try:
        p = urllib.parse.urlsplit(urllib.parse.urljoin(base, value.strip()))
        if p.scheme not in ("https", "http") or not p.hostname or p.username or p.password:
            return ""
        if p.port not in (None, 80, 443):
            return ""
        query = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in TRACKING]
        return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(),
                                       p.path or "/", urllib.parse.urlencode(query), ""))
    except (ValueError, AttributeError):
        return ""


def assert_public(url):
    p = urllib.parse.urlsplit(url)
    if not canonical_url(url):
        raise ValueError("Only public HTTP(S) addresses on standard ports are allowed")
    addresses = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Private or local network addresses are not permitted")


class RedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        assert_public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in ("br", "p", "div", "li"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("p", "div", "li"):
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def plain(value, limit=2000):
    parser = TextParser()
    parser.feed(value or "")
    return re.sub(r"\s+", " ", html.unescape("".join(parser.parts))).strip()[:limit]


def date_value(value):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        try:
            d = parsedate_to_datetime(value.strip())
        except (ValueError, TypeError, OverflowError):
            return None
    if not d.tzinfo:
        d = d.replace(tzinfo=UTC)
    return d.astimezone(UTC)


def local_name(tag):
    return tag.rsplit("}", 1)[-1].lower()


def child_text(node, *names):
    for name in names:
        for child in node:
            if local_name(child.tag) == name:
                return "".join(child.itertext()).strip()
    return ""


def parse_feed(raw, base):
    if len(raw) > MAX_BYTES:
        raise ValueError("Feed exceeds maximum size")
    # Reject entity declarations in common XML encodings, including UTF-16.
    probe = raw.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in probe or b"<!ENTITY" in probe:
        raise ValueError("XML document types and entities are not accepted")
    # Some publishers emit blank lines before the XML declaration. Normalize
    # only an ASCII/UTF-8 preamble; leave UTF-16 and other encodings untouched.
    xml = raw.lstrip(b" \t\r\n")
    if xml.startswith(b"\xef\xbb\xbf"):
        xml = xml[3:].lstrip(b" \t\r\n")
    root = ET.fromstring(xml)
    if local_name(root.tag) not in ("rss", "feed", "rdf"):
        raise ValueError("Response is not an RSS or Atom feed")
    entries = []
    for node in root.iter():
        if local_name(node.tag) not in ("item", "entry"):
            continue
        link = child_text(node, "link")
        for child in node:
            if local_name(child.tag) == "link" and child.get("rel", "alternate") == "alternate":
                link = child.get("href") or link
                if link:
                    break
        # Some RSS publishers omit link but supply a permalink GUID.
        if not link:
            for child in node:
                if local_name(child.tag) == "guid" and child.get("isPermaLink", "true") == "true":
                    link = child.text or ""
        url = canonical_url(link, base) if link else ""
        title = plain(child_text(node, "title"), 300)
        if not title or not url:
            continue
        entries.append({
            "url": url, "title": title,
            "description": plain(child_text(node, "description", "summary"), 2000),
            "date": child_text(node, "pubdate", "published", "date"),
            "updated": child_text(node, "updated"),
            "tags": [plain("".join(c.itertext()) or c.get("term", ""), 100)
                     for c in node if local_name(c.tag) == "category"],
        })
        if len(entries) >= 150:
            break
    return entries


class FeedLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if (tag == "link" and "alternate" in attrs.get("rel", "").lower().split()
                and attrs.get("type", "").lower() in
                ("application/rss+xml", "application/atom+xml", "application/rdf+xml")):
            self.links.append(attrs.get("href", ""))


class Client:
    def __init__(self):
        self.opener = urllib.request.build_opener(RedirectHandler())
        self.robots = {}

    def request(self, url, headers=None):
        assert_public(url)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                          "Accept": "application/rss+xml, application/atom+xml, text/xml, text/html;q=0.8",
                                          **(headers or {})})
        for attempt in range(2):
            try:
                with self.opener.open(request, timeout=15) as response:
                    body = response.read(MAX_BYTES + 1)
                    if len(body) > MAX_BYTES:
                        raise ValueError("Response exceeds maximum size")
                    return response.status, dict(response.headers), body, response.url
            except urllib.error.HTTPError as error:
                if error.code == 304:
                    return 304, dict(error.headers), b"", url
                if attempt == 0 and error.code in (500, 502, 503, 504):
                    time.sleep(1)
                    continue
                raise

    def allowed(self, url):
        p = urllib.parse.urlsplit(url)
        origin = p.scheme + "://" + p.netloc
        if origin not in self.robots:
            robot = urllib.robotparser.RobotFileParser(origin + "/robots.txt")
            try:
                _, _, body, _ = self.request(origin + "/robots.txt")
                robot.parse(body.decode("utf-8", "replace").splitlines())
            except urllib.error.HTTPError as error:
                if error.code in (404, 410):
                    robot.parse([])
                else:
                    raise ValueError("Cannot check robots.txt (HTTP %s)" % error.code)
            self.robots[origin] = robot
        return self.robots[origin].can_fetch(AGENT, url)

    def fetch(self, url, headers=None):
        if not self.allowed(url):
            raise ValueError("Source disallows automated access to this path")
        response = self.request(url, headers)
        if response[3] != url and not self.allowed(response[3]):
            raise ValueError("Redirect destination disallows automated access")
        return response


def discover(client, source, cached_url=None):
    if source.get("feed"):
        return source["feed"]
    if cached_url:
        return cached_url
    _, _, body, resolved = client.fetch(source["website"])
    links = FeedLinks()
    links.feed(body.decode("utf-8", "replace"))
    for value in links.links:
        url = canonical_url(value, resolved)
        if url and "comment" not in url.lower():
            return url
    # No guessed endpoint spray: one conventional fallback, verified by the parser.
    return urllib.parse.urljoin(resolved, "/feed/")


def classify(entry, source):
    text = entry["title"] + " " + entry["description"] + " " + " ".join(entry["tags"])
    category = source.get("category", "companies")
    # Category feeds keep the publisher's more specific classification.
    if not source.get("fixed_category"):
        category = next((name for name, pattern in CATEGORIES.items()
                         if re.search(pattern, text, re.I)), category)
    matches = [(name, region) for name, (region, pattern) in COUNTRIES.items()
               if re.search(pattern, text, re.I)]
    country, region = matches[0] if len(matches) == 1 else ("Pan-African", "Pan-African")
    return category, country, region


def make_article(entry, source, now):
    published = date_value(entry["date"])
    if published and (published > now + timedelta(days=1) or published < now - timedelta(days=30)):
        return None
    required = source.get("include_keywords", [])
    if required and not any(re.search(r"\b" + re.escape(k) + r"\b",
                                     entry["title"] + " " + entry["description"], re.I)
                            for k in required):
        return None
    category, country, region = classify(entry, source)
    # Excerpts are opt-in per publisher after reuse terms have been reviewed.
    excerpt = entry["description"] if source.get("allow_excerpt", False) else ""
    if len(excerpt) > 240:
        excerpt = excerpt[:237].rsplit(" ", 1)[0] + "…"
    return {
        "id": "feed-" + hashlib.sha256(entry["url"].encode()).hexdigest()[:24],
        "kind": "syndicated", "status": "published", "type": "Source story",
        "headline": entry["title"], "standfirst": excerpt,
        "summary": "", "body": [], "category": category, "also": [],
        "country": country, "region": region, "companies": [],
        "acsDate": now.date().isoformat(),
        "eventDate": "",  # A publisher timestamp is not the date the event happened.
        "publishedAt": published.isoformat() if published else None,
        "collectedAt": now.isoformat(timespec="seconds"), "sourceId": source["id"],
        "sources": [{"name": source["name"], "title": entry["title"], "url": entry["url"],
                     "date": published.date().isoformat() if published else "",
                     "checked": now.date().isoformat()}],
    }


def validate_articles(articles):
    if not isinstance(articles, list):
        raise ValueError("Article archive must be a JSON array")
    ids = set()
    for article in articles:
        if not isinstance(article, dict) or not isinstance(article.get("id"), str) or not article["id"]:
            raise ValueError("Each article needs a non-empty string ID")
        if article["id"] in ids:
            raise ValueError("Duplicate article ID: " + article["id"])
        ids.add(article["id"])


def collect(config, output, client=None, now=None):
    client = client or Client()
    now = now or datetime.now(UTC)
    sources = [s for s in config["sources"] if s.get("enabled")]
    if not sources:
        raise ValueError("No sources are enabled")
    if len({s["id"] for s in sources}) != len(sources):
        raise ValueError("Source IDs must be unique")
    articles_path = output / "articles.json"
    archive = read_json(articles_path, [])
    validate_articles(archive)
    state = read_json(output / "collector-state.json", {"sources": {}})
    suppressed = set(read_json(output / "suppressed-urls.json", []))
    suppressed = {canonical_url(u) for u in suppressed}
    archive = [a for a in archive if not (a.get("kind") == "syndicated" and
               any(canonical_url(s.get("url", "")) in suppressed for s in a.get("sources", [])))]
    by_id = {a["id"]: a for a in archive}
    # Respect withdrawn/manual records; never turn them back into published entries.
    known_urls = {canonical_url(s.get("url", "")) for a in archive for s in a.get("sources", [])}
    report = {"checkedAt": now.isoformat(timespec="seconds"), "newArticles": 0, "sources": []}
    healthy = 0
    for source in sources:
        old = state["sources"].get(source["id"], {})
        current = dict(old)
        result = {"id": source["id"], "name": source["name"], "website": source["website"],
                  "new": 0, "lastSuccess": old.get("lastSuccess")}
        try:
            feed_url = discover(client, source, old.get("feed"))
            headers = {}
            if old.get("feed") == feed_url:
                if old.get("etag"):
                    headers["If-None-Match"] = old["etag"]
                if old.get("lastModified"):
                    headers["If-Modified-Since"] = old["lastModified"]
            status, response_headers, raw, resolved = client.fetch(feed_url, headers)
            entries = [] if status == 304 else parse_feed(raw, resolved)
            response_headers = {k.lower(): v for k, v in response_headers.items()}
            for entry in entries:
                if entry["url"] in suppressed or entry["url"] in known_urls:
                    continue
                article = make_article(entry, source, now)
                if article is None:
                    continue
                by_id[article["id"]] = article
                known_urls.add(entry["url"])
                result["new"] += 1
            current.update({"feed": resolved, "lastSuccess": report["checkedAt"], "failures": 0})
            if status != 304:
                current["etag"] = response_headers.get("etag", "")
                current["lastModified"] = response_headers.get("last-modified", "")
            result.update({"status": "ok", "feed": resolved, "entries": len(entries),
                           "lastSuccess": report["checkedAt"]})
            healthy += 1
        except Exception as error:
            # One broken source must not prevent the other sources from updating.
            current["failures"] = old.get("failures", 0) + 1
            if current["failures"] >= 3 and not source.get("feed"):
                current.pop("feed", None)  # Rediscover on the next run.
                current.pop("etag", None)
                current.pop("lastModified", None)
            result.update({"status": "error", "error": str(error)[:240]})
        state["sources"][source["id"]] = current
        report["newArticles"] += result["new"]
        report["sources"].append(result)
    values = list(by_id.values())
    # Keep manually written/imported records; bound only the automatically collected feed.
    manual = [a for a in values if a.get("kind") != "syndicated"]
    feed = sorted((a for a in values if a.get("kind") == "syndicated"),
                  key=lambda a: a.get("publishedAt") or a.get("collectedAt", ""), reverse=True)
    archive = manual + feed[:config.get("max_feed_articles", 3000)]
    report.update({"healthySources": healthy, "totalSources": len(sources),
                   "totalArticles": sum(a.get("status") == "published" for a in archive),
                   "status": "ok" if healthy == len(sources) else "partial" if healthy else "error"})
    write_json(output / "status.json", report)
    write_json(output / "collector-state.json", state)
    if healthy or suppressed:
        write_json(articles_path, archive)
    # On complete failure leave existing articles untouched and make the job fail.
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/sources.json"))
    parser.add_argument("--output", type=Path, default=Path("data"))
    args = parser.parse_args()
    report = collect(read_json(args.config), args.output)
    print(json.dumps(report, indent=2))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        def cell(value):
            return str(value or "—").replace("|", "/").replace("\n", " ").replace("<", "&lt;")
        lines = ["## ACS collection", "",
                 "%s new stories. %s/%s sources responded." %
                 (report["newArticles"], report["healthySources"], report["totalSources"]),
                 "", "| Source | Status | New | Detail |", "|---|---|---:|---|"]
        lines += ["| %s | %s | %s | %s |" %
                  (cell(s["name"]), s["status"], s["new"], cell(s.get("error", s.get("feed"))))
                  for s in report["sources"]]
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 0 if report["healthySources"] else 1


if __name__ == "__main__":
    sys.exit(main())
