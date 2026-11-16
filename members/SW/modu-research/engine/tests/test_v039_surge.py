"""v0.39 T3-1 관심회사 주가 큰 움직임 감지(KIS 현재가) → 공시 목록 바로 확인.
같은 시장 지수 대비 ±7%p · 오름·내림 모두 · 같은 거래일 한 번 · 바로 확인 하루 30번 · 키 없으면 쉼 · 연결 실패에도 멈추지 않음 · 국내 종목만 ·
답 카드에는 쓰지 않음 · 키·토큰은 화면·오류 문장에 남지 않음."""
import os, tempfile, unittest, json
from datetime import datetime, timezone, timedelta
from mrn import surge as S, autocheck as AC
from mrn.store import Store

KEY, SECRET = 'TESTKEY-abcdef123456', 'TESTSECRET-zyxw9876'
ENV = {'KIS_APP_KEY': KEY, 'KIS_APP_SECRET': SECRET}
KST = timezone(timedelta(hours=9))


def at(s):
    return lambda: datetime.fromisoformat(s)


class FakeKis:
    def __init__(self, prices, index=None, fail_index=False, fail_at=None):
        self.prices, self.idx, self.fail_index, self.fail_at, self.calls = prices, index or {'0001': '1.00', '1001': '-1.00'}, fail_index, fail_at, []

    def __call__(self, method, url, headers, body):
        self.calls.append(url)
        if self.fail_at is not None and len(self.calls) >= self.fail_at:
            raise S.KisError('network', 'KIS 연결 실패(URLError)')
        if url.endswith('/oauth2/tokenP'):
            return 200, {'access_token': 'TOKEN-secret-xyz', 'expires_in': 86400}
        q = dict(x.split('=') for x in url.split('?')[1].split('&'))
        if 'inquire-index-price' in url:
            if self.fail_index:
                return 500, {'rt_cd': '1', 'msg_cd': 'EGW00'}
            return 200, {'rt_cd': '0', 'output': {'bstp_nmix_prdy_ctrt': self.idx[q['FID_INPUT_ISCD']]}}
        t = q['FID_INPUT_ISCD']
        pct, mkt = self.prices[t]
        return 200, {'rt_cd': '0', 'output': {'stck_prpr': '10000', 'prdy_ctrt': pct, 'rprs_mrkt_kor_name': mkt}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.store = Store(self.tmp.name); AC.ensure(self.store); S.ensure(self.store)
        self.checks = []; self.tok = os.path.join(self.tmp.name, 'tok.json')

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, store, trigger, env=None):
        self.checks.append(trigger); return {'id': len(self.checks), 'status': 'ok'}

    def poll(self, fake, when='2026-11-12T02:00:00+00:00', env=ENV, tickers=('000001', '000002', '000003')):
        kis = S.Kis(KEY, SECRET, http=fake, store=self.store, clock=at(when), sleep=lambda s: None, token_path=self.tok)
        return S.poll(self.store, list(tickers), env=env, kis=kis, clock=at(when), check=self.check, names={'000001': '가회사'})


class Session(unittest.TestCase):
    def test_sessions(self):
        k = lambda s: S.session(datetime.fromisoformat(s))
        self.assertEqual(k('2026-11-12T10:00:00+09:00'), ('2026-11-12', 'open'))
        self.assertEqual(k('2026-11-12T08:59:00+09:00'), ('2026-11-11', 'closed'))         # 장 시작 전 = 전 거래일 종가
        self.assertEqual(k('2026-11-12T15:31:00+09:00'), ('2026-11-12', 'closed'))
        self.assertEqual(k('2026-11-14T12:00:00+09:00'), ('2026-11-13', 'closed'))         # 토요일 → 금요일
        self.assertEqual(k('2026-09-24T12:00:00+09:00'), ('2026-09-23', 'closed'))         # 추석 휴장 → 전 거래일


