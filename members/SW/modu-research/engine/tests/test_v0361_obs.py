"""v0.36.1 관측 묶음: T06 시세 품질 검사 · N09 RSI(14) · N10 기간 변동성·드문 패턴 후보 · N07 유동성 묶음."""
import json, math, os, unittest
from mrn import nodes as N
from mrn.market import price_quality
from tests.test_flow import Base, build, doc, _h, _w


def rewrite_prices(d, fn):
    """사본의 price_daily 를 고친 뒤 해시를 다시 맞춘다."""
    p = os.path.join(d, 'price_daily.jsonl')
    rows = [json.loads(x) for x in open(p, encoding='utf-8') if x.strip()]
    rows = fn(rows)
    _w(p, ''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in rows))
    mp = os.path.join(d, 'manifest.json'); man = json.load(open(mp, encoding='utf-8'))
    man['tables']['price_daily'].update(rows=len(rows), sha256=_h(p)); _w(mp, json.dumps(man))
    _w(os.path.join(d, 'manifest.sha256'), _h(mp) + '  manifest.json\n')


def liq_doc():
    d = doc(); d['edges'].append({'from_node': 't06', 'from_port': 'prices', 'to_node': 'n07', 'to_port': 'prices'})
    d['nodes'].append({'id': 'n09', 'type': 'N09', 'config': {}})
    d['edges'].append({'from_node': 't06', 'from_port': 'prices', 'to_node': 'n09', 'to_port': 'prices'})
    return d


class Helpers(unittest.TestCase):
    def test_rsi_extremes_and_hand_value(self):
        self.assertEqual(N._rsi14([100.0 + i for i in range(40)]), 100.0)          # 하락이 한 번도 없음
        self.assertAlmostEqual(N._rsi14([100.0 - i for i in range(40)]), 0.0)
        self.assertIsNone(N._rsi14([1.0] * 14))                                    # 15개 미만
        c = [10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10]           # 상승 7번(+1), 하락 7번(−1) → 50
        self.assertAlmostEqual(N._rsi14([float(x) for x in c]), 50.0)
        # 하루 더(+2): 상승평균 (0.5×13+2)/14, 하락평균 0.5×13/14 → RS = 8.5/6.5
        self.assertAlmostEqual(N._rsi14([float(x) for x in c + [12]]), 100 - 100 / (1 + 8.5 / 6.5))

    def test_quality_flags_without_fixing(self):
        r = lambda d, o, h, l, c, v: {'trade_date': d, 'open': o, 'high': h, 'low': l, 'close': c, 'volume': v}
        q = price_quality([r('2026-01-02', '10', '12', '9', '11', 5), r('2026-01-02', '10', '12', '9', '11', 5),
                           r('2026-01-05', '10', '9', '9', '11', 5), r('2026-01-06', '10', '12', '9', '11', 0), r('2026-01-07', '10', '12', '9', '0', 5)])
        self.assertEqual(q['duplicate_dates'], ['2026-01-02']); self.assertEqual(q['ohlc_errors'], ['2026-01-05'])
        self.assertEqual(q['zero_volume'], ['2026-01-06']); self.assertEqual(q['bad_close'], ['2026-01-07']); self.assertEqual(q['checked'], 5)

    def test_mad_candidate_found_only_on_the_odd_day(self):
        rows = []
        for i in range(200):
            c = 100.0 * (1.001 if i % 2 else 0.999) ** 1 + i * 0.01
            rows.append({'trade_date': f'd{i:03d}', 'close': str(c), 'high': str(c * 1.01), 'low': str(c * 0.99), 'volume': 1000 + (i % 7)})
        self.assertEqual(N._mad_candidates(rows), [])
        rows[-3]['volume'] = 50000
        got = N._mad_candidates(rows)
        self.assertEqual([(x['date'], x['feature']) for x in got], [('d197', '로그 거래량')])


