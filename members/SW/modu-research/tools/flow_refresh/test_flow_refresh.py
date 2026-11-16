"""flow_refresh 시험 — 가짜 사본·가짜 KIS로(네트워크 없음). 실행: (엔진 venv) python test_flow_refresh.py"""
import hashlib, importlib, json, os, sys, tempfile, unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
KST = timezone(timedelta(hours=9))
BASE = '20261115T213829+0900'


def _h(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def wdays(end, n):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5: out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def val(t, i):   # 회사·날짜 순번별 가짜 값(사본과 KIS가 같은 규칙)
    b = 1000 if t == '005930' else 3000
    return {'prsn': b + i, 'frgn': -(b + 2 * i), 'orgn': i, 'hold': f'{45 + i / 100:.4f}', 'vol': 100000 + i}


def build(root, tickers, upto):
    d = Path(root, BASE); (d / 'investor_flow_daily').mkdir(parents=True)
    days = wdays(upto, 10); parts, total = {}, 0
    for t in tickers:
        recs = []
        for i, x in enumerate(days):
            v = val(t, i)
            recs.append({'ticker': t, 'trade_date': x.isoformat(), 'individual_net_qty': v['prsn'], 'foreign_net_qty': v['frgn'],
                         'institution_net_qty': v['orgn'], 'foreign_hold_pct': v['hold'], 'volume': v['vol'], 'source': 'naver_trend', 'collected_at': 'x'})
        f = d / 'investor_flow_daily' / f'{t}.jsonl'; f.write_text(''.join(json.dumps(r, sort_keys=True) + '\n' for r in recs), encoding='utf-8')
        parts[t] = {'file': f'investor_flow_daily/{t}.jsonl', 'rows': len(recs), 'sha256': _h(f)}; total += len(recs)
    fc = d / 'company.jsonl'; fc.write_text(''.join(json.dumps({'ticker': t, 'name': t}) + '\n' for t in tickers), encoding='utf-8')
    man = {'asof_kst': BASE, 'tables': {
        'investor_flow_daily': {'partitioned': True, 'parts': parts, 'rows': total, 'source_grade': 'portal:naver', 'note': '네이버', 'query': 'q'},
        'company': {'file': 'company.jsonl', 'rows': len(tickers), 'sha256': _h(fc), 'source_grade': 'registered', 'note': '', 'query': 'q'}}}
    mp = d / 'manifest.json'; mp.write_text(json.dumps(man, ensure_ascii=False), encoding='utf-8')
    (d / 'manifest.sha256').write_text(_h(mp) + '  manifest.json\n', encoding='utf-8')
    Path(root, 'LATEST.txt').write_text(BASE + '\n', encoding='utf-8')
    return days


class FakeKis:
    def __init__(self, key, secret, **kw):
        self.key, self.secret, self.calls = key, secret, 0
        self.sleep = lambda s: None
    def token(self): return 'tok'
    def _count(self): self.calls += 1


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = self.tmp.name
        self.env = mock.patch.dict(os.environ, {'MODU_NODES_NEON_DIR': self.root, 'KIS_APP_KEY': 'k', 'KIS_APP_SECRET': 's'}); self.env.start()
        import flow_refresh as FR; self.FR = importlib.reload(FR)
        self.now = datetime(2026, 11, 13, 18, 0, tzinfo=KST)   # 금요일 장 마감 뒤
        self.days = build(self.root, ['005930', '000660'], date(2026, 11, 5))
        self.new_days = [d for d in wdays(date(2026, 11, 13), 6) if d > date(2026, 11, 5)]

    def tearDown(self):
        self.env.stop(); self.tmp.cleanup()

    def http_for(self, mism=None, hole=None, limit=None):
        alld = self.days + self.new_days
        def http(method, url, headers, body):
            q = dict(x.split('=') for x in url.split('?')[1].split('&')); t = q['FID_INPUT_ISCD']
            rows = []
            for i, d in enumerate(alld):
                v = val(t, i)
                if 'inquire-investor' in url:
                    p = v['prsn'] + (1 if mism == t and i == len(self.days) - 1 else 0)
                    rows.append({'stck_bsop_date': d.strftime('%Y%m%d'), 'prsn_ntby_qty': str(p), 'frgn_ntby_qty': str(v['frgn']), 'orgn_ntby_qty': str(v['orgn'])})
                else:
                    assert q['FID_ORG_ADJ_PRC'] == '1'
                    if hole and d == hole:
                        continue
                    ehrt = f"{float(v['hold']) * 2:.2f}" if limit == t else v['hold'][:5]   # 외국인 한도 50% 종목: 소진율 = 보유율 x 2
                    rows.append({'stck_bsop_date': d.strftime('%Y%m%d'), 'hts_frgn_ehrt': ehrt, 'acml_vol': str(v['vol']), 'frgn_ntby_qty': '999'})
            return 200, {'rt_cd': '0', 'output': rows[::-1]}
        return http

    def run_main(self, http, argv=()):
        def mk(key, secret, **kw):
            k = FakeKis(key, secret); k.http = http; return k
        class DT(datetime):
            @classmethod
            def now(cls, tz=None): return self.now if tz is None or tz == KST else self.now.astimezone(tz)
        with mock.patch.object(self.FR.SG, 'Kis', side_effect=mk), mock.patch.object(self.FR, 'datetime', DT):
            return self.FR.main(list(argv))

    def test_fills_new_days_and_switches_latest(self):
        self.assertEqual(self.run_main(self.http_for()), 0)
        latest = Path(self.root, 'LATEST.txt').read_text().strip(); self.assertNotEqual(latest, BASE)
        from mrn import market as M
        s = M.flow_series('005930', '2026-11-13T18:00:00+09:00')
        last = s['rows'][-1]; n = len(self.days) + len(self.new_days) - 1; v = val('005930', n)
        self.assertEqual(last['trade_date'], '2026-11-13')
        self.assertEqual((last['individual_net_qty'], last['foreign_net_qty'], last['institution_net_qty'], last['volume']), (v['prsn'], v['frgn'], v['orgn'], v['vol']))
        self.assertEqual(last['foreign_hold_pct'], v['hold'])                     # 사본과 같은 글자 모양(소수 4자리)
        self.assertEqual(s['source']['flows']['kis_rows'], len(self.new_days))
        self.assertTrue(Path(self.root, BASE, 'manifest.json').exists())        # 예전 사본 그대로
        man = json.loads(Path(self.root, latest, 'manifest.json').read_text(encoding='utf-8'))
        self.assertIn('kis_investor', man['tables']['investor_flow_daily']['note']); self.assertEqual(man['refresh'][-1]['companies'], 2)

    def test_mismatch_aborts_over_20pct(self):
        self.assertEqual(self.run_main(self.http_for(mism='000660')), 3)
        self.assertEqual(Path(self.root, 'LATEST.txt').read_text().strip(), BASE)

    def test_today_only_after_close(self):
        self.now = datetime(2026, 11, 13, 11, 0, tzinfo=KST)   # 장중 → 11-12 까지만
        self.assertEqual(self.run_main(self.http_for()), 0)
        from mrn import market as M
        s = M.flow_series('005930', '2026-11-13T18:00:00+09:00')
        self.assertEqual(s['rows'][-1]['trade_date'], '2026-11-12')

    def test_hole_stops_before_gap(self):
        self.assertEqual(self.run_main(self.http_for(hole=self.new_days[2])), 0)
        from mrn import market as M
        s = M.flow_series('005930', '2026-11-13T18:00:00+09:00')
        self.assertEqual(s['rows'][-1]['trade_date'], self.new_days[1].isoformat())

    def test_limit_stock_fills_nets_but_blanks_hold(self):
        self.assertEqual(self.run_main(self.http_for(limit='000660')), 0)
        from mrn import market as M
        s = M.flow_series('000660', '2026-11-13T18:00:00+09:00'); last = s['rows'][-1]
        n = len(self.days) + len(self.new_days) - 1; v = val('000660', n)
        self.assertEqual(last['trade_date'], '2026-11-13'); self.assertEqual(last['individual_net_qty'], v['prsn'])
        self.assertIsNone(last['foreign_hold_pct'])
        s2 = M.flow_series('005930', '2026-11-13T18:00:00+09:00'); self.assertIsNotNone(s2['rows'][-1]['foreign_hold_pct'])
        latest = Path(self.root, 'LATEST.txt').read_text().strip()
        man = json.loads(Path(self.root, latest, 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(man['refresh'][-1]['hold_blank'], ['000660'])

    def test_dry_and_auto(self):
        self.assertEqual(self.run_main(self.http_for(), ['--dry']), 0)
        self.assertEqual(Path(self.root, 'LATEST.txt').read_text().strip(), BASE)
        self.run_main(self.http_for())
        calls = []
        def http(*a): calls.append(a); return 200, {'rt_cd': '0', 'output': []}
        self.assertEqual(self.run_main(http, ['--auto']), 0); self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
