"""v0.10: 목표부터 조립 에이전트."""
import json, os, tempfile, unittest
from fastapi.testclient import TestClient
from mrn.assembler import assemble, map_from_audit
from mrn.specs import SPECS
from mrn.workflow import WorkflowDoc, validate, blocking, topo_order
from mrn import nodes as N

HERE = os.path.dirname(__file__)
CUT = '2026-11-06T07:00:00+09:00'


def load(name):
    with open(os.path.join(HERE, 'data', name), encoding='utf-8') as f:
        return json.load(f)['items']


def judge(it):
    r = assemble(it['q'])
    got_t = sorted(set(t['type'] for t in r['targets'])); got_g = {g['id'] for g in r['gaps']}
    return got_t == sorted(set(it['expect_targets'])) and r['status'] == it['expect_status'] and set(it.get('expect_gaps', [])) <= got_g


class EvalSets(unittest.TestCase):
    def test_goal_eval_v1(self):
        items = load('goal_eval_v1.json'); bad = [i['q'] for i in items if not judge(i)]
        self.assertEqual(bad, [])

    def test_goal_holdout_v1(self):
        items = load('goal_holdout_v1.json'); bad = [i['q'] for i in items if not judge(i)]
        self.assertEqual(bad, [])


class Structure(unittest.TestCase):
    QS = [i['q'] for i in load('goal_eval_v1.json')] + [i['q'] for i in load('goal_holdout_v1.json')]

    def test_docs_are_valid_and_connected(self):
        for q in self.QS:
            r = assemble(q, cutoff=CUT)
            if not r['doc']:
                self.assertIn(r['status'], ('ask', 'gap_only')); self.assertTrue(r['choices']); continue
            d = WorkflowDoc.model_validate(r['doc'])
            codes = {i['code'] for i in blocking(validate(d, N.check_assumptions))}
            self.assertTrue(codes <= {'assumption_invalid'}, (q, codes))      # 사람 몫(T03)만 남는다
            ids = [n['id'] for n in r['doc']['nodes']]
            self.assertEqual(len(ids), len(set(ids)))
            for n in r['doc']['nodes']:
                self.assertNotEqual(SPECS[n['type']]['implementation'], 'not_connected', (q, n['type']))   # 준비 중 노드는 깔지 않는다
            if 'T03' in {n['type'] for n in r['doc']['nodes']}:
                self.assertTrue(any(h['type'] == 'T03' for h in r['human']))
            topo_order(d)

    def test_trade_and_other_company_notes(self):
        r = assemble('엔비디아랑 삼성전자 주가 오를까?')
        self.assertTrue(any('판단하지 않아요' in n for n in r['notes']))
        self.assertTrue(any('엔비디아' in n for n in r['notes']))
        txt = json.dumps(r, ensure_ascii=False)
        for w in ('매수하세요', '매도하세요', '목표주가는'):
            self.assertNotIn(w, txt)

    def test_pick_after_ask_keeps_company(self):
        r = assemble('삼성 어때?')
        self.assertEqual(r['status'], 'ask')
        r2 = assemble('삼성 어때?', pick=['N09'])
        self.assertEqual([(t['type'], t['company']) for t in r2['targets']], [('N09', '005930')])

    def test_two_companies_price_chains(self):
        r = assemble('두 회사 주가 흐름 비교')
        self.assertEqual(sorted(t['company'] for t in r['targets']), ['000660', '005930'])
        t06 = sorted(n['config']['company'] for n in r['doc']['nodes'] if n['type'] == 'T06')
        self.assertEqual(t06, ['000660', '005930'])
        self.assertIn('T05', {n['type'] for n in r['doc']['nodes']})

    def test_n01_config_from_question(self):
        r = assemble('SK하이닉스 2025년 재고자산')
        n01 = next(n for n in r['doc']['nodes'] if n['type'] == 'N01')
        self.assertEqual(n01['config']['companies'], ['000660'])
        self.assertEqual(n01['config']['years'], [2025])
        self.assertIn('inventory', n01['config']['metrics'])

    def test_map(self):
        rows = [{'question': '외국인 수급', 'targets': [], 'gaps': ['N07'], 'signature': ''},
                {'question': '하이닉스 순매수', 'targets': ['N01'], 'gaps': ['N07'], 'signature': 'T01 → N01'},
                {'question': '매출', 'targets': ['N01'], 'gaps': [], 'signature': 'T01 → N01'}]
        m = map_from_audit(rows)
        self.assertEqual(m['total'], 3)
        self.assertEqual(m['gaps'][0]['id'], 'N07'); self.assertEqual(m['gaps'][0]['count'], 2)
        self.assertEqual(m['goals'][0], {'id': 'N01', 'label': m['goals'][0]['label'], 'count': 2})
        self.assertEqual(m['chains'][0]['count'], 2)


class Api(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        from mrn.server import create_app
        self.c = TestClient(create_app(self.tmp.name, port=4395))
        self.c.get('/api/health')
        self.c.headers['X-CSRF-Token'] = self.c.cookies.get('mrn_csrf')

    def tearDown(self):
        self.c.close(); self.tmp.cleanup()

    def test_assemble_run_and_map(self):
        r = self.c.post('/api/agent/assemble', json={'question': '삼성전자 2025년 매출과 영업이익은 얼마야?', 'cutoff': CUT}).json()
        self.assertEqual(r['status'], 'ok'); self.assertEqual(r['issues'], [])
        run = self.c.post('/api/runs', json={'doc': r['doc']})
        self.assertIn(run.status_code, (200, 201, 202), run.text)
        import time
        rid = run.json()['id']
        for _ in range(100):                          # 배경 실행이 끝난 뒤 정리
            if self.c.get(f'/api/runs/{rid}').json()['status'] not in ('waiting', 'queued', 'running'):
                break
            time.sleep(0.1)
        self.c.post('/api/agent/assemble', json={'question': '사업보고서에서 리스크 요인 어디에 나와?'})
        self.c.post('/api/agent/assemble', json={'question': '위험 요인은 원문에서 어디에 나와?'})
        m = self.c.get('/api/agent/assemble/map').json()
        self.assertEqual(m['total'], 3)
        self.assertEqual(m['gaps'][0]['id'], 'DOCS'); self.assertEqual(m['gaps'][0]['count'], 2)


if __name__ == '__main__':
    unittest.main()


class Wording(unittest.TestCase):
    def test_net_buying_is_not_trade_request(self):
        r = assemble('하이닉스 영업이익이랑 외국인 순매수 같이 보고 싶어')
        self.assertFalse(any('판단하지 않아요' in n for n in r['notes']))
        self.assertTrue(any('판단하지 않아요' in n for n in assemble('하이닉스 지금 매수해도 돼?')['notes']))

    def test_hits_not_double_counted(self):
        r = assemble('삼성전자 기업가치 계산')
        self.assertEqual(r['targets'][0]['hits'], ['기업가치'])
