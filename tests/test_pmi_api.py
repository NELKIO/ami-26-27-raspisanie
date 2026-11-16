"""RaspisAPI.build() на странице ПМИ: формат выгрузки для плагина Obsidian.

Run: python3 -I tests/test_pmi_api.py
Сеть закрыта, страница работает на встроенном снимке; дата зафиксирована на 16.11.2026.
"""
import functools
import threading
import unittest
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class PmiApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(ROOT)))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch(channel="chrome")
        except Exception:
            cls.browser = cls.pw.chromium.launch()
        ctx = cls.browser.new_context(timezone_id="Europe/Moscow", locale="ru-RU")
        ctx.route("https://**/*", lambda route: route.abort())
        page = ctx.new_page()
        cls.errors = []
        page.on("pageerror", lambda e: cls.errors.append(str(e)))
        page.clock.install(time=datetime(2026, 11, 16, 9, tzinfo=timezone.utc))
        page.goto(f"http://127.0.0.1:{cls.server.server_port}/index.html")
        page.wait_for_function("RaspisAPI.state() !== 'loading'")
        cls.state = page.evaluate("RaspisAPI.state()")
        cls.data = page.evaluate("RaspisAPI.build()")
        cls.day_label = page.text_content("#dayTabs") or ""

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()

    def day(self, group, iso):
        return next(d for d in self.data["groups"][group]["days"] if d["date"] == iso)

    def test_page_still_renders(self):
        self.assertEqual(self.errors, [])
        self.assertEqual(self.state, "snapshot")
        self.assertIn("ПН", self.day_label)

    def test_index(self):
        idx = self.data["index"]
        self.assertEqual(idx["version"], 1)
        self.assertEqual(idx["pinned"], ["2611-1"])
        self.assertEqual(len(idx["groups"]), 30)
        self.assertEqual(idx["times"][0], ["9:30", "10:50"])
        self.assertEqual(idx["range"]["from"], "2026-11-01")

    def test_regular_day(self):
        d = self.day("2611-1", "2026-11-16")
        self.assertEqual(d["dow"], "ПН")
        self.assertEqual((d["module"], d["week"], d["kind"]), (2, 3, ""))
        self.assertEqual([p["start"] for p in d["pairs"]], ["11:10", "13:00", "16:20"])
        first = d["pairs"][0]
        self.assertEqual((first["name"], first["type"], first["typeName"], first["sure"]),
                         ("Линейная алгебра и геометрия", "l", "Лекция", True))

    def test_online_and_stream_flags(self):
        d = self.day("2611-1", "2026-11-17")
        by_start = {p["start"]: p for p in d["pairs"]}
        self.assertTrue(by_start["19:40"]["online"])
        self.assertTrue(by_start["11:10"]["stream"])

    def test_date_lists_filter_pairs(self):
        # «05.11, 19.11, 03.12, 17.12» — матан в ЧТ 13:00 только по этим датам
        on = [p["name"] for p in self.day("2611-1", "2026-11-19")["pairs"] if p["start"] == "13:00"]
        off = [p["name"] for p in self.day("2611-1", "2026-11-26")["pairs"] if p["start"] == "13:00"]
        self.assertEqual(on, ["Математический анализ"])
        self.assertEqual(off, [])

    def test_holiday_has_no_pairs(self):
        d = self.day("2611-1", "2026-11-04")
        self.assertEqual(d["kind"], "holiday")
        self.assertEqual(d["pairs"], [])
        self.assertIn("пар нет", d["note"])

    def test_no_sundays_and_session_marked(self):
        dates = [d["date"] for d in self.data["groups"]["2611-1"]["days"]]
        self.assertNotIn("2026-11-15", dates)
        self.assertEqual(self.day("2611-1", "2026-12-21")["kind"], "session")


if __name__ == "__main__":
    unittest.main()
