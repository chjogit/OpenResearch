"""v0.38 T2-4a 보류 정리: T2-H1 명령창 대량 받기의 사용량 계측 · T2-H2 「지금 확인」을 뒤에서 돌리기(기존 API 는 그대로)."""
import os, sqlite3, tempfile, time, unittest
from unittest import mock

from mrn import autocheck as AC
from mrn import dartdocs as D
from mrn.store import Store
from tests.test_easy import EasyBase
from tests.test_v038_autocheck import FakeDart, ENV, COS, row


class Background(EasyBase):
    def wait_done(self, sec=10):
        t0 = time.time()
        while time.time() - t0 < sec:
            s = self.c.get('/api/watch/autocheck').json()
            if not s['checking']:
                return s
            time.sleep(0.05)
        self.fail('뒤에서 도는 확인이 끝나지 않음')

    def test_background_run_returns_at_once_and_finishes(self):
        self.assertFalse(self.c.get('/api/watch/autocheck').json()['checking'])
        self.c.post('/api/watch', json={'ticker': '005930'})
        fake = FakeDart(); fake.rows['00126380'] = [row('20261110000001')]
        with mock.patch.dict(os.environ, ENV), mock.patch.object(D, 'http_get', fake), mock.patch.object(AC, '_companies', lambda t: COS):
            r = self.c.post('/api/watch/autocheck/run?background=1')
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual((r.json()['status'], r.json()['status_label']), ('started', '확인 시작')); self.assertNotIn('thread', r.json())
            s = self.wait_done()
        self.assertEqual((s['last_run']['status'], s['last_run']['new'], s['last_run']['trigger']), ('ok', 1, 'manual'))
        self.assertEqual([x['rcept_no'] for x in s['recent']], ['20261110000001'])

    def test_old_call_still_waits_and_busy_is_409_both_ways(self):
        self.c.post('/api/watch', json={'ticker': '005930'})
        fake = FakeDart(); fake.rows['00126380'] = [row('20261110000002')]
        with mock.patch.dict(os.environ, ENV), mock.patch.object(D, 'http_get', fake), mock.patch.object(AC, '_companies', lambda t: COS):
            r = self.c.post('/api/watch/autocheck/run')                       # 예전 호출: 끝날 때까지 기다렸다가 결과를 줌
        self.assertEqual((r.status_code, r.json()['status'], r.json()['new']), (200, 'ok', 1))
        AC._RUN_LOCK.acquire()
        try:
            self.assertTrue(self.c.get('/api/watch/autocheck').json()['checking'])
            self.assertEqual(self.c.post('/api/watch/autocheck/run?background=1').status_code, 409)
            self.assertEqual(self.c.post('/api/watch/autocheck/run').status_code, 409)
        finally:
            AC._RUN_LOCK.release()

    def test_web_polls_status(self):
        js = open(os.path.join(os.path.dirname(AC.__file__), '..', 'web', 'watch.js'), encoding='utf-8').read()
        self.assertIn("autocheck/run?background=1", js); self.assertIn('a.checking', js)


class Metered(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_bulk_calls_are_counted_and_capped(self):
        seen = []
        g = D.metered_get(get=lambda url, *a, **k: seen.append(url) or b'ok', log=lambda *a: None, data_dir=self.tmp.name)
        self.assertEqual(g('https://opendart.fss.or.kr/api/list.json?x=1'), b'ok'); g('https://opendart.fss.or.kr/api/document.xml?y=2')
        st = Store(self.tmp.name)
        self.assertEqual(AC.usage(st)['calls'], 2); self.assertEqual(len(seen), 2)
        with st.lock, st.connect() as c:
            c.execute('UPDATE dart_usage SET calls=?', (AC.usage(st)['doc_stop_at'],))
        with self.assertRaises(D.DartDocsError) as e:                           # 원문 상한에 닿으면 대량 받기도 멈춤
            g('https://opendart.fss.or.kr/api/document.xml?y=3')
        self.assertEqual(e.exception.code, 'usage_cap'); self.assertEqual(len(seen), 2)
        self.assertEqual(g('https://opendart.fss.or.kr/api/list.json?x=4'), b'ok')       # 목록은 그보다 높은 상한

    def test_meter_failure_never_stops_fetch(self):
        notes = []
        with mock.patch.object(AC, 'counted_get', lambda st, get: (lambda url, *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError('database is locked')))):
            g = D.metered_get(get=lambda url, *a, **k: b'ok', log=notes.append, data_dir=self.tmp.name)
            self.assertEqual(g('u1'), b'ok'); self.assertEqual(g('u2'), b'ok')
        self.assertEqual(len(notes), 1); self.assertIn('사용량 계측에 쓰지 못한 호출', notes[0])  # 한 번만 알림
        with mock.patch.object(AC, 'ensure', lambda st: (_ for _ in ()).throw(RuntimeError('x'))):
            g = D.metered_get(get=lambda url, *a, **k: b'raw', log=notes.append, data_dir=self.tmp.name)
        self.assertEqual(g('u'), b'raw'); self.assertIn('세지 않고 받습니다', notes[-1])
        self.assertFalse(any('http' in n or 'crtfc' in n for n in notes))

    def test_cli_uses_meter(self):
        import inspect
        from mrn import dartsamples as DS
        self.assertIn('get=metered_get()', inspect.getsource(D.main)); self.assertIn('get=D.metered_get()', inspect.getsource(DS.main))


if __name__ == '__main__':
    unittest.main()
