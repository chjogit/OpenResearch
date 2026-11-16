"""v0.9: T06 가격 사본 · N09 · N10."""
import hashlib, json, os, tempfile, unittest
from datetime import date, timedelta
from mrn import nodes as N
from mrn.engine import Engine
from mrn.store import Store
from mrn.workflow import WorkflowDoc, validate, blocking, topo_order
from mrn import market

CUT = '2026-11-06T07:00:00+09:00'


def _h(p):
    with open(p, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def _wt(p, text, nl='\n'):
    with open(p, 'w', encoding='utf-8', newline=nl) as f:
        f.write(text)


def make_snapshot(root, closes, start=date(2025, 1, 2), ticker='000660', extra_after=0):
    name = '20261106T120000+0900'
    d = os.path.join(root, name); os.makedirs(d)
    rows, day = [], start
    seq = list(closes) + [closes[-1]] * extra_after
    i = 0
    while i < len(seq):
        if day.weekday() < 5:
            c = seq[i]
            rows.append({'ticker': ticker, 'trade_date': day.isoformat(), 'open': str(c), 'high': str(c + 1), 'low': str(c - 1), 'close': str(c),
                         'volume': str(1000 + (i % 7) * 10 + (50000 if i == len(seq) - 3 else 0)), 'trade_value': str(c * 1000), 'market_cap': '1', 'source': 'fsc',
                         'collected_at': '2026-11-06T03:00:00+00:00'})
            i += 1
        day += timedelta(days=1)
    rows.append({**rows[-1], 'source': 'yfinance', 'trade_date': rows[-1]['trade_date']})  # must be ignored
    def w(fname, recs):
        p = os.path.join(d, fname)
        with open(p, 'w', encoding='utf-8', newline='\n') as f:
            for r in recs: f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n')
        return _h(p), len(recs)
    tables = {}
    for t, recs in (('price_daily', rows), ('company', [{'ticker': ticker, 'name': 'SK하이닉스'}])):
        h, n = w(t + '.jsonl', recs)
        tables[t] = {'file': t + '.jsonl', 'rows': n, 'sha256': h, 'source_grade': 'public:fsc', 'query': 'test', 'note': ''}
    mp = os.path.join(d, 'manifest.json')
    _wt(mp, json.dumps({'asof_kst': name, 'tables': tables}))
    _wt(os.path.join(d, 'manifest.sha256'), _h(mp) + '  manifest.json\n', '\r\n')
    _wt(os.path.join(root, 'LATEST.txt'), name + '\n')
    return d, rows


def doc(company='000660', extra=()):
    return {'name': 'px', 'cutoff': CUT,
            'nodes': [{'id': 't06', 'type': 'T06', 'config': {'company': company, 'snapshot': '', 'lookback': 260}},
                      {'id': 'n09', 'type': 'N09', 'config': {}}, {'id': 'n10', 'type': 'N10', 'config': {}}, *extra],
            'edges': [{'from_node': 't06', 'from_port': 'prices', 'to_node': 'n09', 'to_port': 'prices'},
                      {'from_node': 't06', 'from_port': 'prices', 'to_node': 'n10', 'to_port': 'prices'}]}


class MarketBase(unittest.TestCase):
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
        rid = self.engine.start('me', w.model_dump(), topo_order(w), background=False)
        run = self.store.get_run('me', rid)
        return run, {n['node_id']: n for n in run['nodes']}

    def pay(self, n):
        return self.store.get_packet(n['output_packet'])['payload']


class T06Snapshot(MarketBase):
    def test_reads_verified_snapshot_and_cutoff(self):
        closes = [100 + i for i in range(300)]
        make_snapshot(self.neon, closes, extra_after=5)
        run, n = self.run_doc(doc())
        self.assertEqual(n['t06']['status'], 'succeeded', n['t06']['reason'])
        p = self.pay(n['t06'])
        self.assertEqual(len(p['rows']), 260)
        self.assertTrue(all(r['trade_date'] <= '2026-11-05' for r in p['rows']))
        self.assertEqual(p['source']['source_grade'], 'public:fsc')
        self.assertFalse(p['adjusted'])

    def test_cutoff_drops_future_rows(self):
        make_snapshot(self.neon, [100 + i for i in range(300)], start=date(2025, 12, 1))  # runs past cutoff
        run, n = self.run_doc(doc())
        p = self.pay(n['t06'])
        self.assertGreater(p['excluded_after_cutoff'], 0)
        self.assertEqual(p['last_usable_date'], '2026-11-05')
        self.assertTrue(all(r['trade_date'] <= '2026-11-05' for r in p['rows']))

    def test_tampered_table_is_held(self):
        d, _ = make_snapshot(self.neon, [100 + i for i in range(300)])
        with open(os.path.join(d, 'price_daily.jsonl'), 'a', encoding='utf-8') as f: f.write('\n')
        run, n = self.run_doc(doc())
        self.assertEqual(n['t06']['status'], 'held')
        self.assertIn('해시', n['t06']['reason'])
        self.assertNotEqual(n['n09']['status'], 'succeeded')

    def test_tampered_manifest_is_held(self):
        d, _ = make_snapshot(self.neon, [100 + i for i in range(300)])
        with open(os.path.join(d, 'manifest.json'), encoding='utf-8') as f: m = json.load(f)
        m['x'] = 1
        _wt(os.path.join(d, 'manifest.json'), json.dumps(m))
        run, n = self.run_doc(doc())
        self.assertEqual(n['t06']['status'], 'held')

    def test_no_snapshot_is_held_not_zero(self):
        run, n = self.run_doc(doc())
        self.assertEqual(n['t06']['status'], 'held')
        self.assertIsNone(n['t06']['output_packet'])

    def test_short_history_partial(self):
        make_snapshot(self.neon, [100 + i for i in range(100)])
        run, n = self.run_doc(doc())
        self.assertEqual(n['t06']['status'], 'partial')
        self.assertEqual(n['n09']['status'], 'partial')
        self.assertTrue(any('1년' in h for h in self.pay(n['n09'])['held']))


class T06Split(MarketBase):
    def test_limit_break_flagged(self):
        closes = [100.0] * 150 + [50.0] * 150   # -50% in one day: split-like
        make_snapshot(self.neon, closes)
        run, n = self.run_doc(doc())
        self.assertEqual(n['t06']['status'], 'partial')
        self.assertIn('가격제한폭', n['t06']['reason'])
        self.assertEqual(len(self.pay(n['t06'])['limit_breaks']), 1)


class N09N10Math(MarketBase):
    def test_known_values(self):
        closes = [100.0] * 200 + [100.0 + i for i in range(1, 61)]   # 260 rows, last = 160
        make_snapshot(self.neon, closes)
        run, n = self.run_doc(doc())
        p = self.pay(n['n09']); F = {f['name']: f for f in p['findings']}
        self.assertEqual(F['기준 종가']['value'], '160.0')
        self.assertAlmostEqual(F['1개월 수익률']['value'], round((160 / 139 - 1) * 100, 2))
        self.assertEqual(F['20일 이동평균']['value'], round(sum(range(141, 161)) / 20, 0))
        self.assertEqual(F['260거래일 최고·최저 (종가)']['value'] if '260거래일 최고·최저 (종가)' in F else F['252거래일 최고·최저 (종가)']['value'], {'high': 160.0, 'low': 100.0})
        for f in p['findings']:
            self.assertIn(f['kind'], ('fact_official', 'derived'))
            if f['kind'] == 'derived': self.assertTrue(f.get('formula'))
        txt = json.dumps(p, ensure_ascii=False)
        for bad in ('매수', '매도', '목표가', '사세요', '파세요'):
            self.assertNotIn(bad + '하', txt)
        q = self.pay(n['n10']); G = {f['name']: f for f in q['findings']}
        self.assertEqual(n['n10']['status'], 'succeeded')   # v0.11: 국면 규칙 추가로 실동작
        self.assertEqual(G['252거래일 최대 낙폭']['value'], 0.0)
        self.assertGreaterEqual(G['거래량 급증일 (최근 60거래일)']['value'], 1)

    def test_n09_rejects_non_t06(self):
        from mrn.nodes import Result
        class P: pass
        pkt = {'header': {'type': 'PriceSeries', 'payload_digest': '', 'produced_by': {'node_type': 'T01', 'node_id': 'x'}}, 'payload': {}}
        from mrn.util import digest
        pkt['header']['payload_digest'] = digest(pkt['payload'])
        with self.assertRaises(Exception):
            N.n09({'id': 'n09', 'config': {}}, {'prices': [pkt]}, None)


@unittest.skipUnless(os.path.exists(os.path.join(os.path.dirname(__file__), '..', '..', '_sources', 'neon', 'LATEST.txt')), 'real snapshot not present')
class RealSnapshot(unittest.TestCase):
    def test_real_snapshot_both_companies(self):
        os.environ.pop('MODU_NODES_NEON_DIR', None)
        for co in ('005930', '000660'):
            ps = market.price_series(co, CUT)
            self.assertGreaterEqual(len(ps['rows']), 252)
            self.assertEqual(ps['rows'][-1]['trade_date'], '2026-11-05')
            self.assertEqual(ps['source']['source_grade'], 'public:fsc')


if __name__ == '__main__':
    unittest.main()
