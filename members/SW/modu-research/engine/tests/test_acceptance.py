"""Acceptance tests for v0.1 (spec §10). Run: python -m unittest discover -s tests -v"""
import os as _os, pathlib as _pl
_os.environ.setdefault('MODU_NODES_BROKER_DIR', str(_pl.Path(__file__).resolve().parents[2] / '_sources' / 'broker_reports_fixture'))  # v0.22: 시험은 고정된 원래 보고서 15건으로
import copy
import os
import socket
import tempfile
import threading
import time
import unittest
from fastapi.testclient import TestClient

from mrn import nodes as N
from mrn.engine import Engine
from mrn.server import create_app
from mrn.specs import REGISTRY, SPECS, plan, plan_workflow
from mrn.store import Store
from mrn.util import digest
from mrn.workflow import WorkflowDoc, validate, blocking, topo_order
from mrn.__main__ import port_free
from mrn.official import Cancelled

CUTOFF = '2026-11-06T07:00:00+09:00'
DCF = {"discount_basis": "WACC", "rate": "9", "terminal_growth": "2",
       "years": [{"growth": "5", "margin": "15", "tax": "22", "depreciation": "40000000", "capex": "50000000", "delta_wc": "2000000"}],
       "bridge": {"debt": "20000000", "excess_cash": "90000000", "nonoperating_assets": "0", "minority": "10000000", "preferred": "0", "other_claims": "0"},
       "terminal_fcff": "30000000", "terminal_reason": "테스트용 정상화 FCFF 가정입니다"}
T03 = {'method': 'dcf', 'label': '테스트', 'shares': '5900000000', 'share_basis': '테스트용 주식 수 근거입니다',
       'assumptions_note': '테스트용 가정 근거입니다', 'input_kind': 'illustrative_assumptions', 'model': DCF}


def chain(t03=None, n02=None, extra_nodes=(), extra_edges=()):
    return {'name': 'chain', 'cutoff': CUTOFF,
            'nodes': [{'id': 't01', 'type': 'T01', 'config': {}}, {'id': 'n01', 'type': 'N01', 'config': {}},
                      {'id': 't03', 'type': 'T03', 'config': t03 or copy.deepcopy(T03)},
                      {'id': 'n02', 'type': 'N02', 'config': n02 or {}}, *extra_nodes],
            'edges': [{'from_node': 't01', 'from_port': 'corpus', 'to_node': 'n01', 'to_port': 'corpus'},
                      {'from_node': 'n01', 'from_port': 'facts', 'to_node': 'n02', 'to_port': 'facts'},
                      {'from_node': 't03', 'from_port': 'assumptions', 'to_node': 'n02', 'to_port': 'assumptions'}, *extra_edges]}


def codes(doc):
    return {i['code'] for i in blocking(validate(WorkflowDoc.model_validate(doc), N.check_assumptions))}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.engine = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def run_doc(self, doc):
        d = WorkflowDoc.model_validate(doc)
        self.assertEqual(blocking(validate(d, N.check_assumptions)), [])
        rid = self.engine.start('me', d.model_dump(), topo_order(d), background=False)
        run = self.store.get_run('me', rid)
        return run, {n['node_id']: n for n in run['nodes']}


class T1Registry(unittest.TestCase):
    def test_twelve_nodes_and_badges(self):
        ids = [s['id'] for s in REGISTRY]
        self.assertEqual([f'N{i:02}' for i in range(1, 13)], [i for i in ids if i.startswith('N')][:12])
        self.assertEqual({SPECS[i]['tier'] for i in ids if i.startswith('N') and int(i[1:]) > 12}, {'addon'})   # v0.14: N13·N14 부가 노드(12노드 원안 밖)
        for s in REGISTRY:
            self.assertIn(s['implementation'], ('real', 'partial', 'not_connected'))
            if s['implementation'] == 'not_connected':
                self.assertTrue(s['not_connected_reason'])
        self.assertEqual({SPECS[f'N{i:02}']['tier'] for i in range(1, 13, 2)}, {'basic'})
        self.assertEqual({SPECS[f'N{i:02}']['tier'] for i in range(2, 13, 2)}, {'extension'})


