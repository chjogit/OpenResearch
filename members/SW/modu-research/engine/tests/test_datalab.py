"""v0.29: 데이터랩 검색량 소급 — 키 비노출 · 이어받기 · 해시 · 기준값 상쇄 · 그날 이전만 평소 · 공개 시차 · 급증 뒤 기록 · API."""
import json, math, os, random, tempfile, unittest
from datetime import date, timedelta
from pathlib import Path
from fastapi.testclient import TestClient
from mrn import attention as A
from mrn import datalab as DL
from mrn import market
from tests.test_reaction import make_snapshot, _cut

SECRET = 'S3CRET-VALUE-xyz'
ENV = {'NAVER_HUB_ID': 'hub-id-123', 'NAVER_HUB_SECRET': SECRET}


def fake_post_factory(spikes=None, scale=None, fail_after=None):
    """데이터랩처럼 답하는 가짜: 회사마다 50±잡음, spikes={(ticker, 날짜): 배수}. 요청 안 최댓값을 100으로 맞춘다."""
    calls = {'n': 0}

    def post(url, headers, payload):
        calls['n'] += 1
        if fail_after is not None and calls['n'] > fail_after:
            return 429, b'{"errorMessage":"limit"}'
        t = payload['keywordGroups'][0]['groupName']
        rnd = random.Random(t)
        d0, d1 = date.fromisoformat(payload['startDate']), date.fromisoformat(payload['endDate'])
        vals, d = [], d0
        while d <= d1:
            v = 50 * (1 + 0.1 * rnd.uniform(-1, 1)) * (spikes or {}).get((t, d.isoformat()), 1)
            vals.append((d.isoformat(), v))
            d += timedelta(days=1)
        mx = max(v for _, v in vals)
        k = (scale or {}).get(t, 1.0)
        data = [{'period': p, 'ratio': v / mx * 100 * k} for p, v in vals]
        return 200, json.dumps({'startDate': payload['startDate'], 'endDate': payload['endDate'], 'timeUnit': 'date',
                                'results': [{'title': t, 'keywords': payload['keywordGroups'][0]['keywords'], 'data': data}]}).encode()
    post.calls = calls
    return post


class Fetch(unittest.TestCase):
    def test_credentials(self):
        m, url, h = DL.credentials(ENV)
        self.assertEqual((m, url), ('hub', DL.HUB_URL))
        self.assertEqual(h['X-NCP-APIGW-API-KEY'], SECRET)
        m, url, h = DL.credentials({'NAVER_CLIENT_ID': 'a', 'NAVER_CLIENT_SECRET': 'b'})
        self.assertEqual((m, url, h['X-Naver-Client-Id']), ('legacy', DL.LEGACY_URL, 'a'))
        with self.assertRaises(DL.DatalabError):
            DL.credentials({})
        self.assertEqual(DL.keywords('삼성전자', '005930'), ['삼성전자 주가', '삼성전자주가', '005930'])

    def test_resume_after_quota_and_no_secret_on_disk(self):
        with tempfile.TemporaryDirectory() as d:
            cos = [(f'90000{i}', f'회사{i}') for i in range(5)]
            logs = []
            with self.assertRaises(DL.DatalabError) as cm:
                DL.fetch(cos, d, '2026-01-01', '2026-03-31', fake_post_factory(fail_after=2), ENV, 0, logs.append)
            self.assertEqual(cm.exception.code, 'quota')
            post = fake_post_factory()
            snap = DL.fetch(cos, d, '2026-01-01', '2026-03-31', post, ENV, 0, logs.append)
            self.assertEqual(post.calls['n'], 3)                         # 이미 받은 2곳은 다시 부르지 않음
            self.assertEqual((Path(d) / 'LATEST.txt').read_text().strip(), snap.name)
            for p in Path(d).rglob('*'):
                if p.is_file():
                    self.assertNotIn(SECRET, p.read_text(encoding='utf-8', errors='ignore'))
            self.assertFalse(any(SECRET in x for x in logs))
            os.environ['MODU_NODES_DATALAB_DIR'] = d
            try:
                man, data = DL.load()
                self.assertEqual(len(data), 5)
                self.assertEqual(man['mode'], 'hub')
                p = next((snap / 'search').iterdir())
                p.write_text(p.read_text() + '{"date":"2026-04-01","ratio":1}\n')
                with self.assertRaises(DL.DatalabError):
                    DL.load()
            finally:
                os.environ.pop('MODU_NODES_DATALAB_DIR', None)


