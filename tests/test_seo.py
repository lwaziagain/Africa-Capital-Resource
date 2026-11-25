"""Validate crawlable identity and resources without requiring a browser."""
import json
import re
import struct
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://www.africacapitalsource.com'


class Page(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.in_head = False
        self.tags = []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        if tag == 'head':
            self.in_head = True
        self.tags.append((tag, dict(attrs), self.in_head))

    def handle_endtag(self, tag):
        if tag == 'head':
            self.in_head = False


class SearchIdentityTests(unittest.TestCase):
    def test_search_metadata_is_in_head_and_canonical_matches_page(self):
        for filename, route in [('index.html', '/'), ('about.html', '/about.html'),
                                ('editorial-standards.html', '/editorial-standards.html')]:
            with self.subTest(page=filename):
                text = (ROOT / filename).read_text()
                page = Page(text)
                self.assertEqual(sum(tag == 'head' for tag, _, _ in page.tags), 1)
                self.assertEqual(sum(tag == 'body' for tag, _, _ in page.tags), 1)
                titles = [(attrs, head) for tag, attrs, head in page.tags if tag == 'title']
                self.assertEqual(len(titles), 1)
                self.assertTrue(titles[0][1])
                metas = {attrs.get('name', attrs.get('property')): attrs.get('content')
                         for tag, attrs, head in page.tags if tag == 'meta' and head}
                self.assertTrue(metas['description'])
                self.assertEqual(metas['og:url'], ORIGIN + route)
                self.assertNotIn('noindex', metas['robots'])
                canonicals = [attrs['href'] for tag, attrs, head in page.tags
                              if tag == 'link' and head and attrs.get('rel') == 'canonical']
                self.assertEqual(canonicals, [ORIGIN + route])
                schema = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', text, re.S)[1])
                site = next(item for item in schema['@graph'] if item['@type'] == 'WebSite')
                self.assertEqual(site['name'], 'African Capital Source')
                self.assertEqual(site['alternateName'], 'ACS')
                self.assertIn('<h1>', text)
                if filename != 'index.html':
                    self.assertNotIn('<script src=', text)
                    self.assertIn('Source stories' if filename.startswith('editorial') else 'How ACS works', text)

    def test_icons_exist_with_advertised_square_dimensions(self):
        for filename, size in [('favicon-96.png', 96), ('apple-touch-icon.png', 180),
                               ('acs-icon-192.png', 192), ('acs-icon-512.png', 512)]:
            blob = (ROOT / 'assets' / filename).read_bytes()
            self.assertEqual(blob[:8], b'\x89PNG\r\n\x1a\n')
            self.assertEqual(struct.unpack('>II', blob[16:24]), (size, size))
        manifest = json.loads((ROOT / 'site.webmanifest').read_text())
        self.assertEqual(manifest['short_name'], 'ACS')
        for icon in manifest['icons']:
            self.assertTrue((ROOT / icon['src'].lstrip('/')).is_file())

    def test_sitemap_only_lists_real_canonical_pages(self):
        sitemap = ET.parse(ROOT / 'sitemap.xml')
        urls = [node.text for node in sitemap.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertEqual(len(urls), 3)
        for url in urls:
            self.assertTrue(url.startswith(ORIGIN + '/'))
            self.assertNotIn('#', url)
            self.assertTrue((ROOT / (url[len(ORIGIN)+1:] or 'index.html')).is_file())
        robots = (ROOT / 'robots.txt').read_text()
        self.assertIn('Sitemap: ' + ORIGIN + '/sitemap.xml', robots)
        self.assertNotIn('Disallow: /', robots)
        headers = json.loads((ROOT / 'vercel.json').read_text())['headers']
        self.assertNotIn('/', [entry['source'] for entry in headers])
        self.assertIn('/tests/:path*', [entry['source'] for entry in headers])
