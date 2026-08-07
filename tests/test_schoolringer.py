from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import schoolringer


def group(name: str):
    return SimpleNamespace(name=name)


class ChooseGroupTests(unittest.TestCase):
    def test_selects_requested_group(self):
        groups = [group("Tanterem"), group("Folyosó")]
        self.assertIs(schoolringer.choose_group(groups, "Folyosó"), groups[1])

    def test_reports_available_groups_for_unknown_name(self):
        with self.assertRaisesRegex(RuntimeError, "Tanterem"):
            schoolringer.choose_group([group("Tanterem")], "Udvar")

    def test_reports_empty_discovery(self):
        with self.assertRaisesRegex(RuntimeError, "Nem található"):
            schoolringer.choose_group([], None)


class DiscoveryTests(unittest.TestCase):
    @patch("schoolringer.pychromecast.get_chromecast_from_cast_info")
    @patch("schoolringer.pychromecast.discovery.discover_chromecasts")
    def test_returns_only_sorted_groups(self, discover, create_cast):
        browser = SimpleNamespace(zc=object())
        discover.return_value = (["first", "second", "third"], browser)
        create_cast.side_effect = [
            SimpleNamespace(name="Zene", cast_type="group"),
            SimpleNamespace(name="Kijelző", cast_type="cast"),
            SimpleNamespace(name="Aula", cast_type="group"),
        ]

        groups, returned_browser = schoolringer.discover_groups(7.5)

        discover.assert_called_once_with(timeout=7.5)
        self.assertIs(returned_browser, browser)
        self.assertEqual([item.name for item in groups], ["Aula", "Zene"])


class PlaybackMonitorTests(unittest.TestCase):
    def test_captures_load_failure(self):
        monitor = schoolringer.PlaybackMonitor()

        monitor.load_media_failed(queue_item_id=1, error_code=103)

        self.assertTrue(monitor.load_failed.is_set())
        self.assertEqual(monitor.error_code, 103)


class ArgumentTests(unittest.TestCase):
    def test_default_media_file(self):
        self.assertEqual(schoolringer.parse_args([]).file, Path("media/teszt.mp3"))


class MediaServerTests(unittest.TestCase):
    def test_serves_only_selected_file(self):
        media = Path(__file__)
        server = schoolringer.start_media_server(media, 0)
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(f"{base_url}/{media.name}") as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")
                self.assertEqual(response.headers["Accept-Ranges"], "bytes")
                self.assertIn(b"MediaServerTests", response.read())

            request = Request(
                f"{base_url}/{media.name}", headers={"Range": "bytes=0-9"}
            )
            with urlopen(request) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(response.headers["Content-Length"], "10")
                self.assertEqual(len(response.read()), 10)
            with self.assertRaises(HTTPError) as error:
                urlopen(f"{base_url}/../schoolringer.py")
            self.assertEqual(error.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
