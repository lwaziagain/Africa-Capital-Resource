import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect import parse_feed, canonical_url, collect, plain, make_article, write_json, discover
from import_archive import unwrap

NOW = datetime(2026, 11, 25, 9, tzinfo=timezone.utc)
SOURCE = {"id": "example", "name": "Example publisher", "website": "https://example.com/",
          "feed": "https://example.com/feed/", "category": "companies", "enabled": True}
RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Nigeria test bank announces a payment service</title>
<link>https://example.com/story?utm_source=rss&amp;story=1</link>
<pubDate>Wed, 25 Nov 2026 07:00:00 +0000</pubDate>
<description><![CDATA[<p>Test-only publisher excerpt.</p><script>bad()</script>]]></description>
</item></channel></rss>"""


class FakeClient:
    def __init__(self, body=RSS, status=200, error=None):
        self.body, self.status, self.error = body, status, error
        self.calls = []

    def fetch(self, url, headers=None):
        self.calls.append((url, headers))
        if self.error:
            raise self.error
        return self.status, {"ETag": '"test-etag"'}, self.body, url


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.config = {"sources": [copy.deepcopy(SOURCE)], "max_feed_articles": 3000}

    def tearDown(self):
        self.temp.cleanup()

    def run_collection(self, client=None):
        return collect(self.config, self.path, client or FakeClient(), NOW)

    def articles(self):
        return json.loads((self.path / "articles.json").read_text())

    def test_rss_is_metadata_only_and_attributed(self):
        report = self.run_collection()
        a = self.articles()[0]
        self.assertEqual(report["newArticles"], 1)
        self.assertEqual(a["country"], "Nigeria")
        self.assertEqual(a["category"], "banking")
        self.assertEqual(a["standfirst"], "")
        self.assertEqual(a["body"], [])
        self.assertEqual(a["eventDate"], "")
        self.assertEqual(a["sources"][0]["url"], "https://example.com/story?story=1")
        self.assertEqual(a["sources"][0]["name"], SOURCE["name"])

    def test_repeat_collection_and_tracking_url_do_not_duplicate(self):
        self.run_collection()
        client = FakeClient(body=RSS.replace(b"utm_source=rss", b"utm_source=email"))
        report = self.run_collection(client)
        self.assertEqual(report["newArticles"], 0)
        self.assertEqual(len(self.articles()), 1)
        self.assertEqual(client.calls[0][1]["If-None-Match"], '"test-etag"')

    def test_304_preserves_data(self):
        self.run_collection()
        previous = self.articles()
        self.assertEqual(self.run_collection(FakeClient(status=304, body=b""))["status"], "ok")
        self.assertEqual(previous, self.articles())

    def test_complete_failure_keeps_article_bytes(self):
        self.run_collection()
        previous = (self.path / "articles.json").read_bytes()
        report = self.run_collection(FakeClient(error=TimeoutError("source timed out")))
        self.assertEqual(report["status"], "error")
        self.assertEqual(previous, (self.path / "articles.json").read_bytes())
        self.assertEqual(report["sources"][0]["lastSuccess"], NOW.isoformat(timespec="seconds"))

    def test_partial_failure_does_not_block_other_sources(self):
        self.config["sources"].append({**SOURCE, "id": "broken", "feed": "https://broken.example/feed/"})
        class Partial(FakeClient):
            def fetch(self, url, headers=None):
                if "broken" in url:
                    raise ValueError("Unavailable")
                return super().fetch(url, headers)
        report = self.run_collection(Partial())
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["healthySources"], 1)
        self.assertEqual(len(self.articles()), 1)

    def test_suppression_removes_story_and_prevents_reimport(self):
        self.run_collection()
        write_json(self.path / "suppressed-urls.json", ["https://example.com/story?story=1"])
        self.run_collection()
        self.assertEqual(self.articles(), [])
        self.assertEqual(self.run_collection()["newArticles"], 0)

    def test_withdrawn_story_stays_withdrawn(self):
        self.run_collection()
        rows = self.articles()
        rows[0]["status"] = "withdrawn"
        write_json(self.path / "articles.json", rows)
        self.run_collection()
        self.assertEqual(self.articles()[0]["status"], "withdrawn")

    def test_excerpts_require_explicit_opt_in(self):
        self.config["sources"][0]["allow_excerpt"] = True
        self.run_collection()
        self.assertEqual(self.articles()[0]["standfirst"], "Test-only publisher excerpt.")

    def test_atom_namespace_relative_link_and_offset_date(self):
        atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <title>Test technology story</title><link rel="alternate" href="/story"/>
        <published>2026-11-25T08:00:00+02:00</published><category term="technology"/>
        <summary>Example text</summary></entry></feed>"""
        entry = parse_feed(atom, "https://example.com/feed/")[0]
        a = make_article(entry, SOURCE, NOW)
        self.assertEqual(entry["url"], "https://example.com/story")
        self.assertEqual(entry["tags"], ["technology"])
        self.assertEqual(a["publishedAt"], "2026-11-25T06:00:00+00:00")

    def test_missing_date_not_misrepresented_as_event_date(self):
        entry = parse_feed(RSS, SOURCE["feed"])[0]
        entry["date"] = ""
        a = make_article(entry, SOURCE, NOW)
        self.assertIsNone(a["publishedAt"])
        self.assertEqual(a["eventDate"], "")

    def test_old_and_future_stories_are_excluded(self):
        entry = parse_feed(RSS, SOURCE["feed"])[0]
        for d in ["2020-01-01T00:00:00Z", "2030-01-01T00:00:00Z"]:
            entry["date"] = d
            self.assertIsNone(make_article(entry, SOURCE, NOW))

    def test_dangerous_xml_and_html_are_rejected(self):
        for xml in [b'<!DOCTYPE rss [<!ENTITY x "bad">]><rss/>',
                    '<!DOCTYPE rss><rss/>'.encode("utf-16"), b"<html>Sign in</html>"]:
            with self.assertRaises(ValueError):
                parse_feed(xml, SOURCE["feed"])

    def test_publisher_whitespace_and_utf8_bom_before_declaration(self):
        expected = parse_feed(RSS, SOURCE["feed"])
        for prefix in [b"\n", b" \r\n\t", b"\xef\xbb\xbf\n", b"\n\xef\xbb\xbf\n"]:
            self.assertEqual(parse_feed(prefix + RSS, SOURCE["feed"]), expected)
        self.assertEqual(parse_feed(RSS.decode().encode("utf-16"), SOURCE["feed"]), expected)
        with self.assertRaises(ValueError):
            parse_feed(b'\n\xef\xbb\xbf\n<!DOCTYPE rss [<!ENTITY x "bad">]><rss/>', SOURCE["feed"])
        self.assertEqual(canonical_url("javascript:alert(1)"), "")
        self.assertEqual(canonical_url("https://user:password@example.com/"), "")
        self.assertEqual(plain("<script>bad()</script><p>Safe</p>"), "Safe")

    def test_corrupt_archive_is_never_overwritten(self):
        file = self.path / "articles.json"
        file.write_text("{bad json")
        with self.assertRaises(json.JSONDecodeError):
            self.run_collection()
        self.assertEqual(file.read_text(), "{bad json")

    def test_discovery_reads_alternate_link(self):
        client = FakeClient(body=b'<html><link rel="alternate" type="application/rss+xml" href="/news/rss"></html>')
        source = {**SOURCE, "feed": None}
        self.assertEqual(discover(client, source), "https://example.com/news/rss")

    def test_retention_preserves_manual_archive(self):
        self.run_collection()
        manual = {"id": "old-acs-report", "status": "published", "headline": "Test archive", "sources": []}
        write_json(self.path / "articles.json", self.articles() + [manual])
        self.config["max_feed_articles"] = 0
        self.run_collection()
        self.assertEqual(self.articles(), [manual])

    def test_export_unwrap_preserves_document_id(self):
        self.assertEqual(unwrap({"articles": [{"id": "a", "data": {"headline": "Test"}}]}, "articles"),
                         [{"id": "a", "headline": "Test"}])


if __name__ == "__main__":
    unittest.main()
