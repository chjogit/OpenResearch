"""Rule-based self-correcting agent: fixes it may make, things it must ask a person, things it must stop on."""
import os as _os, pathlib as _pl
_os.environ.setdefault('MODU_NODES_BROKER_DIR', str(_pl.Path(__file__).resolve().parents[2] / '_sources' / 'broker_reports_fixture'))  # v0.22: 시험은 고정된 원래 보고서 15건으로
import copy
import tempfile
import time
import unittest
from fastapi.testclient import TestClient
from mrn.agent import match_rule, RULES

try:
    import pymupdf  # noqa: F401
    from mrn.broker import broker_dir
    HAVE_PDF = broker_dir().exists() and any(broker_dir().glob('*.pdf'))
except ImportError:
    HAVE_PDF = False

DCF = {"discount_basis": "WACC", "rate": "9", "terminal_growth": "2", "years": [
    {"growth": "0", "margin": "0", "tax": "22", "depreciation": "45000000", "capex": "60000000", "delta_wc": "5000000"},
    {"growth": "0", "margin": "0", "tax": "22", "depreciation": "50000000", "capex": "65000000", "delta_wc": "5000000"}],
    "bridge": {"debt": "20000000", "excess_cash": "90000000", "nonoperating_assets": "0", "minority": "10000000", "preferred": "0", "other_claims": "0"},
    "terminal_fcff": "250000000", "terminal_reason": "테스트용 정상화 FCFF 가정입니다"}
T03 = {'method': 'dcf', 'label': 't', 'shares': '5846279000', 'share_basis': '테스트 주식 수 근거입니다',
       'assumptions_note': '테스트용 가정 근거입니다', 'input_kind': 'illustrative_assumptions', 'model': DCF}
E = lambda a, ap, b, bp: {'from_node': a, 'from_port': ap, 'to_node': b, 'to_port': bp}
N = lambda i, t, c=None: {'id': i, 'type': t, 'config': c or {}}


def dcf_doc(t04s=1, reports=None, n01=None):
    nodes = [N('t01', 'T01'), N('n01', 'N01', n01), N('t03', 'T03', copy.deepcopy(T03))]
    edges = [E('t01', 'corpus', 'n01', 'corpus')]
    for i in range(t04s):
        nodes += [N(f't04_{i}', 'T04', {'report': (reports or [''] * t04s)[i]}), N(f'n02_{i}', 'N02', {'apply_forecast': 'yes'})]
        edges += [E('n01', 'facts', f'n02_{i}', 'facts'), E('t03', 'assumptions', f'n02_{i}', 'assumptions'), E(f't04_{i}', 'forecasts', f'n02_{i}', 'forecasts')]
    return {'name': 'a', 'cutoff': '', 'nodes': nodes, 'edges': edges}


class AgentBase(unittest.TestCase):
    def setUp(self):
        from mrn.server import create_app
        self.tmp = tempfile.TemporaryDirectory()
        self.c = TestClient(create_app(self.tmp.name, port=4395))
        self.c.get('/api/health')
        self.c.headers['X-CSRF-Token'] = self.c.cookies.get('mrn_csrf')

    def tearDown(self):
        self.tmp.cleanup()

    def agent(self, doc, **kw):
        r = self.c.post('/api/agent/runs', json={'doc': doc} | kw)
        self.assertEqual(r.status_code, 201, r.text)
        aid = r.json()['id']
        for _ in range(300):
            a = self.c.get(f'/api/agent/runs/{aid}').json()
            if a['status'] != 'running':
                return a
            time.sleep(0.1)
        self.fail('agent did not finish')

    def final_nodes(self, a):
        run = self.c.get(f"/api/runs/{a['final_run']}").json()
        return {n['node_id']: n for n in run['nodes']}


