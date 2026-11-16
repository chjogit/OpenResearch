"""v0.11: T07 수급 사본 · N07 · N08 · N10 국면 규칙."""
import hashlib, json, os, tempfile, unittest
from datetime import date, timedelta
from mrn import nodes as N
from mrn.engine import Engine
from mrn.store import Store
from mrn.workflow import WorkflowDoc, validate, blocking, topo_order

CUT = '2026-11-06T07:00:00+09:00'


def _h(p):
    with open(p, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def _w(p, text, nl='\n'):
    with open(p, 'w', encoding='utf-8', newline=nl) as f:
        f.write(text)


def build(root, closes, fnet, ticker='000660', start=date(2025, 6, 2), lending=True):
    name = '20261106T120000+0900'; d = os.path.join(root, name); os.makedirs(d)
    days, day = [], start
    while len(days) < len(closes):
        if day.weekday() < 5: days.append(day.isoformat())
        day += timedelta(days=1)
    T = {
        'price_daily': [{'ticker': ticker, 'trade_date': t, 'open': str(c), 'high': str(c), 'low': str(c), 'close': str(c), 'volume': '1000',
                         'trade_value': '1', 'market_cap': '1', 'source': 'fsc', 'collected_at': 'x'} for t, c in zip(days, closes)],
        'investor_flow_daily': [{'ticker': ticker, 'trade_date': t, 'foreign_net_qty': f, 'institution_net_qty': -f // 2, 'individual_net_qty': -f // 2,
                                 'foreign_hold_pct': '50.00', 'volume': 1000, 'source': 'naver_trend', 'collected_at': 'x'} for t, f in zip(days, fnet)],
        'company': [{'ticker': ticker, 'name': 'SK하이닉스', 'shares_outstanding': '1000000'}],
    }
    if lending:
        T['stock_lending_daily'] = [{'ticker': ticker, 'trade_date': t, 'balance_qty': 10000 + i, 'balance_amt': '1', 'lent_qty': 1, 'repaid_qty': 0,
                                     'source': 'fsc_lending', 'collected_at': 'x'} for i, t in enumerate(days)]
    tables = {}
    for t, recs in T.items():
        p = os.path.join(d, t + '.jsonl')
        _w(p, ''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in recs))
        tables[t] = {'file': t + '.jsonl', 'rows': len(recs), 'sha256': _h(p), 'source_grade': 'x', 'query': 'test', 'note': ''}
    mp = os.path.join(d, 'manifest.json'); _w(mp, json.dumps({'asof_kst': name, 'tables': tables}))
    _w(os.path.join(d, 'manifest.sha256'), _h(mp) + '  manifest.json\n')
    _w(os.path.join(root, 'LATEST.txt'), name + '\n')
    return d, days


def doc(company='000660'):
    cfg = {'company': company, 'snapshot': '', 'lookback': 260}
    return {'name': 'flow', 'cutoff': CUT,
            'nodes': [{'id': 't06', 'type': 'T06', 'config': dict(cfg)}, {'id': 't07', 'type': 'T07', 'config': dict(cfg)},
                      {'id': 'n07', 'type': 'N07', 'config': {}}, {'id': 'n08', 'type': 'N08', 'config': {}}, {'id': 'n10', 'type': 'N10', 'config': {}}],
            'edges': [{'from_node': 't07', 'from_port': 'flows', 'to_node': 'n07', 'to_port': 'flows'},
                      {'from_node': 't07', 'from_port': 'flows', 'to_node': 'n08', 'to_port': 'flows'},
                      {'from_node': 't06', 'from_port': 'prices', 'to_node': 'n08', 'to_port': 'prices'},
                      {'from_node': 't06', 'from_port': 'prices', 'to_node': 'n10', 'to_port': 'prices'}]}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.neon = os.path.join(self.tmp.name, 'neon'); os.makedirs(self.neon)
        self.old = os.environ.get('MODU_NODES_NEON_DIR'); os.environ['MODU_NODES_NEON_DIR'] = self.neon
        self.store = Store(os.path.join(self.tmp.name, 'db')); self.engine = Engine(self.store)

    def tearDown(self):
        if self.old is None: os.environ.pop('MODU_NODES_NEON_DIR', None)
        else: os.environ['MODU_NODES_NEON_DIR'] = self.old
        self.tmp.cleanup()

    def run_doc(self, d):
        w = WorkflowDoc.model_validate(d)
        self.assertEqual(blocking(validate(w, N.check_assumptions)), [])
        run = self.store.get_run('me', self.engine.start('me', w.model_dump(), topo_order(w), background=False))
        return run, {n['node_id']: n for n in run['nodes']}

    def pay(self, n):
        return self.store.get_packet(n['output_packet'])['payload']


