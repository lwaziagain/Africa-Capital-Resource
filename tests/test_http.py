import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from collect import Client


class RobotsTests(unittest.TestCase):
    def test_plain_text_rules_are_requested_and_enforced(self):
        client = Client()
        client.request = Mock(return_value=(200, {},
            b'User-agent: *\nDisallow: /private/\n', 'https://example.com/robots.txt'))
        self.assertTrue(client.allowed('https://example.com/feed/'))
        self.assertFalse(client.allowed('https://example.com/private/feed/'))
        client.request.assert_called_once_with('https://example.com/robots.txt',
            {'Accept': 'text/plain, */*;q=0.1'})

    def test_access_refusal_never_becomes_permission_to_fetch_feed(self):
        for status in (403, 406, 429, 503):
            client = Client()
            client.request = Mock(side_effect=HTTPError(
                'https://example.com/robots.txt', status, 'Refused', {}, None))
            with self.assertRaisesRegex(ValueError, 'Cannot check robots.txt'):
                client.fetch('https://example.com/feed/')
            self.assertEqual(client.request.call_count, 1)

    def test_disallowed_feed_is_not_requested(self):
        client = Client()
        client.request = Mock(return_value=(200, {},
            b'User-agent: *\nDisallow: /\n', 'https://example.com/robots.txt'))
        with self.assertRaisesRegex(ValueError, 'disallows automated access'):
            client.fetch('https://example.com/feed/')
        self.assertEqual(client.request.call_count, 1)


if __name__ == '__main__':
    unittest.main()