class Rules(unittest.TestCase):
    def test_rule_lookup(self):
        self.assertEqual(match_rule('run', 'T04', 'held', 'report_not_selected')['id'], 'R01')
        self.assertEqual(match_rule('run', 'N06', 'partial', None)['id'], 'R14')
        self.assertEqual(match_rule('run', 'X', 'held', 'something_new')['id'], 'R99')
        self.assertEqual(match_rule('check', '', '-', 'cycle')['action'], 'ask')
        self.assertTrue(all(r['why'] for r in RULES))
        self.assertNotIn('approve', {r.get('fix') for r in RULES})


class AgentNoPdf(AgentBase):
    def test_partial_is_accepted_and_reported(self):
        doc = {'name': 'm', 'cutoff': '', 'nodes': [N('t01', 'T01'), N('n05', 'N05'), N('n06', 'N06')],
               'edges': [E('t01', 'corpus', 'n05', 'corpus'), E('n05', 'exposure', 'n06', 'exposure')]}
        a = self.agent(doc)
        self.assertEqual(a['status'], 'completed')
        self.assertEqual([x['rule'] for x in a['accepted']], ['R14'])
        self.assertEqual(a['iteration'], 1)

    def test_scope_fix_before_run(self):
        doc = dcf_doc(0, n01={'companies': ['000660'], 'years': [2024, 2025], 'metrics': ['revenue', 'operatingProfit']})
        doc['nodes'].append(N('n02', 'N02'))
        doc['edges'] += [E('n01', 'facts', 'n02', 'facts'), E('t03', 'assumptions', 'n02', 'assumptions')]
        a = self.agent(doc)
        self.assertEqual(a['status'], 'completed', a['note'])
        self.assertIn({'node': 'n01', 'field': 'companies', 'before': ['000660'], 'after': ['000660', '005930']}, a['changes'])
        self.assertEqual(self.final_nodes(a)['n02']['status'], 'succeeded')

    def test_missing_metric_fix_after_run(self):
        doc = dcf_doc(0, n01={'companies': ['005930'], 'years': [2024, 2025], 'metrics': ['operatingProfit']})
        doc['nodes'].append(N('n02', 'N02'))
        doc['edges'] += [E('n01', 'facts', 'n02', 'facts'), E('t03', 'assumptions', 'n02', 'assumptions')]
        a = self.agent(doc)
        self.assertEqual(a['status'], 'completed', a['note'])
        self.assertEqual(a['iteration'], 2)
        self.assertEqual(a['changes'][0]['after'], ['operatingProfit', 'revenue'])

    def test_blocking_validation_asks(self):
        doc = {'name': 'x', 'cutoff': '', 'nodes': [N('n01', 'N01')], 'edges': []}
        a = self.agent(doc)
        self.assertEqual(a['status'], 'needs_human')
        self.assertEqual(a['runs'], [])
        self.assertTrue(a['asks'])

    def test_no_report_available_asks(self):
        a = self.agent(dcf_doc(1))
        self.assertEqual(a['status'], 'needs_human')
        self.assertEqual(a['asks'][0]['rule'], 'R01')
        self.assertEqual(a['changes'], [])


