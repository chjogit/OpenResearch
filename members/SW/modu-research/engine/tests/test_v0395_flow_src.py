"""v0.39.5: 수급 사본의 KIS 보충 행(kis_investor) — 쓰임·출처 표시·스위치. 네트워크 없음."""
import hashlib, json, os, tempfile, unittest
from unittest import mock

from mrn import market


def _h(p):
    with open(p, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def snap(root, flows, name='20261116T180000+0900'):
    d = os.path.join(root, name); os.makedirs(d)
    tables = {}
    for t, recs in (('investor_flow_daily', flows), ('company', [{'ticker': '005930', 'name': '삼성전자'}])):
        p = os.path.join(d, t + '.jsonl')
        with open(p, 'w', encoding='utf-8', newline='\n') as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n')
        tables[t] = {'file': t + '.jsonl', 'rows': len(recs), 'sha256': _h(p), 'source_grade': 'portal:naver', 'query': 'test', 'note': ''}
    mp = os.path.join(d, 'manifest.json')
    with open(mp, 'w', encoding='utf-8') as f:
        f.write(json.dumps({'asof_kst': name, 'tables': tables}))
    with open(os.path.join(d, 'manifest.sha256'), 'w', encoding='utf-8') as f:
        f.write(_h(mp) + '  manifest.json\n')
    with open(os.path.join(root, 'LATEST.txt'), 'w', encoding='utf-8') as f:
        f.write(name + '\n')


def fr(day, f, src):
    return {'ticker': '005930', 'trade_date': day, 'foreign_net_qty': f, 'institution_net_qty': 1, 'individual_net_qty': -f - 1,
            'foreign_hold_pct': '46.0000', 'volume': 100, 'source': src, 'collected_at': '2026-11-16T09:00:00+00:00'}


class Flow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {'MODU_NODES_NEON_DIR': self.tmp.name}); self.env.start()
        snap(self.tmp.name, [fr('2026-11-04', 10, 'naver_trend'), fr('2026-11-05', 20, 'naver_trend'),
                             fr('2026-11-06', 30, 'kis_investor'), fr('2026-11-13', 40, 'kis_investor')])

    def tearDown(self):
        self.env.stop(); self.tmp.cleanup()

    def test_kis_rows_used_and_labelled(self):
        os.environ.pop('MODU_PRICE_KIS', None)
        s = market.flow_series('005930', '2026-11-14T16:00:00+09:00')
        self.assertEqual([r['trade_date'] for r in s['rows']][-1], '2026-11-13')
        self.assertEqual(s['source']['flows']['kis_rows'], 2)
        self.assertIn('한국투자증권 투자자별 매매(kis) 2거래일 보충', s['source']['flows']['origin'])
        self.assertIn('최근 2거래일은 한국투자증권', s['notes'][0])
        s2 = market.flow_series('005930', '2026-11-10T16:00:00+09:00')   # 기준 날짜 뒤 행은 안 씀
        self.assertEqual(s2['rows'][-1]['trade_date'], '2026-11-06'); self.assertEqual(s2['source']['flows']['kis_rows'], 1)

    def test_switch_off_drops_kis(self):
        with mock.patch.dict(os.environ, {'MODU_PRICE_KIS': '0'}):
            s = market.flow_series('005930', '2026-11-14T16:00:00+09:00')
        self.assertEqual(s['rows'][-1]['trade_date'], '2026-11-05'); self.assertEqual(s['source']['flows']['kis_rows'], 0)
        self.assertNotIn('kis', s['source']['flows']['origin']); self.assertNotIn('한국투자증권', s['notes'][0])


class HoldDate(unittest.TestCase):
    """보유율이 빈 KIS 보충 날(외국인 한도 종목)이 있으면, 보유율 문장은 값이 있는 마지막 날짜를 밝힌다."""
    def run_n07(self, holds):
        from mrn import nodes
        rows = [{'trade_date': f'2026-11-0{i}', 'foreign_net_qty': 1, 'institution_net_qty': 1, 'individual_net_qty': -2,
                 'foreign_hold_pct': h, 'volume': 10} for i, h in enumerate(holds, 1)]
        payload = {'company': '005930', 'name': '삼성전자', 'rows': rows, 'lending': [], 'shares_outstanding': None, 'source': {}}
        with mock.patch.object(nodes, '_flow_inputs', return_value=(payload, 'dig')), mock.patch.object(nodes, '_one', return_value=None):
            res = nodes.n07(None, [], None)
        return [f for f in res.payload['findings'] if f['name'] == '외국인 보유율'][0]

    def test_blank_days_use_own_date(self):
        h = self.run_n07(['40.0000'] * 5 + [None, None])
        self.assertEqual(h['as_of'], '2026-11-05'); self.assertTrue(h['claim'].startswith('2026-11-05 기준 40.00%'))

    def test_no_blank_unchanged(self):
        h = self.run_n07(['40.0000'] * 7)
        self.assertEqual(h['as_of'], '2026-11-07'); self.assertEqual(h['claim'], '40.00%')


if __name__ == '__main__':
    unittest.main()
