"""v0.38 T2-1 관심 종목 공시 자동 확인: 따라잡기·중복 없음·멈춤 뒤 이어 받기·사용량 상한·한국 날짜·일정."""
import json
import os
import tempfile
import threading
import unittest
import urllib.parse
from datetime import datetime, timezone
from unittest import mock

from fastapi.testclient import TestClient

from mrn import autocheck as AC
from mrn import dartdocs as D
from mrn.store import Store
from tests.test_easy import EasyBase

ENV = {'DART_API_KEY': 'test-key', 'MODU_AUTO_DOCS': '0'}     # 목록 확인만 보는 시험 — 원문 자동 받기(T2-4e)는 test_v038_t2_4e 에서
COS = {'000660': {'ticker': '000660', 'corp_code': '00164779', 'name': 'SK하이닉스'},
       '005930': {'ticker': '005930', 'corp_code': '00126380', 'name': '삼성전자'}}


def at(s):
    return datetime.fromisoformat(s)


def row(no, nm='주요사항보고서(자기주식취득결정)'):
    return {'rcept_no': no, 'report_nm': nm, 'rcept_dt': no[:8], 'flr_nm': '회사', 'rm': ''}


class FakeDart:
    def __init__(self, per=100):
        self.rows, self.calls, self.fail, self.per = {}, [], {}, per

    def __call__(self, url, *a, **k):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        self.calls.append(q)
        corp = q.get('corp_code')
        if corp in self.fail:
            code = self.fail[corp]
            if code == 'network':
                raise D.DartDocsError('network', 'DART 연결 실패(URLError)')
            return json.dumps({'status': code, 'message': 'x'}).encode()
        rs = sorted((r for r in self.rows.get(corp, []) if q['bgn_de'] <= r['rcept_dt'] <= q['end_de']), key=lambda r: r['rcept_no'])
        if not rs:
            return json.dumps({'status': '013'}).encode()
        page = int(q['page_no'])
        return json.dumps({'status': '000', 'list': rs[(page - 1) * self.per: page * self.per], 'total_page': -(-len(rs) // self.per)}).encode()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        AC.ensure(self.store)
        self.fake = FakeDart()

    def tearDown(self):
        self.tmp.cleanup()

    def watch(self, *tickers, owner='o1'):
        with self.store.lock, self.store.connect() as c:
            for t in tickers:
                c.execute('INSERT OR IGNORE INTO watchlist(owner_id,ticker,added_at) VALUES(?,?,?)', (owner, t, '2026-11-01T00:00:00+00:00'))

    def run_at(self, when, env=ENV, **kw):
        return AC.check_once(self.store, 'manual', clock=lambda: at(when), get=self.fake, env=env, companies=COS, **kw)

    def seen(self):
        with self.store.lock, self.store.connect() as c:
            return {r['rcept_no']: dict(r) for r in c.execute('SELECT * FROM filing_seen')}

    def covered(self, t):
        with self.store.lock, self.store.connect() as c:
            r = c.execute('SELECT covered_to FROM autocheck_state WHERE ticker=?', (t,)).fetchone()
        return r and r['covered_to']


class CatchUp(Base):
    def test_first_check_then_overlap_without_duplicates(self):
        self.watch('005930')
        self.fake.rows['00126380'] = [row('20261110000001'), row('20261111000002')]
        r = self.run_at('2026-11-12T01:00:00+00:00')                     # 한국 11-12 10시
        self.assertEqual((r['status'], r['new'], r['done'], r['calls']), ('ok', 2, 1, 1))
        self.assertEqual(self.fake.calls[-1]['bgn_de'], '20261105')     # 처음 등록한 회사는 최근 7일
        self.assertEqual(self.fake.calls[-1]['end_de'], '20261112')
        self.assertNotIn('pblntf_ty', self.fake.calls[-1])              # 모든 공시 유형
        self.assertEqual(self.covered('005930'), '2026-11-12')
        self.assertTrue(all(v['first_check'] == 1 for v in self.seen().values()))
        r = self.run_at('2026-11-12T03:00:00+00:00')                     # 같은 날 다시: 하루 겹쳐 보지만 중복 0
        self.assertEqual(r['new'], 0)
        self.assertEqual(self.fake.calls[-1]['bgn_de'], '20261112')
        self.fake.rows['00126380'].append(row('20261112000003', '[기재정정]현금ㆍ현물배당결정'))
        r = self.run_at('2026-11-12T08:00:00+00:00')                     # 같은 날 늦게 나온 공시도 잡힘
        self.assertEqual(r['new'], 1)
        s = self.seen()
        self.assertEqual(len(s), 3)
        self.assertEqual(s['20261112000003']['first_check'], 0)
        self.assertEqual(s['20261112000003']['kind'], 'dividend')
        self.assertEqual(s['20261112000003']['rcept_dt'], '2026-11-12')
        self.assertEqual(s['20261112000003']['first_seen_at'], '2026-11-12T08:00:00+00:00')   # 앱이 처음 본 시각

    def test_app_off_for_days_catches_up(self):
        self.watch('005930')
        self.run_at('2026-11-12T01:00:00+00:00')
        self.fake.rows['00126380'] = [row('20261115000001'), row('20261120000002'), row('20261125000003')]
        r = self.run_at('2026-11-25T01:00:00+00:00')
        self.assertEqual(self.fake.calls[-1]['bgn_de'], '20261112')     # 마지막으로 확인한 날부터
        self.assertEqual(r['new'], 3)

    def test_long_gap_is_capped_and_noted(self):
        self.watch('005930')
        with self.store.lock, self.store.connect() as c:
            c.execute("INSERT INTO autocheck_state VALUES('005930','2026-01-01','2026-01-01T00:00:00+00:00')")
        self.fake.rows['00126380'] = [row('20261001000001')]
        r = self.run_at('2026-11-12T01:00:00+00:00')
        self.assertEqual(self.fake.calls[-1]['bgn_de'], '20260814')     # 최근 90일
        self.assertIn('90일', r['notes'])
        self.assertEqual(self.seen()['20261001000001']['first_check'], 1)   # 오래 비었으면 「새 공시」로 쏟아 내지 않음

    def test_unexpected_error_and_interrupted_run_are_closed(self):
        self.watch('005930')

        def boom(url, *a, **k):
            raise ValueError('x')
        r = AC.check_once(self.store, 'manual', clock=lambda: at('2026-11-12T01:00:00+00:00'), get=boom, env=ENV, companies=COS)
        self.assertEqual((r['status'], r['code']), ('error', 'internal'))
        self.assertIsNone(self.covered('005930'))
        with self.store.lock, self.store.connect() as c:                 # 앱이 확인 도중 꺼진 경우를 흉내
            c.execute("INSERT INTO autocheck_runs(trigger,started_at,status) VALUES('interval','2026-11-12T02:00:00+00:00','running')")
        self.assertEqual(AC.close_interrupted(self.store), 1)            # 다시 켤 때(앱 시작 때 한 번만, F6)
        self.assertEqual((AC.last_run(self.store)['status'], AC.last_run(self.store)['code']), ('stopped', 'interrupted'))

    def test_clock_behind_never_asks_future_start(self):
        self.watch('005930')
        with self.store.lock, self.store.connect() as c:
            c.execute("INSERT INTO autocheck_state VALUES('005930','2026-12-01','2026-12-01T00:00:00+00:00')")
        self.run_at('2026-11-12T01:00:00+00:00')
        self.assertEqual(self.fake.calls[-1]['bgn_de'], self.fake.calls[-1]['end_de'])

    def test_korean_date_after_utc_midnight(self):
        self.watch('005930')
        self.run_at('2026-11-12T16:30:00+00:00')                         # 한국은 이미 11-13 01:30
        self.assertEqual(self.fake.calls[-1]['end_de'], '20261113')
        self.assertEqual(AC.usage(self.store, AC.kst_day(at('2026-11-12T16:30:00+00:00')))['calls'], 1)

    def test_paging_counts_every_call(self):
        self.fake.per = 2
        self.watch('005930')
        self.fake.rows['00126380'] = [row(f'2026111000000{i}') for i in range(5)]
        r = self.run_at('2026-11-12T01:00:00+00:00')
        self.assertEqual((r['new'], r['calls']), (5, 3))
        self.assertEqual(AC.usage(self.store, AC.kst_day(at('2026-11-12T01:00:00+00:00')))['calls'], 3)

    def test_odd_rows_ignored_and_subsidiary_marked(self):
        self.watch('005930')
        self.fake.rows['00126380'] = [row('20261110000001', '자회사의주요경영사항(자기주식취득결정)'), {'rcept_no': 'abc', 'report_nm': 'x', 'rcept_dt': '20261110'}]
        r = self.run_at('2026-11-12T01:00:00+00:00')
        self.assertEqual(r['new'], 1)
        rec = AC.recent(self.store, ['005930'])
        self.assertTrue(rec[0]['subsidiary'])
        self.assertTrue(rec[0]['url'].endswith('rcpNo=20261110000001'))


class Stops(Base):
    def test_network_stop_then_resume_without_loss(self):
        self.watch('000660', '005930')
        self.run_at('2026-11-12T01:00:00+00:00')
        self.fake.rows['00164779'] = [row('20261118000001')]
        self.fake.rows['00126380'] = [row('20261119000002')]
        self.fake.fail['00126380'] = 'network'                           # 두 번째 회사에서 연결이 끊김
        r = self.run_at('2026-11-20T01:00:00+00:00')
        self.assertEqual((r['status'], r['code'], r['done'], r['new']), ('stopped', 'network', 1, 1))
        self.assertIn('다음 확인 때 이어서', r['message'])
        self.assertEqual(self.covered('000660'), '2026-11-20')
        self.assertEqual(self.covered('005930'), '2026-11-12')           # 끝내지 못한 회사는 날짜를 올리지 않음
        del self.fake.fail['00126380']
        r = self.run_at('2026-11-21T01:00:00+00:00')
        self.assertEqual(r['status'], 'ok')
        self.assertIn('20261119000002', self.seen())                    # 놓친 공시 0

    def test_daily_limit_020_stops(self):
        self.watch('005930')
        self.fake.fail['00126380'] = '020'
        r = self.run_at('2026-11-12T01:00:00+00:00')
        self.assertEqual((r['status'], r['code']), ('stopped', 'dart_020'))
        self.assertIn('하루 한도', r['message'])
        self.assertIsNone(self.covered('005930'))

    def test_other_dart_error_skips_one_company_only(self):
        self.watch('000660', '005930')
        self.fake.fail['00164779'] = '100'
        self.fake.rows['00126380'] = [row('20261110000001')]
        r = self.run_at('2026-11-12T01:00:00+00:00')
        self.assertEqual((r['status'], r['done'], r['new']), ('partial', 1, 1))
        self.assertIn('000660', r['notes'])

    def test_no_key_and_empty_make_no_calls(self):
        self.watch('005930')
        r = self.run_at('2026-11-12T01:00:00+00:00', env={})
        self.assertEqual(r['status'], 'no_key'); self.assertEqual(self.fake.calls, [])
        other = Store(os.path.join(self.tmp.name, 'b')); AC.ensure(other)
        r = AC.check_once(other, 'manual', clock=lambda: at('2026-11-12T01:00:00+00:00'), get=self.fake, env=ENV, companies=COS)
        self.assertEqual(r['status'], 'empty'); self.assertEqual(self.fake.calls, [])

    def test_missing_corp_code_noted(self):
        self.watch('005930')
        r = AC.check_once(self.store, 'manual', clock=lambda: at('2026-11-12T01:00:00+00:00'), get=self.fake, env=ENV, companies={})
        self.assertEqual((r['status'], r['done']), ('partial', 0))
        self.assertIn('corp_code', r['notes'])

    def test_busy_when_another_check_runs(self):
        self.watch('005930')
        AC._RUN_LOCK.acquire()
        try:
            self.assertEqual(self.run_at('2026-11-12T01:00:00+00:00')['status'], 'busy')
        finally:
            AC._RUN_LOCK.release()
        self.assertEqual(self.run_at('2026-11-12T01:00:00+00:00')['status'], 'ok')


class Usage(Base):
    ENV_SMALL = {**ENV, 'MODU_DART_DAILY_LIMIT': '100', 'MODU_DART_LIST_STOP': '0.10', 'MODU_DART_DOC_STOP': '0.05'}   # 목록 상한 10회 · 원문 상한 5회

    def set_usage(self, day, n):
        with self.store.lock, self.store.connect() as c:
            c.execute('INSERT OR REPLACE INTO dart_usage(day,calls) VALUES(?,?)', (day, n))

    def test_list_cap_stops_before_calling(self):
        self.watch('005930')
        self.set_usage('2026-11-12', 10)
        r = self.run_at('2026-11-12T01:00:00+00:00', env=self.ENV_SMALL)
        self.assertEqual((r['status'], r['code'], r['calls']), ('stopped', 'usage_cap', 0))
        self.assertEqual(self.fake.calls, [])
        self.assertIn('상한', r['message'])
        r = self.run_at('2026-11-13T01:00:00+00:00', env=self.ENV_SMALL)   # 한국 날짜가 바뀌면 다시 0부터
        self.assertEqual(r['status'], 'ok')

    def test_doc_cap_is_lower_than_list_cap(self):
        cfg = AC.config(self.ENV_SMALL)
        self.set_usage('2026-11-12', 5)
        g = AC.counted_get(self.store, self.fake, cfg, clock=lambda: at('2026-11-12T01:00:00+00:00'))
        with self.assertRaises(D.DartDocsError) as e:
            g('https://opendart.fss.or.kr/api/document.xml?crtfc_key=k&rcept_no=20261110000001')
        self.assertEqual(e.exception.code, 'usage_cap')
        self.assertIn('원문 받기', str(e.exception))
        g('https://opendart.fss.or.kr/api/list.json?crtfc_key=k&corp_code=00126380&bgn_de=20261110&end_de=20261110&page_no=1&page_count=100')
        self.assertEqual(AC.usage(self.store, at('2026-11-12T01:00:00+00:00').date(), cfg)['calls'], 6)   # 막힌 원문 요청은 세지 않음
        self.assertNotIn('k&', str(e.exception))                          # 키·주소를 오류 문장에 남기지 않음

    def test_manual_fetch_counts_and_respects_cap(self):
        cfg = AC.config(self.ENV_SMALL)
        self.set_usage('2026-11-12', 4)                                    # 목록 1회는 되고(5회째) 원문은 상한
        root = os.path.join(self.tmp.name, 'docs')
        g = AC.counted_get(self.store, self.fake, cfg, clock=lambda: at('2026-11-12T01:00:00+00:00'))
        self.fake.rows['00126380'] = [row('20261110000001')]
        with self.assertRaises(D.DartDocsError) as e:
            D.fetch_one('005930', '20261110000001', out_root=root, get=g, env=ENV, company=COS['005930'])
        self.assertEqual(e.exception.code, 'usage_cap')                  # 목록은 확인했지만 원문은 상한이라 받지 않음
        self.assertFalse(os.path.exists(os.path.join(root, '20261110000001.zip')))

    def test_config_falls_back_on_bad_values(self):
        c = AC.config({'MODU_AUTOCHECK_MIN': 'x', 'MODU_DART_DAILY_LIMIT': '-5', 'MODU_DART_DOC_STOP': '9'})
        self.assertEqual((c['interval_min'], c['daily_limit'], c['doc_stop'], c['list_stop']), (60, 100, 1.0, 0.95))
        self.assertEqual(AC.config({'MODU_AUTOCHECK_MIN': '1'})['interval_min'], 10)   # 너무 잦은 확인은 막음
        self.assertFalse(AC.config({'MODU_AUTOCHECK': '0'})['enabled'])


class Schedule(Base):
    def test_startup_run_then_stop(self):
        done = threading.Event(); seen = []

        def fake_check(store, trigger, env=None):
            seen.append(trigger); done.set()
        s = AC.Scheduler(self.store, env={}, delay=0, check=fake_check)
        self.assertTrue(s.start())
        self.assertTrue(done.wait(5))
        s.stop(); s.thread.join(5)
        self.assertEqual(seen, ['startup'])
        self.assertFalse(s.thread.is_alive())

    def test_disabled_does_not_start(self):
        self.assertFalse(AC.Scheduler(self.store, env={'MODU_AUTOCHECK': '0'}).start())

    def test_check_failure_does_not_kill_schedule(self):
        calls = []

        def boom(store, trigger, env=None):
            calls.append(trigger)
            raise RuntimeError('x')
        s = AC.Scheduler(self.store, env={}, delay=0, check=boom)
        s.cfg['interval_min'] = 0.0005                                    # 시험에서만 아주 짧게(0.03초)
        s.start()
        for _ in range(100):
            if len(calls) >= 2:
                break
            threading.Event().wait(0.05)
        s.stop(); s.thread.join(5)
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(calls[:2], ['startup', 'interval'])


class Api(EasyBase):
    def test_status_run_and_owner_isolation(self):
        self.assertFalse(any(t.name == 'autocheck' for t in threading.enumerate()))   # 시험·create_app 만으로는 일정이 돌지 않음
        s = self.c.get('/api/watch/autocheck').json()
        for k in ('enabled', 'running', 'interval_min', 'has_key', 'usage', 'last_run', 'recent', 'note'):
            self.assertIn(k, s)
        self.assertFalse(s['running'])
        self.c.post('/api/watch', json={'ticker': '005930'})
        fake = FakeDart(); fake.rows['00126380'] = [row('20261110000001')]
        with mock.patch.dict(os.environ, ENV), mock.patch.object(D, 'http_get', fake), mock.patch.object(AC, '_companies', lambda t: COS):
            r = self.c.post('/api/watch/autocheck/run')
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()['status'], r.json()['new']), ('ok', 1))
        self.assertEqual(r.json()['status_label'], '확인 끝')
        s = self.c.get('/api/watch/autocheck').json()
        self.assertEqual([x['rcept_no'] for x in s['recent']], ['20261110000001'])
        x = s['recent'][0]                                                 # v0.38 T2-2 등급(제목만)
        self.assertEqual((x['grade'], x['rule'], x['can_compute']), (1, 'buyback', True))
        self.assertEqual([y['rcept_no'] for y in s['board']['computable']], ['20261110000001'])
        self.assertEqual(set(s['board']), {'computable', '상', '중', '하'})
        self.assertEqual(s['last_run']['status_label'], '확인 끝')
        self.assertEqual(s['usage']['calls'] >= 1, True)
        other = TestClient(self.c.app); other.get('/api/health')
        self.assertEqual(other.get('/api/watch/autocheck').json()['recent'], [])   # 남의 관심 종목 공시는 안 보임
        self.assertEqual(other.post('/api/watch/autocheck/run').status_code, 403)   # CSRF 없으면 거절

    def test_busy_is_409(self):
        AC._RUN_LOCK.acquire()
        try:
            r = self.c.post('/api/watch/autocheck/run')
        finally:
            AC._RUN_LOCK.release()
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()['detail']['code'], 'busy')


if __name__ == '__main__':
    unittest.main()