@unittest.skipUnless(HAVE_PDF, 'broker PDFs or PyMuPDF not available')
class AgentBroker(AgentBase):
    def setUp(self):
        super().setUp()
        self.c.post('/api/broker/scan')
        self.reps = self.c.get('/api/broker/reports').json()['reports']

    def approve(self, prefix):
        f = next(r['file'] for r in self.reps if r['file'].startswith(prefix))
        self.c.post('/api/broker/review', json={'file': f, 'action': 'approve_report'})
        return f

    def test_picks_report_by_policy(self):
        f = self.approve('20261007_company_261161000')
        a = self.agent(dcf_doc(1))
        self.assertEqual(a['status'], 'completed', a['note'])
        self.assertEqual(a['changes'][0]['after'], f)
        n = self.final_nodes(a)
        self.assertEqual((n['t04_0']['status'], n['n02_0']['status']), ('succeeded', 'succeeded'))
        self.assertEqual(a['summary']['held'], [])
        self.assertTrue(any('주당가치' in t for t in a['summary']['published']))

    def test_never_overrides_human_choice(self):
        self.approve('20261007_company_261161000')
        other = next(r['file'] for r in self.reps if r['file'].startswith('20260922'))
        a = self.agent(dcf_doc(1, reports=[other]))
        self.assertEqual(a['status'], 'needs_human')
        self.assertEqual(a['asks'][0]['rule'], 'R02')
        self.assertEqual(a['changes'], [])
        self.assertEqual(next(n for n in a['doc_final']['nodes'] if n['id'] == 't04_0')['config']['report'], other)

    def test_forecast_choice_objection(self):
        f1 = self.approve('20261007_company_261161000')
        f2 = self.approve('20260922')
        a = self.agent(dcf_doc(1, reports=[f1]))
        r = self.c.post('/api/agent/objections', json={'run_id': a['final_run'], 'node_id': 't04_0', 'field': 'report', 'value': f2, 'reason': '다른 증권사 시각으로 보고 싶음'})
        self.assertEqual(r.status_code, 201, r.text)
        for _ in range(300):
            ob = self.c.get(f"/api/agent/objections/{r.json()['id']}").json()
            if ob['agent']['status'] != 'running':
                break
            time.sleep(0.1)
        row = ob['comparison']['per_share'][0]
        self.assertNotEqual(row['before'], row['after'])

    def test_normalized_scenario_monotonic(self):
        self.approve('20261007_company_261161000')
        nodes = [N('t01', 'T01'), N('n01', 'N01'), N('t04', 'T04'), N('t05', 'T05')]
        edges = [E('t01', 'corpus', 'n01', 'corpus')]
        for i, v in enumerate(['150000000', '250000000', '350000000']):
            t = copy.deepcopy(T03); t['model']['terminal_fcff'] = v
            nodes += [N(f't03_{i}', 'T03', t), N(f'n02_{i}', 'N02', {'apply_forecast': 'yes'})]
            edges += [E('n01', 'facts', f'n02_{i}', 'facts'), E(f't03_{i}', 'assumptions', f'n02_{i}', 'assumptions'),
                      E('t04', 'forecasts', f'n02_{i}', 'forecasts'), E(f'n02_{i}', 'valuation', 't05', 'results')]
        a = self.agent({'name': 'n', 'cutoff': '', 'nodes': nodes, 'edges': edges})
        self.assertEqual(a['status'], 'completed', a['note'])
        n = self.final_nodes(a)
        vals = [float(self.c.get('/api/packets/' + n[f'n02_{i}']['output_packet']).json()['payload']['per_share']) for i in range(3)]
        self.assertTrue(vals[0] < vals[1] < vals[2])
        self.assertGreater(vals[2] / vals[0], 1.3)          # long-run assumption moves value far more than the forecast spread
        self.assertEqual(a['summary']['held'], [])
        self.assertTrue(any('말기가치 비중' in t for t in a['summary']['published']))

    def test_three_distinct_brokers(self):
        for r in self.reps:
            self.c.post('/api/broker/review', json={'file': r['file'], 'action': 'approve_report'})
        a = self.agent(dcf_doc(3))
        self.assertEqual(a['status'], 'completed', a['note'])
        brokers = [c['label'].split(' ', 1)[1] for c in a['changes']]
        self.assertEqual(len(set(brokers)), 3)
        files = [c['after'] for c in a['changes']]
        self.assertEqual(len(set(files)), 3)