class T2Plan(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(plan([])['count'], 6)
        self.assertEqual(plan(['macro', 'flow', 'sentiment'])['count'], 9)
        self.assertEqual(plan(['fundamentals', 'industry', 'macro', 'flow', 'technical', 'sentiment'])['count'], 12)

    def test_basic_always_and_no_unselected_extension(self):
        p = plan(['macro'])['specialists']
        self.assertTrue({'N01', 'N03', 'N05', 'N07', 'N09', 'N11'} <= set(p))
        self.assertEqual([x for x in p if SPECS[x]['tier'] == 'extension'], ['N06'])

    def test_generated_workflow_valid_shape(self):
        wf = plan_workflow(['fundamentals'])
        d = WorkflowDoc.model_validate({k: wf[k] for k in ('name', 'nodes', 'edges')})
        errs = codes(d.model_dump())
        self.assertEqual(errs, {'assumption_invalid'})  # only the empty T03 must be filled by a person


class T3InvalidConnections(unittest.TestCase):
    def test_type_mismatch(self):
        doc = chain(extra_nodes=[{'id': 't06', 'type': 'T06', 'config': {}}, {'id': 'n05', 'type': 'N05', 'config': {}}],
                    extra_edges=[{'from_node': 't06', 'from_port': 'prices', 'to_node': 'n05', 'to_port': 'corpus'}])
        self.assertIn('type_mismatch', codes(doc))

    def test_missing_required_input(self):
        doc = chain()
        doc['edges'] = doc['edges'][:2]
        self.assertIn('missing_input', codes(doc))

    def test_cycle(self):
        doc = {'name': 'c', 'cutoff': CUTOFF, 'nodes': [{'id': 'a', 'type': 'T05', 'config': {}}, {'id': 'b', 'type': 'T05', 'config': {}}],
               'edges': [{'from_node': 'a', 'from_port': 'report', 'to_node': 'b', 'to_port': 'results'},
                         {'from_node': 'b', 'from_port': 'report', 'to_node': 'a', 'to_port': 'results'}]}
        self.assertIn('cycle', codes(doc))

    def test_mixed_cutoff(self):
        doc = chain(extra_nodes=[{'id': 't01b', 'type': 'T01', 'config': {'cutoff': '2026-11-05T07:00:00+09:00'}}])
        self.assertIn('mixed_cutoff', codes(doc))

    def test_n06_requires_n05(self):
        doc = chain(extra_nodes=[{'id': 'n06', 'type': 'N06', 'config': {}}],
                    extra_edges=[{'from_node': 'n01', 'from_port': 'facts', 'to_node': 'n06', 'to_port': 'exposure'}])
        self.assertIn('N06_requires_N05', codes(doc))

    def test_assumption_invalid(self):
        bad = copy.deepcopy(T03)
        bad['model']['rate'] = '1'
        bad['model']['terminal_growth'] = '3'
        self.assertIn('assumption_invalid', codes(chain(t03=bad)))

    def test_port_overfilled_and_scope(self):
        doc = chain(extra_nodes=[{'id': 't03b', 'type': 'T03', 'config': copy.deepcopy(T03)}],
                    extra_edges=[{'from_node': 't03b', 'from_port': 'assumptions', 'to_node': 'n02', 'to_port': 'assumptions'}])
        self.assertIn('port_overfilled', codes(doc))
        doc = chain()
        doc['nodes'][1]['config'] = {'companies': ['000660']}
        self.assertIn('n02_scope', codes(doc))

    def test_unapproved_forecast_held(self):
        payload = {'forecasts': [{'broker': 'X', 'review': {'state': 'proposed'}}]}
        pkt = {'header': {'type': 'BrokerForecastPackage', 'payload_digest': digest(payload), 'produced_by': {'node_id': 't04'}}, 'payload': payload}
        fp = {'facts': [{'company': '005930', 'period': 2025, 'metric': 'revenue'}]}
        ap = {'method': 'dcf'}
        mk = lambda t, p: {'header': {'type': t, 'payload_digest': digest(p), 'produced_by': {'node_id': 'x'}}, 'payload': p}
        r = N.n02({'id': 'n02', 'config': {}}, {'facts': [mk('FactPackage', fp)], 'assumptions': [mk('AssumptionSet', ap)], 'forecasts': [pkt]}, None)
        self.assertEqual((r.status, r.error_code), ('held', 'unapproved_forecast'))


class T4to7Execution(Base):
    def test_real_chain_with_cell_evidence(self):
        run, n = self.run_doc(chain())
        self.assertEqual([n[k]['status'] for k in ('t01', 'n01', 't03', 'n02')], ['succeeded'] * 4)
        facts = self.store.get_packet(n['n01']['output_packet'])['payload']['facts']
        rev = next(f for f in facts if f['fact_id'] == '005930:2025:revenue')
        self.assertEqual(rev['value'], '333605938')
        self.assertEqual((rev['unit'], rev['scope'], rev['source']['rcept_no']), ('백만원', 'CFS', '20260310002820'))
        self.assertTrue(rev['source']['table_id'] and rev['source']['table_raw_hash'] and rev['source']['row'])
        v = self.store.get_packet(n['n02']['output_packet'])['payload']
        kinds = {i['kind'] for i in v['inputs']}
        self.assertTrue({'fact_official', 'assumption_illustrative', 'derived'} <= kinds)
        self.assertTrue(all(i.get('origin_ref') for i in v['inputs']))
        self.assertTrue(v['illustrative'])

    def _n02_with(self, mutate, fix_digest):
        run, n = self.run_doc(chain())
        fpk = self.store.get_packet(n['n01']['output_packet'])
        apk = self.store.get_packet(n['t03']['output_packet'])
        mutate(fpk['payload'])
        if fix_digest:
            fpk['header']['payload_digest'] = digest(fpk['payload'])

        class Ctx:
            cutoff = CUTOFF
            def step(self, m): pass
            def tool_call(self): pass
            def heartbeat(self): pass
            def cancelled(self): return False
        return N.n02({'id': 'n02', 'config': {}}, {'facts': [fpk], 'assumptions': [apk]}, Ctx())

    def test_tamper_without_digest_update_held(self):
        def m(p):
            next(f for f in p['facts'] if f['fact_id'] == '005930:2025:revenue')['value'] = '999999999'
        with self.assertRaises(N.Integrity):
            self._n02_with(m, fix_digest=False)

    def test_tamper_with_digest_update_held_by_reverify(self):
        def m(p):
            next(f for f in p['facts'] if f['fact_id'] == '005930:2025:revenue')['value'] = '999999999'
        r = self._n02_with(m, fix_digest=True)
        self.assertEqual((r.status, r.error_code), ('held', 'reverify_mismatch'))
        def h(p):
            next(f for f in p['facts'] if f['fact_id'] == '005930:2025:revenue')['source']['table_raw_hash'] = 'f' * 64
        r = self._n02_with(h, fix_digest=True)
        self.assertEqual(r.status, 'held')

    def test_narrow_gap_warning_and_sensitivity(self):
        t = copy.deepcopy(T03)
        t['model']['rate'] = '6'
        t['model']['terminal_growth'] = '4.5'
        run, n = self.run_doc(chain(t03=t))
        v = self.store.get_packet(n['n02']['output_packet'])['payload']
        self.assertTrue(any('2%p 미만' in w for w in v['alerts']))
        self.assertEqual(len(v['sensitivity']), 25)
        for c in v['sensitivity']:
            self.assertIn(c['status'], ('calculated', 'held'))
            if c['status'] == 'calculated':
                self.assertRegex(c['input_digest'], '^[a-f0-9]{64}$')
        self.assertTrue(any(c['status'] == 'held' for c in v['sensitivity']))  # g >= r cells are held, not computed

    def test_not_connected_is_not_zero(self):
        # v0.14: 모든 노드가 실동작이 되어, N11을 잠시 미연결로 바꿔 같은 원칙(미연결 ≠ 0)을 시험한다
        from mrn.specs import SPECS
        old = (SPECS['N11']['implementation'], SPECS['N11'].get('not_connected_reason'))
        SPECS['N11']['implementation'], SPECS['N11']['not_connected_reason'] = 'not_connected', '시험용 미연결'
        self.addCleanup(lambda: SPECS['N11'].update(implementation=old[0], not_connected_reason=old[1]))
        doc = {'name': 'nc', 'cutoff': CUTOFF, 'nodes': [{'id': 't08', 'type': 'T08', 'config': {}}, {'id': 'n11', 'type': 'N11', 'config': {}},
                                                         {'id': 'r', 'type': 'T05', 'config': {}}],
               'edges': [{'from_node': 't08', 'from_port': 'events', 'to_node': 'n11', 'to_port': 'events'},
                         {'from_node': 'n11', 'from_port': 'finding', 'to_node': 'r', 'to_port': 'results'}]}
        run, n = self.run_doc(doc)
        self.assertEqual(n['n11']['status'], 'not_connected')
        self.assertIsNone(n['n11']['output_packet'])
        rep = self.store.get_packet(n['r']['output_packet'])['payload']
        self.assertEqual(rep['entries'][0]['status'], 'not_connected')
        self.assertEqual(run['status'], 'partial')

    def test_cutoff_guards(self):
        doc = chain()
        doc['cutoff'] = '2026-10-01T00:00:00+09:00'
        run, n = self.run_doc(doc)
        self.assertEqual(n['t01']['status'], 'held')
        self.assertEqual(n['n02']['status'], 'held')  # propagates, not success


class T8Cancel(Base):
    def test_cancel_keeps_finished_results(self):
        orig = N.HANDLERS['N01']

        def slow(node, inputs, ctx):
            for _ in range(200):
                ctx.heartbeat()
                if ctx.cancelled():
                    raise Cancelled()
                time.sleep(0.02)
            return orig(node, inputs, ctx)
        import mrn.engine as E
        E.HANDLERS['N01'] = slow
        try:
            d = WorkflowDoc.model_validate(chain())
            rid = self.engine.start('me', d.model_dump(), topo_order(d))
            for _ in range(200):
                if any(x['node_id'] == 'n01' and x['status'] == 'running' for x in self.store.get_run('me', rid)['nodes']):
                    break
                time.sleep(0.02)
            self.store.request_cancel('me', rid)
            self.engine.threads[rid].join(10)
            run = self.store.get_run('me', rid)
            st = {x['node_id']: x['status'] for x in run['nodes']}
            self.assertEqual(run['status'], 'cancelled')
            self.assertEqual(st['t01'], 'succeeded')
            self.assertEqual(st['n01'], 'cancelled')
            self.assertEqual(st['n02'], 'cancelled')
            t01 = next(x for x in run['nodes'] if x['node_id'] == 't01')
            self.assertIsNotNone(self.store.get_packet(t01['output_packet']))
            self.assertFalse(self.engine.busy())
        finally:
            E.HANDLERS['N01'] = orig


class T9RestartAndApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def client(self):
        c = TestClient(create_app(self.tmp.name, port=4395))
        c.get('/api/health')
        c.headers['X-CSRF-Token'] = c.cookies.get('mrn_csrf')
        return c

    def test_save_reopen_restart_interrupted(self):
        c = self.client()
        r = c.post('/api/workflows', json={'doc': chain(), 'note': '처음'}).json()
        c.put(f"/api/workflows/{r['id']}", json={'doc': {**chain(), 'name': '새 이름'}})
        run = c.post('/api/runs', json={'doc': chain(), 'workflow_id': r['id'], 'workflow_version': 2})
        self.assertEqual(run.status_code, 201)
        rid = run.json()['id']
        for _ in range(100):
            if c.get(f'/api/runs/{rid}').json()['status'] not in ('waiting', 'running'):
                break
            time.sleep(0.05)
        before = c.get(f'/api/runs/{rid}').json()
        # simulate a crash mid-run on another record
        s = Store(self.tmp.name)
        s.create_run(c.cookies.get('mrn_owner'), chain(), ['t01'])
        c2 = TestClient(create_app(self.tmp.name, port=4395))
        c2.cookies.update(c.cookies)
        h = c2.get('/api/health').json()
        self.assertEqual(h['interrupted_on_start'][0], 1)
        wf = c2.get(f"/api/workflows/{r['id']}").json()
        self.assertEqual(wf['name'], '새 이름')
        self.assertIn('이름 변경', wf['history'][0]['note'])
        after = c2.get(f'/api/runs/{rid}').json()
        self.assertEqual([(n['node_id'], n['status'], n['output_packet']) for n in before['nodes']],
                         [(n['node_id'], n['status'], n['output_packet']) for n in after['nodes']])
        statuses = [x['status'] for x in c2.get('/api/runs').json()]
        self.assertIn('interrupted', statuses)

    def test_csrf_and_owner_isolation(self):
        c = self.client()
        r = c.post('/api/workflows', json={'doc': chain()}).json()
        bad = TestClient(create_app(self.tmp.name, port=4395))
        bad.get('/api/health')
        self.assertEqual(bad.post('/api/workflows', json={'doc': chain()}).status_code, 403)  # no CSRF header
        self.assertEqual(bad.get(f"/api/workflows/{r['id']}").status_code, 404)  # other owner
        self.assertEqual(c.post('/api/workflows', json={'doc': chain()}, headers={'Origin': 'http://evil.example'}).status_code, 403)

    def test_invalid_doc_rejected_before_run(self):
        c = self.client()
        doc = chain()
        doc['edges'] = doc['edges'][:1]
        r = c.post('/api/runs', json={'doc': doc})
        self.assertEqual(r.status_code, 422)
        self.assertIn('missing_input', {i['code'] for i in r.json()['detail']['issues']})


class T10Port(unittest.TestCase):
    def test_port_in_use_detected(self):
        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        s.listen(1)
        try:
            self.assertFalse(port_free(s.getsockname()[1]))
        finally:
            s.close()


if __name__ == '__main__':
    unittest.main()