class Poll(Base):
    def test_excess_both_ways_and_one_check(self):
        f = FakeKis({'000001': ('12.00', 'KOSPI'), '000002': ('8.00', 'KOSPI200'), '000003': ('-9.00', 'KOSDAQ')}, {'0001': '3.00', '1001': '-1.00'})
        r = self.poll(f)
        self.assertEqual(r['status'], 'ok'); self.assertEqual(r['found'], ['000001', '000003'])       # 12−3=9 / 8−3=5(아님) / −9−(−1)=−8
        self.assertEqual(self.checks, ['surge']); self.assertTrue(r['checked'])
        self.assertEqual(r['calls'], 6)                                                             # 토큰 1 + 현재가 3 + 지수 2(시장마다 한 번)
        self.assertIn('기준 지수 코스피 +3.00% · 코스닥 -1.00%', r['message'])
        ev = {e['ticker']: e for e in S.board(self.store, ['000001', '000003'], clock=at('2026-11-12T03:00:00+00:00'))}
        self.assertEqual((ev['000001']['excess'], ev['000001']['mkt'], ev['000001']['name']), (9.0, 'KOSPI', '가회사'))
        self.assertEqual((ev['000003']['excess'], ev['000003']['mkt']), (-8.0, 'KOSDAQ'))
        with self.store.lock, self.store.connect() as c:
            self.assertEqual(c.execute("SELECT calls FROM kis_usage WHERE day='2026-11-12'").fetchone()[0], 6)
        r2 = self.poll(FakeKis({'000001': ('13.00', 'KOSPI'), '000002': ('1.00', 'KOSPI'), '000003': ('-9.50', 'KOSDAQ')}, {'0001': '3.00', '1001': '-1.00'}), when='2026-11-12T03:00:00+00:00')
        self.assertEqual(r2['found'], []); self.assertEqual(self.checks, ['surge'])               # 같은 거래일은 한 번만 바로 확인
        ev = {e['ticker']: e for e in S.board(self.store, ['000001'], clock=at('2026-11-12T03:00:00+00:00'))}
        self.assertEqual(ev['000001']['pct'], 13.0)                                                 # 더 크게 움직이면 값만 갱신

    def test_index_missing_falls_back_and_says_so(self):
        r = self.poll(FakeKis({'000001': ('7.50', 'KOSPI'), '000002': ('2.00', 'KOSPI'), '000003': ('1.00', 'KOSDAQ')}, fail_index=True))
        self.assertEqual(r['found'], ['000001'])
        e = S.board(self.store, ['000001'], clock=at('2026-11-12T03:00:00+00:00'))[0]
        self.assertIsNone(e['excess']); self.assertIn('지수 등락률을 받지 못해', e['note'])
        self.assertIn('기준 지수 코스피 못 받음', r['message'])

    def test_daily_cap(self):
        env = {**ENV, 'MODU_SURGE_DAILY': '1'}
        self.poll(FakeKis({'000001': ('12.00', 'KOSPI'), '000002': ('0', 'KOSPI'), '000003': ('0', 'KOSDAQ')}), env=env)
        r = self.poll(FakeKis({'000001': ('0', 'KOSPI'), '000002': ('15.00', 'KOSPI'), '000003': ('0', 'KOSDAQ')}), env=env, when='2026-11-12T04:00:00+00:00')
        self.assertEqual(r['found'], ['000002']); self.assertEqual(self.checks, ['surge']); self.assertIn('바로 확인 1번을 다 써서', r['message'])

    def test_no_key_off_and_network(self):
        f = FakeKis({})
        r = self.poll(f, env={})
        self.assertEqual((r['status'], f.calls), ('no_key', []))
        self.assertEqual(self.poll(f, env={**ENV, 'MODU_SURGE': '0'})['status'], 'off')
        r = self.poll(FakeKis({'000001': ('1', 'KOSPI'), '000002': ('1', 'KOSPI'), '000003': ('1', 'KOSPI')}, fail_at=3))
        self.assertEqual(r['status'], 'error'); self.assertIn('다음 훑기 때 다시', r['message'])

    def test_domestic_only_and_bad_ticker_continues(self):
        class F(FakeKis):
            def __call__(s, method, url, headers, body):
                if '000002' in url:
                    s.calls.append(url); return 200, {'rt_cd': '1', 'msg_cd': 'EGW00121'}
                return super().__call__(method, url, headers, body)
        f = F({'000001': ('20.00', 'KOSPI'), '000003': ('0', 'KOSDAQ')})
        r = self.poll(f, tickers=('AAPL', '000001', '000002', '000003'))
        self.assertEqual(r['found'], ['000001']); self.assertIn('000002: KIS 조회 실패', r['message'])
        self.assertFalse(any('AAPL' in u for u in f.calls))

    def test_secrets_never_in_records(self):
        self.poll(FakeKis({'000001': ('12.00', 'KOSPI'), '000002': ('0', 'KOSPI'), '000003': ('0', 'KOSDAQ')}))
        self.poll(FakeKis({}, fail_at=1), env=ENV, when='2026-11-13T02:00:00+00:00')
        with self.store.lock, self.store.connect() as c:
            dump = json.dumps([dict(r) for t in ('surge_events', 'surge_polls', 'kis_usage') for r in c.execute(f'SELECT * FROM {t}')], ensure_ascii=False)
        st = json.dumps(S.status(self.store, ['000001'], env=ENV, clock=at('2026-11-12T03:00:00+00:00')), ensure_ascii=False)
        for secret in (KEY, SECRET, 'TOKEN-secret-xyz'):
            self.assertNotIn(secret, dump); self.assertNotIn(secret, st)

    def test_board_shows_same_day_filings_only(self):
        self.poll(FakeKis({'000001': ('12.00', 'KOSPI'), '000002': ('0', 'KOSPI'), '000003': ('0', 'KOSDAQ')}))
        with self.store.lock, self.store.connect() as c:
            for no, dt in (('20261112000001', '2026-11-12'), ('20261111000002', '2026-11-11')):
                c.execute('INSERT INTO filing_seen(rcept_no,ticker,report_nm,rcept_dt,first_seen_at) VALUES(?,?,?,?,?)', (no, '000001', '단일판매ㆍ공급계약체결', dt, '2026-11-12T03:00:00+00:00'))
        e = S.board(self.store, ['000001'], clock=at('2026-11-12T03:00:00+00:00'))[0]
        self.assertEqual([f['rcept_no'] for f in e['filings']], ['20261112000001'])
        self.assertTrue(e['filings'][0]['url'].endswith('20261112000001'))