class Transform(unittest.TestCase):
    def test_weekend_folded_into_next_trading_day(self):
        cal = ['2026-11-06', '2026-11-09']
        att = DL.by_trading_day({'2026-11-06': 10, '2026-11-07': 20, '2026-11-08': 30, '2026-11-09': 40}, cal, '2026-11-09')
        self.assertEqual(att, {'2026-11-06': 10, '2026-11-09': 30})     # 토·일·월 평균

    def test_scale_cancels_and_prior_only(self):
        rnd = random.Random(1)
        ds = [f'd{i:03d}' for i in range(80)]
        att = {d: 50 + rnd.uniform(-5, 5) for d in ds}
        a1 = DL.asvi(att)
        a2 = DL.asvi({d: v * 0.37 for d, v in att.items()})              # 요청마다 다른 기준값(최댓값=100) → 배수는 같아야
        self.assertTrue(all(abs(a1[d] - a2[d]) < 1e-9 for d in a1))
        self.assertNotIn(ds[DL.BASE_MIN - 1], a1)                        # 이전 기록 20일 미만이면 비움
        att2 = dict(att)
        att2[ds[-1]] = 5000                                             # 마지막 날 급증이 앞날 배수를 바꾸지 않음
        a3 = DL.asvi(att2)
        self.assertTrue(all(abs(a1[d] - a3[d]) < 1e-9 for d in ds[:-1] if d in a1))


class Panel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dl = tempfile.TemporaryDirectory()
        os.environ['MODU_NODES_NEON_DIR'] = self.tmp.name
        os.environ['MODU_NODES_DATALAB_DIR'] = self.dl.name
        market._UNI.clear(); A._CACHE.clear(); A._SCACHE.clear()
        self.days, self.ev, self.cos = make_snapshot(self.tmp.name)
        self.spike_days = self.days[120:300:20]
        spikes = {(self.cos[5], d): 5.0 for d in self.spike_days}
        scale = {t: 0.2 + i * 0.03 for i, t in enumerate(self.cos)}
        DL.fetch([(t, f'회사{i}') for i, t in enumerate(self.cos)], self.dl.name, self.days[0], self.days[-1],
                 fake_post_factory(spikes, scale), ENV, 0, lambda *_: None)

    def tearDown(self):
        for k in ('MODU_NODES_NEON_DIR', 'MODU_NODES_DATALAB_DIR'):
            os.environ.pop(k, None)
        market._UNI.clear(); A._CACHE.clear(); A._SCACHE.clear()
        self.tmp.cleanup(); self.dl.cleanup()

    def test_spikes_found_and_relation_has_enough_days(self):
        sp = A.search_panel(_cut(self.days[-1]))
        mine = [e for e in sp['_spikes'] if e['ticker'] == self.cos[5]]
        self.assertEqual(sorted(e['date'] for e in mine), self.spike_days)
        self.assertTrue(all(e['asvi_adj'] >= A.SPIKE for e in mine))     # 월요일 급증은 주말과 평균돼 약해짐
        self.assertGreater(sp['relation']['strict']['n_dates'], A.MIN_DATES)
        self.assertIn(sp['relation']['strict']['verdict'], ('link', 'none'))
        self.assertIn('no_disclosure', sp['spikes'])
        # 공시 목록이 시작되기 전 급증은 「공시 없음」이 아니라 「모름」 (v0.29.1)
        self.assertTrue(sp['disclosure_from'])
        for e in mine:
            self.assertIs(e['with_disclosure'] is None, e['date'] < sp['disclosure_from'])
        self.assertEqual(sp['spikes']['unknown_disclosure']['stats']['first']['n'], sum(1 for e in sp['_spikes'] if e['with_disclosure'] is None))

    def test_publication_lag_respected(self):
        cut = _cut(self.days[200])
        sp = A.search_panel(cut)
        self.assertLess(sp['known_until'], self.days[200])               # 기준일 당일 검색량은 아직 모름
        self.assertTrue(all(d <= sp['known_until'] for m in sp['_asvi'].values() for d in m))

    def test_thermo_and_api(self):
        T = A.thermo(self.cos[5], _cut(self.days[-1]))
        self.assertTrue(T['search']['available'])
        self.assertTrue(T['search']['series'])
        self.assertEqual(len(T['search']['company_spikes']), len(self.spike_days))
        from mrn.server import create_app
        with tempfile.TemporaryDirectory() as dd:
            c = TestClient(create_app(dd, port=4395))
            j = c.get('/api/attention/search', params={'cutoff': _cut(self.days[-1])}).json()
            self.assertTrue(j['available'])
            self.assertNotIn('_spikes', j)
            self.assertEqual(j['model_calls'], 0)

    def test_without_datalab_says_how(self):
        os.environ['MODU_NODES_DATALAB_DIR'] = os.path.join(self.dl.name, 'nope')
        A._SCACHE.clear()
        T = A.thermo(self.cos[1], _cut(self.days[-1]))
        self.assertFalse(T['search']['available'])
        self.assertIn('run-datalab.cmd', T['search']['line'])


class Web(unittest.TestCase):
    def test_tool_files(self):
        root = Path(__file__).resolve().parents[1]
        ex = (root / 'local-env.example.cmd').read_text(encoding='utf-8')
        self.assertIn('NAVER_HUB_ID', ex)
        js = (root / 'web' / 'easy.js').read_text(encoding='utf-8')
        self.assertIn('검색량', js[js.index('v0.27 관심 체온계:'):])


if __name__ == '__main__':
    unittest.main()