class Gate(AgentBase):
    def test_summary_numbers_are_all_bound(self):
        doc = {'name': 'f', 'cutoff': '', 'nodes': [N('t01', 'T01'), N('n01', 'N01')], 'edges': [E('t01', 'corpus', 'n01', 'corpus')]}
        a = self.agent(doc)
        sm = a['summary']
        self.assertEqual(sm['held'], [])
        self.assertTrue(sm['published'])
        self.assertNotIn('red', sm['counts'])
        self.assertGreaterEqual(sm['bound'], 4)

    def test_gate_withholds_fabrication_and_judgement(self):
        doc = {'name': 'f', 'cutoff': '', 'nodes': [N('t01', 'T01'), N('n01', 'N01')], 'edges': [E('t01', 'corpus', 'n01', 'corpus')]}
        a = self.agent(doc)
        g = self.c.post('/api/agent/gate', json={'run_id': a['final_run'], 'text':
            '삼성전자 2025년 매출액은 400조원입니다. 삼성전자 2025년 매출액은 {{fact:005930:2025:revenue}}입니다. 실적 모멘텀이 강합니다. 매수 추천합니다.'}).json()
        self.assertEqual(len(g['published']), 1)
        self.assertIn('333,605,938', g['published'][0])
        self.assertEqual(len(g['held']), 3)

    def test_unknown_value_slot_is_mismatch(self):
        doc = {'name': 'f', 'cutoff': '', 'nodes': [N('t01', 'T01'), N('n01', 'N01')], 'edges': [E('t01', 'corpus', 'n01', 'corpus')]}
        a = self.agent(doc)
        g = self.c.post('/api/agent/gate', json={'run_id': a['final_run'], 'text': '주당가치는 {{val:n02.per_share}}입니다.'}).json()
        self.assertEqual(g['published'], [])


class Planner(AgentBase):
    def plan(self, q, persona=None):
        return self.c.post('/api/agent/plan', json={'question': q, 'persona': persona}).json()

    def test_keyword_choices(self):
        self.assertEqual(self.plan('삼성전자 2025년 매출과 영업이익이 공시에 얼마로 나와?')['example_id'], 'facts-only')
        self.assertEqual(self.plan('금리랑 환율 노출은 어때?')['example_id'], 'facts-macro')
        self.assertEqual(self.plan('증권사 전망으로 기업가치 DCF 계산해줘')['example_id'], 'samsung-broker-dcf')
        self.assertEqual(self.plan('증권사별 전망을 넣으면 기업가치가 얼마나 갈리는지 비교해줘')['example_id'], 'broker-compare')
        self.assertEqual(self.plan('업황 정점 이후 정상화 이익에 따라 기업가치가 어떻게 달라져?')['example_id'], 'normalized-scenario')
        r = self.plan('음', 'expert-wide')
        self.assertEqual((r['example_id'], r['method']), ('broker-compare', 'keyword'))

    def test_trade_and_scope_notes(self):
        r = self.plan('삼성전자 지금 사야 해?')
        self.assertTrue(any('판단은 하지 않습니다' in n for n in r['notes']))
        r = self.plan('LG전자 실적 알려줘')
        self.assertTrue(any('삼성전자·SK하이닉스뿐' in n for n in r['notes']))

    def test_model_answer_must_be_known_template(self):
        import json, os, threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        replies = iter(['{"example_id": "broker-compare", "reason": "비교 질문"}', '{"example_id": "make-up-anything", "reason": "x"}'])

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                body = json.dumps({'choices': [{'message': {'content': next(replies)}}]}).encode()
                self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers(); self.wfile.write(body)

            def log_message(self, *a):
                pass
        srv = HTTPServer(('127.0.0.1', 0), H)
        th = threading.Thread(target=srv.serve_forever, daemon=True); th.start()
        os.environ['MODU_NODES_LLM_URL'] = f'http://127.0.0.1:{srv.server_port}/v1'
        os.environ['MODU_NODES_LLM_MODEL'] = 'fake'
        try:
            r = self.plan('삼성전자 공시 실적')
            self.assertEqual((r['example_id'], r['method']), ('broker-compare', 'model'))
            r = self.plan('삼성전자 공시 실적')
            self.assertEqual((r['example_id'], r['method']), ('facts-only', 'keyword'))
            self.assertIn('목록에 없는', r['model_note'])
        finally:
            del os.environ['MODU_NODES_LLM_URL'], os.environ['MODU_NODES_LLM_MODEL']
            srv.shutdown(); srv.server_close()

    def test_no_model_configured_falls_back(self):
        r = self.plan('삼성전자 공시 실적')
        self.assertEqual(r['method'], 'keyword')
        self.assertIn('모델 미설정', r['model_note'])