class Engine(Base):
    def test_liquidity_bundle_numbers(self):
        d, days = build(self.neon, [100.0 + i for i in range(200)], [5] * 200)
        def fn(rows):
            for i, r in enumerate(rows):
                r['trade_value'] = str(2_000_000_000 if i >= 195 else 1_000_000_000); r['volume'] = 2000 if i >= 195 else 1000
            return rows
        rewrite_prices(d, fn)
        run, n = self.run_doc(liq_doc())
        self.assertEqual(n['n07']['status'], 'succeeded', n['n07']['reason'])
        P = self.pay(n['n07']); F = {f['name']: f for f in P['findings']}
        self.assertEqual(F['거래대금 배율 (최근 5일 ÷ 직전 60일)']['value'], 2.0)
        self.assertIn('급증', F['거래대금 배율 (최근 5일 ÷ 직전 60일)']['claim']); self.assertEqual(F['거래대금 배율 (최근 5일 ÷ 직전 60일)']['kind'], 'rule_derived')
        self.assertIn('5일 20억원', F['거래대금 평균']['claim'])
        self.assertIn('1일 평균 0.200%', F['회전율']['claim']); self.assertIn('20일 평균 0.125%', F['회전율']['claim'])   # 2000/1e6, (15×1000+5×2000)/20/1e6
        self.assertEqual(F['거래대금이 평소와 달랐던 날 (최근 20거래일)']['value'], 1)                                   # 195번째 날만 직전 20일 평균의 2배
        self.assertIn('10억원 ~ 10억원', F['최근 60거래일 거래대금 범위']['claim'])   # 20억원인 날은 60일 중 5일(상위 8%)이라 90 백분위 밖
        a5 = sum(abs(1 / (100 + i - 1)) * 100 / 0.002 for i in range(195, 200)) / 5
        self.assertAlmostEqual(F['Amihud 비유동성']['value'], round(a5, 6))
        self.assertIn('유동성 충격 점수', F)
        self.assertIn('5거래일 누적 순매수', F)                                    # 기존 항목은 그대로
        self.assertNotIn('미연결', json.dumps(P['held'], ensure_ascii=False))

    def test_n07_without_prices_still_works_and_says_so(self):
        build(self.neon, [100.0 + i for i in range(200)], [5] * 200)
        run, n = self.run_doc(doc())
        P = self.pay(n['n07'])
        self.assertEqual(n['n07']['status'], 'succeeded')
        self.assertTrue(any('가격 자료(T06) 미연결' in h for h in P['held']))
        self.assertNotIn('회전율', {f['name'] for f in P['findings']})

    def test_t06_quality_note_and_n09_n10_new_items(self):
        d, days = build(self.neon, [100.0 + i for i in range(200)], [5] * 200)
        def fn(rows):
            rows[150]['volume'] = 0
            return rows
        rewrite_prices(d, fn)
        run, n = self.run_doc(liq_doc())
        self.assertIn('거래량 0', n['t06']['reason']); self.assertIn('표시만', n['t06']['reason'])
        self.assertEqual(self.pay(n['t06'])['quality']['zero_volume'], [days[150]])
        self.assertEqual(len(self.pay(n['t06'])['rows']), 200)                     # 지우지 않음
        F9 = {f['name']: f for f in self.pay(n['n09'])['findings']}
        self.assertEqual(F9['RSI(14)']['value'], 100.0)
        F10 = {f['name']: f for f in self.pay(n['n10'])['findings']}
        want = math.sqrt(sum(math.log((100 + i) / (99 + i)) ** 2 for i in range(195, 200))) * 100
        self.assertAlmostEqual(F10['5거래일 기간 변동성(연율 아님)']['value'], round(want, 2))
        self.assertIn('20일 실현 변동성(연율)', F10)                               # 기존 정의 유지
        self.assertEqual(F10['드문 패턴 후보 (최근 60거래일)']['kind'], 'rule_derived')
        self.assertIn('거래량 급증일 (최근 60거래일)', F10)                        # 기존 항목 유지
        txt = json.dumps([self.pay(n[k]) for k in ('n07', 'n09', 'n10')], ensure_ascii=False)
        for bad in ('과매수', '과매도', '매수 신호', '매도 신호', '이상매매입니다'):
            self.assertNotIn(bad, txt)


if __name__ == '__main__':
    unittest.main()
