"""Small tests that do not start a compositor or a desktop session."""

import importlib.util
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtQml import QJSEngine

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("manager", ROOT / "manage.py")
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


class ConfigTypesTest(unittest.TestCase):
    def test_schema_namespace_and_list_types(self):
        defaults = manager.schema_defaults()["General"]
        self.assertEqual(defaults["launchers"], [])
        self.assertEqual(defaults["groupingAppIdBlacklist"], [])
        self.assertIs(defaults["showToolTips"], False)
        self.assertIs(type(defaults["iconSpacing"]), int)


class AppFilterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])
        cls.engine = QJSEngine()
        source = (
            (ROOT / "plasmoid" / manager.PLUGIN / "contents/ui/code/AudioFilter.js")
            .read_text()
            .replace(".pragma library", "")
        )
        result = cls.engine.evaluate(source)
        if result.isError():
            raise RuntimeError(result.toString())
        cls.filter = cls.engine.globalObject().property("isExcluded")

    def test_only_target_chrome_apps_are_excluded(self):
        cases = {
            "": False,
            "google-chrome": False,
            "org.kde.konsole": False,
            "crx_eilembjdkfgodjkcjnpgpaenohkicgjd": True,
            "chrome-kjbdgfilnfhdoflbpgamdcdgpehopbep-Profile_2.desktop": True,
            "CRX_EILEMBJDKFGODJKCJNPGPAENOHKICGJD": True,
            "crx_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": False,
            "aeilembjdkfgodjkcjnpgpaenohkicgjda": False,
        }
        for app_id, expected in cases.items():
            with self.subTest(app_id=app_id):
                value = self.filter.call([self.engine.toScriptValue(app_id)])
                self.assertEqual(value.toBool(), expected)


if __name__ == "__main__":
    unittest.main()