class Objection(AgentBase):
    def base_run(self):
        doc = dcf_doc(0, n01={'companies': ['005930'], 'years': [2024, 2025], 'metrics': ['revenue', 'operatingProfit']})
        doc['nodes'].append(N('n02', 'N02'))
        doc['edges'] += [E('n01', 'facts', 'n02', 'facts'), E('t03', 'assumptions', 'n02', 'assumptions')]
        a = self.agent(doc)
        self.assertEqual(a['status'], 'completed', a['note'])
        return a['final_run']

    def wait(self, oid):
        for _ in range(300):
            ob = self.c.get(f'/api/agent/objections/{oid}').json()
            if ob['agent']['status'] != 'running':
                return ob
            time.sleep(0.1)
        self.fail('objection did not finish')

    def test_assumption_objection_reruns_and_compares(self):
        rid = self.base_run()
        before = self.c.get(f'/api/runs/{rid}').json()
        f = self.c.get(f'/api/agent/objection-fields?run_id={rid}&node_id=t03').json()['fields']
        self.assertIn('model.rate', [x['field'] for x in f])
        r = self.c.post('/api/agent/objections', json={'run_id': rid, 'node_id': 't03', 'field': 'model.rate', 'value': '11', 'reason': '할인율 9%는 낮다고 봅니다'})
        self.assertEqual(r.status_code, 201, r.text)
        ob = self.wait(r.json()['id'])
        self.assertEqual(ob['agent']['status'], 'completed')
        row = ob['comparison']['per_share'][0]
        self.assertLess(float(row['change_pct']), 0)               # higher discount rate -> lower value
        self.assertEqual(ob['change']['before'], '9')
        self.assertEqual(ob['reason'], '할인율 9%는 낮다고 봅니다')
        self.assertEqual(self.c.get(f'/api/runs/{rid}').json()['doc'], before['doc'])   # original untouched
        self.assertEqual(ob['agent']['summary']['held'], [])

    def test_rejections(self):
        rid = self.base_run()
        bad = [({'node_id': 't03', 'field': 'model.rate', 'value': '11', 'reason': '짧음'}, '사유'),
               ({'node_id': 't03', 'field': 'model.rate', 'value': '9', 'reason': '같은 값으로 이의'}, '같습니다'),
               ({'node_id': 't03', 'field': 'model.rate', 'value': '열한', 'reason': '숫자가 아님 시험'}, '숫자'),
               ({'node_id': 'n02', 'field': 'company', 'value': '000660', 'reason': '허용되지 않는 항목'}, '없는 항목'),
               ({'node_id': 't01', 'field': 'cutoff', 'value': 'x', 'reason': '대상 아닌 노드 시험'}, '대상이 아닙니다')]
        for body, word in bad:
            r = self.c.post('/api/agent/objections', json={'run_id': rid} | body)
            self.assertEqual(r.status_code, 422, body)
            self.assertIn(word, r.text)

    def test_fact_recheck_cannot_edit_values(self):
        rid = self.base_run()
        r = self.c.post('/api/agent/objections', json={'run_id': rid, 'node_id': 'n01', 'field': '', 'reason': '매출 숫자가 이상해 보입니다'})
        ob = self.wait(r.json()['id'])
        self.assertEqual(ob['comparison']['facts_changed'], [])
        self.assertGreater(ob['comparison']['facts_compared'], 0)
        r = self.c.post('/api/agent/objections', json={'run_id': rid, 'node_id': 'n01', 'field': 'value', 'value': '1', 'reason': '값을 바꾸려는 시도'})
        self.assertEqual(r.status_code, 422)


if __name__ == '__main__':
    unittest.main()
