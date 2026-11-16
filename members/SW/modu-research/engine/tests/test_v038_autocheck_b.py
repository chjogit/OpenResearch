"""v0.38 T2-1b 재검토(다른 시각) 반영: F1 재시도 · F2 직전 확인 시각 · F3 종목이 많아도 상·1등급 유지 · F4 「새로」 · F5 JSON 아닌 응답 · F6 끊김 정리는 시작 때만 · F7 벽시계 일정."""
import json
import sqlite3
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone

from mrn import autocheck as AC
from mrn import dartdocs as D
from mrn.store import Store
from tests.test_v038_autocheck import Base, FakeDart, ENV, COS, at, row


class Prev(Base):
    def test_prev_checked_at_and_gap(self):
        self.watch('005930')
        self.run_at('2026-11-12T01:00:00+00:00')
        self.fake.rows['00126380'] = [row('20261112000009')]
        self.run_at('2026-11-12T01:40:00+00:00')
        s = self.seen()['20261112000009']
        self.assertEqual(s['prev_checked_at'], '2026-11-12T01:00:00+00:00')      # 실제로 뜬 때 = 01:00~01:40 사이
        rec = AC.recent(self.store, ['005930'], now=at('2026-11-12T02:00:00+00:00'))
        self.assertEqual(rec[0]['seen_gap_min'], 40)
        self.assertTrue(rec[0]['is_new'])
        self.assertFalse(AC.recent(self.store, ['005930'], now=at('2026-11-14T02:00:00+00:00'))[0]['is_new'])   # 하루 지나면 「새로」 아님

    def test_first_check_has_no_prev(self):
        self.watch('005930')
        self.fake.rows['00126380'] = [row('20261110000001')]
        self.run_at('2026-11-12T01:00:00+00:00')
        r = AC.recent(self.store, ['005930'])[0]
        self.assertIsNone(r['prev_checked_at']); self.assertIsNone(r['seen_gap_min']); self.assertFalse(r['is_new'])

    def test_old_table_gets_column(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            st = Store(d)
            with st.lock, st.connect() as c:                               # T2-1 때의 표 모양
                c.execute('CREATE TABLE filing_seen(rcept_no TEXT PRIMARY KEY, ticker TEXT NOT NULL, corp_code TEXT, name TEXT, report_nm TEXT NOT NULL, rcept_dt TEXT NOT NULL, '
                          'filer TEXT, remark TEXT, kind TEXT, first_seen_at TEXT NOT NULL, first_check INTEGER NOT NULL DEFAULT 0, run_id INTEGER)')
                c.execute("INSERT INTO filing_seen VALUES('20261110000001','005930','1','삼성전자','x','2026-11-10','f','',NULL,'2026-11-12T01:00:00+00:00',1,1)")
            AC.ensure(st); AC.ensure(st)                                    # 두 번 불러도 됨
            with st.lock, st.connect() as c:
                cols = [r['name'] for r in c.execute('PRAGMA table_info(filing_seen)')]
                self.assertIn('prev_checked_at', cols)
                self.assertEqual(c.execute('SELECT COUNT(*) n FROM filing_seen').fetchone()['n'], 1)   # 기존 줄 유지


class ManyTickers(Base):
    def test_top_tier_not_pushed_out(self):
        """F3 재현: 관심 종목 50곳 · 회사마다 하루 2건 지분 보고 · 8일 → 그래도 11-10의 횡령·배임(상)·자기주식 취득(1등급)이 판에 있다."""
        cos = {f'{i:06d}': {'ticker': f'{i:06d}', 'corp_code': f'C{i:07d}', 'name': f'회사{i}'} for i in range(1, 51)}
        self.watch(*cos)
        n = 0
        for i, t in enumerate(cos):
            rows = []
            for day in range(5, 13):
                for k in range(2):
                    n += 1; rows.append(row(f'202611{day:02d}{n:06d}', '임원ㆍ주요주주특정증권등소유상황보고서'))
            self.fake.rows[cos[t]['corp_code']] = rows
        self.fake.rows[cos['000001']['corp_code']] += [row('20261110900001', '횡령ㆍ배임사실확인'), row('20261110900002', '주요사항보고서(자기주식취득결정)')]
        AC.check_once(self.store, 'manual', clock=lambda: at('2026-11-12T01:00:00+00:00'), get=self.fake, env=ENV, companies=cos)
        b = AC.board_view(self.store, list(cos), now=at('2026-11-12T02:00:00+00:00'))
        self.assertIn('20261110900001', [x['rcept_no'] for x in b['상']])
        self.assertIn('20261110900002', [x['rcept_no'] for x in b['computable']])
        self.assertLessEqual(len(b['하']), AC.LOW_LIMIT)

    def test_window_drops_old(self):
        self.watch('005930')
        self.fake.rows['00126380'] = [row('20261020000001', '횡령ㆍ배임사실확인')]
        with self.store.lock, self.store.connect() as c:
            c.execute("INSERT INTO autocheck_state VALUES('005930','2026-10-15','2026-10-15T00:00:00+00:00')")
        self.run_at('2026-11-12T01:00:00+00:00')
        self.assertIn('20261020000001', self.seen())                           # 기록은 남고
        self.assertEqual(AC.board_view(self.store, ['005930'], now=at('2026-11-12T01:00:00+00:00'))['상'], [])   # 판(최근 14일)에서는 빠짐


class BadResponse(Base):
    def test_html_response_is_stop_reason_not_internal(self):
        self.watch('000660', '005930')
        self.fake.fail['00164779'] = None
        def get(url, *a, **k):
            if 'corp_code=00164779' in url:
                return b'<html>\xec\xa0\x90\xea\xb2\x80 \xec\xa4\x91</html>'
            return self.fake(url)
        r = AC.check_once(self.store, 'manual', clock=lambda: at('2026-11-12T01:00:00+00:00'), get=get, env=ENV, companies=COS)
        self.assertEqual((r['status'], r['code']), ('stopped', 'dart_bad_response'))
        self.assertIn('DART 응답을 읽지 못했어요', r['message'])
        self.assertNotIn('JSONDecodeError', r['message'])

    def test_bad_total_page_and_non_dict(self):
        for body in (b'{"status":"000","list":[],"total_page":"x"}', b'[1,2]', b'\xff\xfe'):
            with self.assertRaises(D.DartDocsError) as e:
                D.list_filings('k', '1', None, '2026-11-01', '2026-11-02', lambda u, b=body: b)
            self.assertEqual(e.exception.code, 'dart_bad_response')

    def test_network_error_still_passes_through(self):
        def get(url, *a, **k):
            raise D.DartDocsError('network', 'DART 연결 실패(URLError)')
        with self.assertRaises(D.DartDocsError) as e:
            D.list_filings('k', '1', None, '2026-11-01', '2026-11-02', get)
        self.assertEqual(e.exception.code, 'network')


class Interrupted(Base):
    def test_ensure_does_not_touch_running_and_ok_clears_code(self):
        self.watch('005930')
        seen = {}
        def get(url, *a, **k):
            AC.ensure(self.store)                                              # 도는 중에 다른 곳에서 ensure가 불려도
            with self.store.lock, self.store.connect() as c:
                seen['st'] = c.execute('SELECT status, code FROM autocheck_runs ORDER BY id DESC LIMIT 1').fetchone()
            return self.fake(url)
        r = AC.check_once(self.store, 'manual', clock=lambda: at('2026-11-12T01:00:00+00:00'), get=get, env=ENV, companies=COS)
        self.assertEqual((seen['st']['status'], seen['st']['code']), ('running', None))   # 「확인 중」 그대로
        self.assertEqual((r['status'], r['code']), ('ok', None))


class Clock:
    def __init__(self):
        self.off = 0.0
    def __call__(self):
        return time.time() + self.off


class ScheduleB(Base):
    def run_sched(self, results, until, clock=None, **kw):
        calls = []
        def check(store, trigger, env=None):
            calls.append(trigger)
            return results[min(len(calls) - 1, len(results) - 1)]
        s = AC.Scheduler(self.store, env={}, delay=0, check=check, clock=clock or time.time, tick=0.01, **kw)
        s.start()
        for _ in range(400):
            if until(calls):
                break
            time.sleep(0.01)
        s.stop(); s.thread.join(5)
        return calls, s

    def test_retry_after_network_then_back_to_interval(self):
        net = {'status': 'stopped', 'code': 'network'}; ok = {'status': 'ok', 'code': None}
        calls, s = self.run_sched([net, net, net, net, ok], lambda c: len(c) >= 4, retry_sec=(0.01, 0.01, 0.01))
        time.sleep(0.1)
        self.assertEqual(calls, ['startup', 'retry', 'retry', 'retry'])            # 세 번 다시 시도한 뒤에는
        self.assertEqual(s.retry, 0)                                               # 원래 간격(60분)으로 돌아가 다섯 번째는 아직 없음
        due = datetime.fromisoformat(s.next_run_at)
        self.assertGreater((due - datetime.now(timezone.utc)).total_seconds(), 3500)

    def test_no_quick_retry_for_daily_limit(self):
        s = AC.Scheduler(self.store, env={})
        self.assertEqual(s.next_gap({'code': 'dart_020'}), (3600, 'interval'))
        self.assertEqual(s.next_gap({'code': 'usage_cap'}), (3600, 'interval'))
        self.assertEqual(s.next_gap({'code': 'network'}), (120, 'retry'))
        self.assertEqual(s.next_gap({'code': None}), (3600, 'interval'))           # 성공하면 재시도 차례도 처음으로
        self.assertEqual(s.next_gap({'code': 'network'}), (120, 'retry'))

    def test_wall_clock_jump_runs_right_away(self):
        """F7: 절전으로 시간이 훌쩍 지나면(벽시계가 다음 확인 시각을 넘으면) 바로 확인."""
        clk = Clock()
        calls = []
        def check(store, trigger, env=None):
            calls.append(trigger); return {'status': 'ok', 'code': None}
        s = AC.Scheduler(self.store, env={}, delay=0, check=check, clock=clk, tick=0.01)
        s.start()
        for _ in range(200):
            if calls:
                break
            time.sleep(0.01)
        time.sleep(0.05); self.assertEqual(len(calls), 1)                         # 60분 간격이라 아직 두 번째 없음
        clk.off = 3601                                                             # 절전에서 깨어난 것처럼 벽시계가 1시간 넘게 지남
        for _ in range(200):
            if len(calls) >= 2:
                break
            time.sleep(0.01)
        s.stop(); s.thread.join(5)
        self.assertEqual(calls[:2], ['startup', 'interval'])

    def test_start_scheduler_closes_interrupted_once(self):
        with self.store.lock, self.store.connect() as c:
            c.execute("INSERT INTO autocheck_runs(trigger,started_at,status) VALUES('interval','2026-11-12T02:00:00+00:00','running')")
        sch, old = AC.Scheduler, AC.SCHED['scheduler']                             # 실제 일정은 띄우지 않음(다른 시험에 남기지 않게 되돌림)
        try:
            AC.Scheduler = lambda store, env=None: type('X', (), {'start': lambda self: True})()
            AC.start_scheduler(self.store, env={})
        finally:
            AC.Scheduler = sch; AC.SCHED['scheduler'] = old
        self.assertEqual((AC.last_run(self.store)['status'], AC.last_run(self.store)['code']), ('stopped', 'interrupted'))


if __name__ == '__main__':
    unittest.main()