class Schedule(Base):
    def test_open_every_minutes_closed_once_per_day(self):
        calls = []
        w = S.Watcher(self.store, env=ENV, poll_fn=lambda *a, **k: calls.append(1) or {'status': 'ok'})
        t = lambda s: datetime.fromisoformat(s)
        w.step(t('2026-11-12T01:00:00+00:00')); w.step(t('2026-11-12T01:05:00+00:00')); w.step(t('2026-11-12T01:10:00+00:00'))   # 10:00 · 10:05 · 10:10 KST
        self.assertEqual(len(calls), 2)
        w.step(t('2026-11-12T07:00:00+00:00')); w.step(t('2026-11-12T09:00:00+00:00')); w.step(t('2026-11-12T22:00:00+00:00'))   # 16:00 · 18:00 · 다음날 07:00
        self.assertEqual(len(calls), 3)                                                              # 장 밖에서는 그 거래일 한 번

    def test_error_waits_before_retry(self):
        calls = []
        w = S.Watcher(self.store, env=ENV, poll_fn=lambda *a, **k: calls.append(1) or {'status': 'error'})
        t = lambda s: datetime.fromisoformat(s)
        for m in (0, 1, 2, 5, 9, 10, 11):
            w.step(t(f'2026-11-12T09:{m:02d}:00+00:00'))                                          # 18:00~ KST 장 밖, 실패가 이어짐
        self.assertEqual(len(calls), 2)                                                             # 10분 간격으로만 다시

    def test_autocheck_status_has_surge(self):
        st = AC.status(self.store, [], env={})
        self.assertIn('surge', st); self.assertFalse(st['surge']['has_key']); self.assertIn('움직인 이유는 판단하지 않아요', st['surge']['note'])

    def test_web(self):
        with open(os.path.join(os.path.dirname(__file__), '..', 'web', 'watch.js'), encoding='utf-8') as f:
            js = f.read()
        for t in ('function wSurge', '${wSurge(a.surge)}', '같은 날 공시 없음'):
            self.assertIn(t, js)
