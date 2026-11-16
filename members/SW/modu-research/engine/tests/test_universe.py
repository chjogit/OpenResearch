"""v0.13: 종목 확장 키트 1(기업별 분할 사본) · C 시장 근거 지도."""
import hashlib, json, os, tempfile, unittest
from datetime import date, timedelta
from mrn import market
from mrn import nodes as N
from mrn.engine import Engine
from mrn.store import Store
from mrn.workflow import WorkflowDoc, validate, blocking, topo_order

CUT = '2026-11-06T16:00:00+09:00'
CO = [('005930', '삼성전자', 'KR'), ('000660', 'SK하이닉스', 'KR'), ('042700', '한미반도체', 'KR'),
      ('003550', 'LG', 'KR'), ('066570', 'LG전자', 'KR'), ('034220', 'LG디스플레이', 'KR'), ('MU', '마이크론', 'US')]


def _h(p):
    with open(p, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def _w(p, recs):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n')
    return _h(p), len(recs)


def make_v3(root, days=300, tickers=('005930', '042700')):
    name = '20261107T000000+0900'
    d = os.path.join(root, name)
    os.makedirs(d)
    tables = {}
    h, n = _w(os.path.join(d, 'company.jsonl'), [{'ticker': t, 'name': nm, 'market': mk, 'krx_sector': '반도체' if t == '042700' else ''} for t, nm, mk in CO])
    tables['company'] = {'file': 'company.jsonl', 'rows': n, 'sha256': h, 'source_grade': 'registered', 'query': 't', 'note': ''}
    for table in ('price_daily', 'investor_flow_daily'):
        parts, total = {}, 0
        for t in tickers:
            rows, day, i = [], date(2025, 6, 2), 0
            while i < days:
                if day.weekday() < 5:
                    c = 100 + i
                    if table == 'price_daily':
                        rows.append({'ticker': t, 'trade_date': day.isoformat(), 'open': str(c), 'high': str(c + 1), 'low': str(c - 1), 'close': str(c),
                                     'volume': str(1000 + i % 9), 'trade_value': '1', 'market_cap': '1', 'source': 'fsc', 'collected_at': '2026-11-06T03:00:00+00:00'})
                    else:
                        rows.append({'ticker': t, 'trade_date': day.isoformat(), 'foreign_net_qty': str((i % 5) - 2), 'institution_net_qty': '1',
                                     'individual_net_qty': '-1', 'foreign_hold_pct': '10', 'volume': '1000'})
                    i += 1
                day += timedelta(days=1)
            f = f'{table}/{t}.jsonl'
            h, n = _w(os.path.join(d, f), rows)
            parts[t] = {'file': f, 'rows': n, 'sha256': h}
            total += n
        tables[table] = {'partitioned': True, 'parts': parts, 'rows': total, 'source_grade': 'public:fsc', 'query': 't', 'note': ''}
    cov = [{'ticker': t, 'price_fsc': {'n': days if t in tickers else 0, 'x': '2026-11-05'}, 'flow': {'n': days if t in tickers else 0, 'x': None},
            'fin_quarter': {'n': 8 if t in ('005930', '000660') else 0, 'x': '2026-06-30'}} for t, _, _ in CO]
    h, n = _w(os.path.join(d, 'coverage.jsonl'), cov)
    tables['coverage'] = {'file': 'coverage.jsonl', 'rows': n, 'sha256': h, 'source_grade': 'derived:count', 'note': ''}
    mp = os.path.join(d, 'manifest.json')
    with open(mp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps({'tool_version': 3, 'tables': tables}))
    with open(os.path.join(d, 'manifest.sha256'), 'w', encoding='utf-8', newline='\r\n') as f:
        f.write(_h(mp) + '  manifest.json\n')
    with open(os.path.join(root, 'LATEST.txt'), 'w', encoding='utf-8', newline='\r\n') as f:
        f.write(name + '\n')
    return d


class V3Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ['MODU_NODES_NEON_DIR'] = self.tmp.name
        market._UNI.clear()
        self.snap = make_v3(self.tmp.name)

    def tearDown(self):
        os.environ.pop('MODU_NODES_NEON_DIR', None)
        market._UNI.clear()
        self.tmp.cleanup()


class TestPartitions(V3Base):
    def test_reads_only_own_part(self):
        ps = market.price_series('042700', CUT)
        self.assertEqual(ps['name'], '한미반도체')
        self.assertEqual(ps['source']['file'], 'price_daily/042700.jsonl')
        self.assertEqual(len(ps['rows']), 260)

    def test_tampered_part_is_held(self):
        p = os.path.join(self.snap, 'price_daily', '042700.jsonl')
        with open(p, 'a', encoding='utf-8') as f:
            f.write('{"ticker":"042700"}\n')
        with self.assertRaises(market.SnapshotError) as e:
            market.price_series('042700', CUT)
        self.assertEqual(e.exception.code, 'table_changed')
        market.price_series('005930', CUT)          # 다른 기업 파일은 영향 없음

    def test_unknown_and_missing_company(self):
        with self.assertRaises(market.SnapshotError) as e:
            market.price_series('999999', CUT)
        self.assertEqual(e.exception.code, 'company_unknown')
        with self.assertRaises(market.SnapshotError) as e:
            market.price_series('066570', CUT)       # 목록엔 있지만 시세 파일이 없음
        self.assertEqual(e.exception.code, 'no_rows')

    def test_t06_t07_any_company(self):
        doc = {'name': 'x', 'cutoff': CUT, 'nodes': [
            {'id': 't06', 'type': 'T06', 'config': {'company': '042700', 'snapshot': '', 'lookback': 260}},
            {'id': 't07', 'type': 'T07', 'config': {'company': '042700', 'snapshot': '', 'lookback': 260}},
            {'id': 'bad', 'type': 'T06', 'config': {'company': '삼성', 'snapshot': '', 'lookback': 260}}], 'edges': []}
        wd = WorkflowDoc.model_validate(doc)
        self.assertFalse(blocking(validate(wd, N.check_assumptions)))
        with tempfile.TemporaryDirectory() as td:
            st = Store(os.path.join(td, 'db'))
            rid = Engine(st).start('o', wd.model_dump(), topo_order(wd), background=False)
            nodes = {n['node_id']: n for n in st.get_run('o', rid)['nodes']}
        self.assertEqual(nodes['t06']['status'], 'succeeded')
        self.assertIn(nodes['t07']['status'], ('succeeded', 'partial'))
        self.assertEqual(nodes['bad']['status'], 'held')


class TestUniverse(V3Base):
    def test_universe_counts(self):
        u = market.universe()
        self.assertEqual(u['count'], len(CO))
        self.assertEqual(u['summary']['price_fsc'], 2)
        self.assertEqual(u['summary']['fin_quarter'], 2)
        keys = [c['key'] for c in u['columns']]
        self.assertEqual(keys[:2], ['price_fsc', 'flow'])
        self.assertTrue(next(c for c in u['columns'] if c['key'] == 'price_fsc')['ready_now'])
        self.assertIs(market.universe(), u)              # manifest 해시로 캐시

    def test_api_and_csv(self):
        from fastapi.testclient import TestClient
        from mrn.server import create_app
        with tempfile.TemporaryDirectory() as td:
            try:
                with TestClient(create_app(data_dir=td)) as c:
                    r = c.get('/api/universe')
                    self.assertEqual(r.status_code, 200)
                    self.assertEqual(r.json()['count'], len(CO))
                    g = c.get('/api/universe/gaps.csv')
                    self.assertEqual(g.status_code, 200)
                    txt = g.content.decode('utf-8-sig')
                    self.assertIn('LG전자', txt)
                    self.assertNotIn('042700,한미반도체,KR,시세', txt)
            finally:
                pass


class TestAssemblerUniverse(V3Base):
    def test_other_company_market_nodes(self):
        from mrn.assembler import assemble
        a = assemble('한미반도체 주가 추세와 외국인 수급')
        self.assertEqual(a['status'], 'ok')
        self.assertTrue(a['targets'])
        self.assertTrue(all(t['company'] == '042700' for t in a['targets']))
        t06 = [n for n in a['doc']['nodes'] if n['type'] in ('T06', 'T07')]
        self.assertTrue(t06 and all(n['config']['company'] == '042700' for n in t06))
        self.assertIn('한미반도체', ' '.join(c['text'] for c in a['chains']))

    def test_base_only_goal_for_other_company(self):
        from mrn.assembler import assemble
        a = assemble('한미반도체 DCF 가치평가')
        self.assertIn(a['status'], ('gap_only', 'ok'))
        self.assertTrue(any('삼성전자·SK하이닉스만' in n for n in a['notes']))
        self.assertFalse(any(t['company'] in ('005930', '000660') for t in a['targets']))

    def test_filings_goal_for_other_company(self):
        from mrn.assembler import assemble
        a = assemble('한미반도체 영업이익과 현금흐름 실적')
        types = {n['type'] for n in a['doc']['nodes']}
        self.assertIn('T11', types)
        self.assertNotIn('T01', types)                 # 묻지 않은 두 기준 기업 원문은 넣지 않음
        a = assemble('한미반도체와 삼성전자 실적')
        types = {n['type'] for n in a['doc']['nodes']}
        self.assertTrue({'T11', 'T01', 'N01'} <= types)

    def test_ambiguous_short_name_note(self):
        from mrn.assembler import assemble
        a = assemble('LG 주가 추세')
        self.assertTrue(any('LG전자' in n for n in a['notes']))
        a = assemble('LG전자 주가 추세')
        self.assertEqual([t['company'] for t in a['targets']][:1], ['066570'])
        self.assertFalse(any('LG전자' in n and '정확한 이름' in n for n in a['notes']))

    def test_ticker_in_question(self):
        from mrn.assembler import parse
        self.assertEqual(parse('042700 수급')['companies'], ['042700'])


if __name__ == '__main__':
    unittest.main()
