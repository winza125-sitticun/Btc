import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import auto_scanner_v6 as scanner


class RezScannerConfigTests(unittest.TestCase):
    def setUp(self):
        scanner._REZ_WATCH_STORE = None
        scanner._REZ_WATCH_STORE_FAILED = False

    def test_rez_defaults_are_disabled_and_stable(self):
        self.assertFalse(scanner.REZ_ANALYSIS_ENABLED)
        self.assertEqual(scanner.REZ_ANALYSIS_VERSION, "REZ_V1")
        self.assertEqual(scanner.REZ_WATCH_TTL_HOURS, 12)

    def test_disabled_rez_store_is_not_constructed(self):
        self.assertFalse(scanner.REZ_ANALYSIS_ENABLED)
        with mock.patch.object(scanner, "RezWatchStore") as store_cls:
            self.assertIsNone(scanner.get_rez_watch_store())
            store_cls.assert_not_called()

    def test_enabled_rez_store_uses_shadow_db_path_and_is_cached(self):
        fake_store = object()
        with mock.patch.object(scanner, "REZ_ANALYSIS_ENABLED", True), mock.patch.object(
            scanner, "RezWatchStore", return_value=fake_store
        ) as store_cls:
            first = scanner.get_rez_watch_store()
            second = scanner.get_rez_watch_store()
        self.assertIs(first, fake_store)
        self.assertIs(second, fake_store)
        store_cls.assert_called_once_with(scanner.SHADOW_DB_PATH)

    def test_rez_store_failure_is_sticky_and_fail_closed(self):
        with mock.patch.object(scanner, "REZ_ANALYSIS_ENABLED", True), mock.patch.object(
            scanner, "RezWatchStore", side_effect=sqlite_error("boom")
        ) as store_cls:
            self.assertIsNone(scanner.get_rez_watch_store())
            self.assertIsNone(scanner.get_rez_watch_store())
        store_cls.assert_called_once()
        self.assertTrue(scanner._REZ_WATCH_STORE_FAILED)


def sqlite_error(message):
    return RuntimeError(message)


if __name__ == "__main__":
    unittest.main()