class Flows(Base):
    def test_n07_numbers_and_portal_label(self):
        closes = [100.0 + i for i in range(200)]
        fnet = [100] * 190 + [-50] * 10            # 마지막 10일 외국인 순매도
        build(self.neon, closes, fnet)
        run, n = self.run_doc(doc())
        self.assertEqual(n['t07']['status'], 'succeeded', n['t07']['reason'])
        self.assertIn('포털', n['t07']['reason'])
        self.assertEqual(self.pay(n['t07'])['kind'], 'fact_portal')
        F = {f['name']: f for f in self.pay(n['n07'])['findings']}
        self.assertIn('외국인 -250주', F['5거래일 누적 순매수']['claim'])
        self.assertIn('외국인 -250주(거래량의 -5.0%)', F['5거래일 누적 순매수']['claim'])
        self.assertEqual(F['외국인 연속 순매도']['claim'], '10거래일째')
        self.assertIn('발행주식의 1.02%', F['대차잔고 (금융위)']['claim'])
        self.assertEqual(F['기준일 주체별 순매수']['kind'], 'fact_portal')

    def test_n08_mismatch_counts(self):
        closes = [100.0 + i for i in range(200)]       # 매일 상승
        fnet = [-10] * 200                              # 매일 외국인 순매도
        build(self.neon, closes, fnet)
        run, n = self.run_doc(doc())
        F = {f['name']: f for f in self.pay(n['n08'])['findings']}
        self.assertIn('순매도인데 상승 60일', F['외국인 매매와 주가가 엇갈린 날 (최근 60거래일)']['claim'])
        self.assertIn('서로 다른 방향', F['최근 20거래일: 외국인 누적과 주가']['claim'])
        txt = json.dumps(self.pay(n['n08']), ensure_ascii=False)
        for bad in ('매수하세요', '매도하세요', '매수 신호', '매도 신호'):
            self.assertNotIn(bad, txt)

    def test_no_lending_table_is_held_item_not_failure(self):
        build(self.neon, [100.0 + i for i in range(200)], [5] * 200, lending=False)
        run, n = self.run_doc(doc())
        self.assertEqual(n['n07']['status'], 'succeeded')
        self.assertTrue(any('대차잔고' in h for h in self.pay(n['n07'])['held']))

    def test_tampered_flow_is_held(self):
        d, _ = build(self.neon, [100.0 + i for i in range(200)], [5] * 200)
        with open(os.path.join(d, 'investor_flow_daily.jsonl'), 'a', encoding='utf-8') as f: f.write('\n')
        run, n = self.run_doc(doc())
        self.assertEqual(n['t07']['status'], 'held')
        self.assertNotEqual(n['n07']['status'], 'succeeded')


class Regime(Base):
    def _regime(self, closes):
        build(self.neon, closes, [1] * len(closes))
        run, n = self.run_doc(doc())
        F = {f['name']: f for f in self.pay(n['n10'])['findings']}
        return F['국면 (이동평균 배열 규칙)']

    def test_up(self):
        f = self._regime([100.0 + i for i in range(200)])
        self.assertEqual(f['value'], '상승'); self.assertEqual(f['kind'], 'rule_derived')

    def test_down(self):
        self.assertEqual(self._regime([400.0 - i for i in range(200)])['value'], '하락')

    def test_flat(self):
        self.assertEqual(self._regime([100.0 + (i % 2) for i in range(200)])['value'], '전환·횡보')

    def test_rule_function_direct(self):
        rows = [{'trade_date': str(i), 'close': str(100 + i)} for i in range(100)]
        r = N.regime(rows)
        self.assertEqual(len(r), 21)
        self.assertTrue(all(x[1] == '상승' for x in r))


if __name__ == '__main__':
    unittest.main()
