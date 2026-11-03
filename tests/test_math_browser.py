"""Browser regressions for the math workbook migration (03.11.2026).

Run: python3 -I tests/test_math_browser.py
Requires: pip install playwright && playwright install chromium
Uses installed Google Chrome when available, otherwise Playwright Chromium.
No live Google request is needed; source cells are fixtures with synthetic meeting credentials.
"""
import functools
import io
import threading
import unittest
import zipfile
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
NEW_BOOK = "1LTYw2ORnM8EXkvIrWDpIjXCgWiXKquxYnyUJglVYIIs"
OLD_BOOK = "1_DxncTDb5oQDG55bnuLluEZSiV88ZRLyIqXFMC3weMY"
TRIVIUM = ('с 11:00 даты: 24.10, 14.11, 28.11, 12.12 и 26.12 '
           'Научно-исследовательский семинар "Тривиум. Математика" (Муравьев М.Ю.) 427')
CONTROL = '14.11 контрольная работа Геометрия и линейная алгебра (Осипов П.С.) 427'
HISTORY = '7.11 состоится занятие С: История России (1111975_53) (Новикова А.Д.) 109'
TRANSFER = 'занятие состоится вместо 4.11 нечёт нед С: Геометрия и линейная алгебра (Ровинский М.З.) 326'
ENGLISH = 'в 110 ауд. с 9:30 АНГЛИЙСКИЙ\nОСН--Мищук А.М.\n212\nМ_АЯДОКЦОК-1_С_1121012_45'
ZOOM = ('со второго модуля ОНЛАЙН 1+ НИС "Геометрия и динамика 1" '
        '(1251723) (Ольшанский Г.И., Скрипченко А.С.) 209 '
        'Ссылка для подключения к зуму: 000 0000 0000 пароль 000')
