"""price_refresh 시험 — 가짜 사본·가짜 KIS로(네트워크 없음). 실행: (엔진 venv) python test_price_refresh.py"""
import hashlib, importlib, json, os, sys, tempfile, unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
KST = timezone(timedelta(hours=9))


def _h(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def wdays(end, n):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5: out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def build(root, tickers, upto):
    name = '20261107T005213+0900'; d = Path(root, name); (d / 'price_daily').mkdir(parents=True)
    days = wdays(upto, 10)
    parts, total = {}, 0
    for t, base in tickers.items():
        recs = [{'ticker': t, 'trade_date': x.isoformat(), 'open': str(base + i), 'high': str(base + i), 'low': str(base + i), 'close': str(base + i),
                 'volume': 100, 'trade_value': '1', 'market_cap': str((base + i) * 1000), 'source': 'fsc', 'collected_at': 'x'} for i, x in enumerate(days)]
        f = d / 'price_daily' / f'{t}.jsonl'; f.write_text(''.join(json.dumps(r, sort_keys=True) + '\n' for r in recs), encoding='utf-8')
        parts[t] = {'file': f'price_daily/{t}.jsonl', 'rows': len(recs), 'sha256': _h(f)}; total += len(recs)
    idx = [{'symbol': '^KS11', 'name': '코스피', 'trade_date': x.isoformat(), 'open': '1', 'high': '1', 'low': '1', 'close': str(5000 + i), 'volume': 1,
            'source': 'yfinance', 'collected_at': 'x'} for i, x in enumerate(days)]
    fi = d / 'market_index_daily.jsonl'; fi.write_text(''.join(json.dumps(r, sort_keys=True) + '\n' for r in idx), encoding='utf-8')
    fc = d / 'company.jsonl'; fc.write_text(''.join(json.dumps({'ticker': t, 'name': t}) + '\n' for t in tickers), encoding='utf-8')
    man = {'asof_kst': name, 'tables': {
        'price_daily': {'partitioned': True, 'parts': parts, 'rows': total, 'source_grade': 'public:fsc', 'note': '국내 기업, 금융위(fsc) 행만', 'query': 'q'},
        'market_index_daily': {'file': 'market_index_daily.jsonl', 'rows': len(idx), 'sha256': _h(fi), 'source_grade': 'unofficial:yfinance', 'note': '비공식', 'query': 'q'},
        'company': {'file': 'company.jsonl', 'rows': len(tickers), 'sha256': _h(fc), 'source_grade': 'registered', 'note': '', 'query': 'q'}}}
    mp = d / 'manifest.json'; mp.write_text(json.dumps(man, ensure_ascii=False), encoding='utf-8')
    (d / 'manifest.sha256').write_text(_h(mp) + '  manifest.json\n', encoding='utf-8')
    Path(root, 'LATEST.txt').write_text(name + '\n', encoding='utf-8')
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
        import price_refresh as PR; self.PR = importlib.reload(PR)
        self.now = datetime(2026, 11, 13, 18, 0, tzinfo=KST)   # 금요일 장 마감 뒤
        self.days = build(self.root, {'005930': 200000, '000660': 500000}, date(2026, 11, 5))
        self.new_days = [d for d in wdays(date(2026, 11, 13), 6) if d > date(2026, 11, 5)]

    def tearDown(self):
        self.env.stop(); self.tmp.cleanup()

    def http_for(self, mism=None, idx_bad=False):
        days, newd = self.days, self.new_days
        def http(method, url, headers, body):
            q = dict(x.split('=') for x in url.split('?')[1].split('&'))
            if 'indexchart' in url:
                rows = [{'stck_bsop_date': d.strftime('%Y%m%d'), 'bstp_nmix_prpr': str((5000 + i) * (1.01 if idx_bad else 1)), 'acml_vol': '9'} for i, d in enumerate(days)]
                rows += [{'stck_bsop_date': d.strftime('%Y%m%d'), 'bstp_nmix_prpr': '5100.5', 'acml_vol': '9'} for d in newd]
                return 200, {'rt_cd': '0', 'output2': rows[::-1]}
            t = q['FID_INPUT_ISCD']; base = 200000 if t == '005930' else 500000
            assert q['FID_ORG_ADJ_PRC'] == '1'
            rows = [{'stck_bsop_date': d.strftime('%Y%m%d'), 'stck_clpr': str(base + i + (1 if mism == t and i == len(days) - 1 else 0)), 'stck_oprc': '1', 'stck_hgpr': '1', 'stck_lwpr': '1', 'acml_vol': '5', 'acml_tr_pbmn': '7'} for i, d in enumerate(days)]
            rows += [{'stck_bsop_date': d.strftime('%Y%m%d'), 'stck_clpr': str(base + 100 + j), 'stck_oprc': '1', 'stck_hgpr': '1', 'stck_lwpr': '1', 'acml_vol': '5', 'acml_tr_pbmn': '7'} for j, d in enumerate(newd)]
            return 200, {'rt_cd': '0', 'output2': rows[::-1]}
        return http

    def run_main(self, http, argv=()):
        def mk(key, secret, **kw):
            k = FakeKis(key, secret); k.http = http; return k
        class DT(datetime):
            @classmethod
            def now(cls, tz=None): return self.now if tz is None or tz == KST else self.now.astimezone(tz)
        with mock.patch.object(self.PR.SG, 'Kis', side_effect=mk), mock.patch.object(self.PR, 'datetime', DT):
            return self.PR.main(list(argv))

    def test_fills_new_days_and_switches_latest(self):
        self.assertEqual(self.run_main(self.http_for()), 0)
        latest = Path(self.root, 'LATEST.txt').read_text().strip()
        self.assertNotEqual(latest, '20261107T005213+0900')
        from mrn import market as M
        s = M.price_series('005930', '2026-11-13T18:00:00+09:00')
        self.assertEqual(s['rows'][-1]['trade_date'], '2026-11-13'); self.assertEqual(s['rows'][-1]['close'], str(200000 + 100 + len(self.new_days) - 1))
        self.assertEqual(s['source']['kis_rows'], len(self.new_days))
        mc = int(s['rows'][-1]['market_cap']); self.assertEqual(mc, int(s['rows'][-1]['close']) * 1000)   # 주식 수 그대로
        self.assertTrue(Path(self.root, '20261107T005213+0900', 'manifest.json').exists())        # 예전 사본 그대로
        idx, _ = M.index_series('2026-11-13T18:00:00+09:00')
        self.assertEqual(idx[-1], ('2026-11-13', '5100.5'))
        man = json.loads(Path(self.root, latest, 'manifest.json').read_text(encoding='utf-8'))
        self.assertIn('kis', man['tables']['price_daily']['note']); self.assertEqual(man['refresh'][0]['companies'], 2)

    def test_mismatch_skips_that_company_only(self):
        self.assertEqual(self.run_main(self.http_for(mism='000660')), 3)   # 1/2 = 50% > 20% → 아무것도 안 바꿈
        self.assertEqual(Path(self.root, 'LATEST.txt').read_text().strip(), '20261107T005213+0900')

    def test_index_mismatch_not_filled(self):
        self.assertEqual(self.run_main(self.http_for(idx_bad=True)), 0)
        from mrn import market as M
        idx, _ = M.index_series('2026-11-13T18:00:00+09:00')
        self.assertEqual(idx[-1][0], '2026-11-05')

    def test_dry_and_auto(self):
        self.assertEqual(self.run_main(self.http_for(), ['--dry']), 0)
        self.assertEqual(Path(self.root, 'LATEST.txt').read_text().strip(), '20261107T005213+0900')
        self.run_main(self.http_for())
        calls = []
        def http(*a): calls.append(a); return 200, {'rt_cd': '0', 'output2': []}
        self.assertEqual(self.run_main(http, ['--auto']), 0); self.assertEqual(calls, [])   # 이미 최신 → KIS 안 부름


    def test_wrong_kis_row_is_corrected_fsc_untouched(self):
        """v0.39.6: 예전에 KIS로 채운 마지막 날 종가가 지금 KIS와 다르면 바로잡음(금융위 행은 그대로)."""
        self.assertEqual(self.run_main(self.http_for()), 0)                     # 11-06~11-13 을 KIS로 채움
        from mrn import market as M
        root = M.resolve(''); man = M.load_manifest(root)
        rows, _ = M.read_rows(root, man, 'price_daily', '005930')
        bad_day = rows[-1]['trade_date']; good_close = rows[-1]['close']
        # 사본의 마지막 KIS 행 종가를 일부러 틀리게(주말에 받은 값이 달랐던 상황) → 새 사본으로 만들어 둠
        p = root / man['tables']['price_daily']['parts']['005930']['file']
        lines = p.read_text(encoding='utf-8').splitlines()
        r = json.loads(lines[-1]); r['close'] = str(int(r['close']) + 3000); lines[-1] = json.dumps(r, sort_keys=True)
        p.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        man2 = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        man2['tables']['price_daily']['parts']['005930']['sha256'] = _h(p)
        (root / 'manifest.json').write_text(json.dumps(man2, ensure_ascii=False), encoding='utf-8')
        (root / 'manifest.sha256').write_text(_h(root / 'manifest.json') + '  manifest.json\n', encoding='utf-8')
        self.now = datetime(2026, 11, 16, 17, 0, tzinfo=KST)                     # 다음 거래일 장 마감 뒤 → 다시 대조
        self.assertEqual(self.run_main(self.http_for()), 0)
        root = M.resolve(''); man = M.load_manifest(root)
        rows, _ = M.read_rows(root, man, 'price_daily', '005930')
        fixed = [x for x in rows if x['trade_date'] == bad_day]
        self.assertEqual([x['close'] for x in fixed], [good_close])              # 바로잡힘(줄 수는 그대로)
        self.assertEqual(len([x for x in rows if x['source'] == 'fsc']), 10)     # 금융위 행 그대로
        self.assertEqual(man['refresh'][-1]['corrected_kis_rows'], {'005930': [bad_day]})

    def test_fsc_mismatch_still_stops(self):
        """금융위 원본 행이 다르면 바로잡지 않고 예전처럼 멈춤"""
        self.assertEqual(self.run_main(self.http_for(mism='000660')), 3)
        self.assertEqual(Path(self.root, 'LATEST.txt').read_text().strip(), '20261107T005213+0900')


if __name__ == '__main__':
    unittest.main()