CANCELLED = ('курс аннулирован на первый семестр 3+ Research Seminar '
             '"Representations and Probability" 1 (1122325) (M.Mariani, G.I.Olshanski) 211')


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class MathBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(ROOT)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/math/'
        cls.pw = sync_playwright().start()
        chrome = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
        cls.browser = cls.pw.chromium.launch(headless=True, **({'executable_path': str(chrome)} if chrome.exists() else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.context = self.browser.new_context()
        self.context.route('https://**/*', lambda route: route.abort())
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.clock.install(time=datetime(2026, 11, 3, 12, tzinfo=timezone.utc))
        self.page.goto(self.url)
        self.page.wait_for_function("SOURCE.state !== 'loading'")

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def parse(self, text):
        return self.page.evaluate('text => parseCard(text, [])', text)

    def verdicts(self, card, dates):
        return self.page.evaluate('a => a.dates.map(d => verdict(a.card, isoDate(d)))', {'card': card, 'dates': dates})

    def course(self, text):
        return self.page.evaluate('''text => parseCourseCell({text:text, hrefs:[]},
            {year:2026, from:'2026-09-01', until:'2026-12-30'}, '')''', text)

    def test_parity_accepts_yo(self):
        card = self.parse('нечёт нед С: Геометрия и линейная алгебра (Ровинский М.З.) 209')[0]
        self.assertEqual(card.get('par'), 'odd')
        self.assertEqual(self.verdicts(card, ['2026-11-11', '2026-11-18']), ['no', 'yes'])

    def test_trivium_date_list_is_not_a_title_or_weekly_recurrence(self):
        card = self.parse(TRIVIUM)[0]
        self.assertEqual(card['n'], 'Научно-исследовательский семинар "Тривиум. Математика"')
        self.assertIn('начало в 11:00', card['d'])
        self.assertEqual(self.verdicts(card, ['2026-11-07', '2026-11-14', '2026-11-21', '2026-11-28', '2026-12-12', '2026-12-19', '2026-12-26']),
                         ['no', 'yes', 'no', 'yes', 'yes', 'no', 'yes'])

    def test_history_dates_joined_by_and_both_count(self):
        card = self.parse('21.11 и 28.11 состоится занятие С: История России (1111975_57) (Клюев А.И.) 212')[0]
        self.assertEqual(self.verdicts(card, ['2026-11-14', '2026-11-21', '2026-11-28', '2026-12-05']), ['no', 'yes', 'yes', 'no'])

    def test_control_work_does_not_merge_into_history(self):
        cards = self.parse(HISTORY + '\n\n' + CONTROL)
        self.assertEqual(len(cards), 2)
        self.assertEqual((cards[1]['k'], cards[1]['w'], cards[1]['room']), ('o', 'Осипов П.С.', '427'))
        self.assertEqual(self.verdicts(cards[0], ['2026-11-07', '2026-11-14']), ['yes', 'no'])
        self.assertEqual(self.verdicts(cards[1], ['2026-11-07', '2026-11-14']), ['no', 'yes'])

    def test_english_explicit_room_overrides_old_room(self):
        card = self.parse(ENGLISH)[0]
        self.assertEqual((card['room'], card['w'], card['lvl']), ('110', 'Мищук А.М.', 'осн'))

    def test_english_does_not_invent_a_start_date(self):
        card = self.parse(ENGLISH)[0]
        self.assertNotIn('21.09', card['d'])
        self.assertIn('начало в 9:30', card['d'])

    def test_transfer_without_new_date_stays_uncertain(self):
        card = self.parse(TRANSFER)[0]
        self.assertTrue(card.get('uncertain'))
        self.assertIn('вместо 4.11', card['d'])
        self.assertEqual(self.verdicts(card, ['2026-11-03', '2026-11-10', '2026-11-17']), ['', 'no', ''])

    def test_annulled_optional_course_is_not_scheduled(self):
        card = self.course(CANCELLED)
        self.assertTrue(card.get('cancelled'))
        self.assertEqual(self.verdicts(card, ['2026-11-05', '2026-11-12']), ['no', 'no'])

    def test_zoom_password_is_not_a_classroom(self):
        card = self.course(ZOOM)
        self.assertEqual(card.get('room'), '209')
        self.assertEqual(card.get('on'), 1)
        self.assertIn('000 0000 0000', card['d'])
        self.assertIn('пароль 000', card['d'])
        self.assertIn('со второго модуля', card['d'])

    def test_links_and_password_continuation_survive(self):
        cards = self.parse('Л: Основы российской государственности (Преподаватель А.А.) 213 : https://example.org/materials\n\nПароль для входа: 1111')
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]['links'], ['https://example.org/materials'])
        self.assertEqual(cards[0]['room'], '213')
        self.assertIn('пароль 1111', cards[0]['d'])
        self.assertEqual(self.page.evaluate("safeURL('javascript:alert(1)')"), '')

    def test_snapshot_preserves_zoom_links_but_not_plaintext_meeting_passwords(self):
        cards = self.page.evaluate('COURSE_SNAPSHOT.courses.flatMap(c => c.sessions.map(s => s.card))')
        self.assertFalse(any('пароль ' in c['d'] or 'Zoom:' in c['d'] for c in cards))
        linked = next(c for c in cards if c['courseId'] == 'rs:1122252')
        self.assertTrue(linked['links'][0].startswith('https://us02web.zoom.us/j/'))
        self.assertIn('?pwd=', linked['links'][0])
        card = next(c for c in cards if c['courseId'] == 'rs:1251723')
        self.assertIn('Реквизиты подключения — в исходной таблице', card['d'])
        self.assertIn(f'https://docs.google.com/spreadsheets/d/{NEW_BOOK}/edit?gid=1583908539', card['links'])
        self.assertEqual(card['on'], 1)
        self.page.locator('#chooseCourses').click()
        self.page.locator('[data-course="rs:1122252"]').check()
        self.page.locator('#doneCourses').click()
        self.page.locator('#datePick').fill('2026-11-11')
        self.page.locator('#datePick').dispatch_event('change')
        self.page.locator('[data-day="2"]').click()
        link = self.page.locator('[data-elective="rs:1122252"]').get_by_role('link', name='подключиться')
        self.assertEqual(link.get_attribute('href'), linked['links'][0])

    def test_old_workbook_caches_cannot_replace_new_snapshot(self):
        self.page.evaluate('''old => {
          localStorage.setItem('raspis_math_mods', JSON.stringify({t:1, source:old, d:{mods:{1:SNAPSHOT[2] || SNAPSHOT[1]}}}));
          localStorage.setItem('raspis_math_courses_v1', JSON.stringify({t:1, source:old, d:COURSE_SNAPSHOT}));
          localStorage.setItem('raspis_math_prefs_v1', JSON.stringify({v:1, group:'БМТМТ264', showEng:true, onlyReal:true, courses:['rs:1249874']}));
        }''', OLD_BOOK)
        self.page.reload()
        self.page.wait_for_function("SOURCE.state !== 'loading'")
        self.assertEqual(self.page.evaluate('Object.keys(MODS)'), ['2'])
        self.assertEqual(self.page.evaluate('SOURCE.state'), 'snapshot')
        self.assertEqual(self.page.evaluate('COURSE_SOURCE.state'), 'snapshot')
        self.assertEqual(self.page.locator('#groupName').inner_text(), 'БМТМТ264')
        self.assertEqual(self.page.locator('#showEng').get_attribute('aria-pressed'), 'true')
        self.assertEqual(self.page.locator('#onlyReal').get_attribute('aria-pressed'), 'true')
        self.assertEqual(self.page.locator('#courseCount').inner_text(), '1')
        self.assertIn(NEW_BOOK, self.page.locator('#sheetLink').get_attribute('href'))
        self.assertIn(NEW_BOOK, self.page.locator('#courseSource a').get_attribute('href'))
        self.assertEqual(self.page.locator('#modBar').is_visible(), False)
        self.assertEqual(self.page.locator('.daynote.carry').count(), 0)

    def test_new_workbook_caches_are_used_offline(self):
        self.page.evaluate('cacheSave(SNAP); courseCacheSave(COURSE_SNAPSHOT)')
        self.page.reload()
        self.page.wait_for_function("SOURCE.state !== 'loading'")
        self.assertEqual(self.page.evaluate('[SOURCE.state, COURSE_SOURCE.state]'), ['cache', 'cache'])
        self.assertEqual(self.page.evaluate('Object.keys(MODS)'), ['2'])

    def test_live_request_uses_new_workbook_and_merged_cells(self):
        html = '''<table><tr><th id="883693860R0"></th><td colspan="7">Расписание занятий на 2 модуль</td></tr>
          <tr><th></th><td></td><td></td><td></td><td>БМТМТ261</td><td colspan="2">БМТМТ262</td><td>БСБВЦ262</td></tr>
          <tr><th></th><td rowspan="2">понедельник</td><td rowspan="2">1</td><td rowspan="2">10:00-11:20</td>
            <td colspan="4">нечет нед Л: Алгебра (Кириченко В.А.) 110</td></tr>
          <tr><th></th><td>чет нед С: Алгебра (Ильин А.И.) 208</td><td colspan="2"></td><td></td></tr></table>'''
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('1бак .html', html)
        self.page.route(f'https://docs.google.com/spreadsheets/d/{NEW_BOOK}/export?format=zip',
                        lambda route: route.fulfill(body=buf.getvalue(), content_type='application/zip'))
        self.page.locator('#refresh').click()
        self.page.wait_for_function("SOURCE.state !== 'loading'")
        self.assertEqual(self.page.evaluate('SOURCE.state'), 'live')
        self.assertEqual(self.page.evaluate('Object.keys(MODS)'), ['2'])
        self.assertEqual(self.page.evaluate('Object.values(MODS[2].items).map(a => a.length)'), [2, 1, 1])
        self.assertEqual(self.page.evaluate('MODS[2].items["БМТМТ261"][1][2].par'), 'even')
        self.assertEqual(self.page.evaluate('MODS[2].times'), [['10:00', '11:20']])


if __name__ == '__main__':
    unittest.main(verbosity=2)
