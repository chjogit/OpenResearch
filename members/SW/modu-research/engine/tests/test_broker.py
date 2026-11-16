"""Broker forecast candidates, approval, T04 and N02 application. Skipped when PDFs or PyMuPDF are absent."""
import os as _os, pathlib as _pl
_os.environ.setdefault('MODU_NODES_BROKER_DIR', str(_pl.Path(__file__).resolve().parents[2] / '_sources' / 'broker_reports_fixture'))  # v0.22: 시험은 고정된 원래 보고서 15건으로
import copy
import tempfile
import time
import unittest
from fastapi.testclient import TestClient
from mrn.broker import broker_dir

try:
    import pymupdf  # noqa: F401
    HAVE = broker_dir().exists() and any(broker_dir().glob('*.pdf'))
except ImportError:
    HAVE = False

F = next((p.name for p in broker_dir().glob('20261007_company_261161000*.pdf')), '') if HAVE else ''  # 한화 2026-10-06
DCF = {"discount_basis": "WACC", "rate": "9", "terminal_growth": "2", "years": [
    {"growth": "0", "margin": "0", "tax": "22", "depreciation": "45000000", "capex": "60000000", "delta_wc": "5000000"},
    {"growth": "0", "margin": "0", "tax": "22", "depreciation": "50000000", "capex": "65000000", "delta_wc": "5000000"}],
    "bridge": {"debt": "20000000", "excess_cash": "90000000", "nonoperating_assets": "0", "minority": "10000000", "preferred": "0", "other_claims": "0"},
    "terminal_fcff": "250000000", "terminal_reason": "테스트용 정상화 FCFF 가정입니다"}


def doc(report=F, apply='yes'):
    return {'name': 't', 'cutoff': '2026-11-06T09:00:00+09:00', 'nodes': [
        {'id': 't01', 'type': 'T01', 'config': {}}, {'id': 'n01', 'type': 'N01', 'config': {}},
        {'id': 't03', 'type': 'T03', 'config': {'method': 'dcf', 'label': 't', 'shares': '5846279000', 'share_basis': '테스트 주식 수 근거입니다',
                                                'assumptions_note': '테스트용 가정 근거입니다', 'input_kind': 'illustrative_assumptions', 'model': copy.deepcopy(DCF)}},
        {'id': 't04', 'type': 'T04', 'config': {'report': report}}, {'id': 'n02', 'type': 'N02', 'config': {'apply_forecast': apply}}],
        'edges': [{'from_node': 't01', 'from_port': 'corpus', 'to_node': 'n01', 'to_port': 'corpus'},
                  {'from_node': 'n01', 'from_port': 'facts', 'to_node': 'n02', 'to_port': 'facts'},
                  {'from_node': 't03', 'from_port': 'assumptions', 'to_node': 'n02', 'to_port': 'assumptions'},
                  {'from_node': 't04', 'from_port': 'forecasts', 'to_node': 'n02', 'to_port': 'forecasts'}]}


@unittest.skipUnless(HAVE, 'broker PDFs or PyMuPDF not available')
class Broker(unittest.TestCase):
    def setUp(self):
        from mrn.server import create_app
        self.tmp = tempfile.TemporaryDirectory()
        self.c = TestClient(create_app(self.tmp.name, port=4395))
        self.c.get('/api/health')
        self.c.headers['X-CSRF-Token'] = self.c.cookies.get('mrn_csrf')
        self.scan = self.c.post('/api/broker/scan').json()

    def tearDown(self):
        self.tmp.cleanup()

    def run_doc(self, d):
        rid = self.c.post('/api/runs', json={'doc': d}).json()['id']
        for _ in range(100):
            run = self.c.get(f'/api/runs/{rid}').json()
            if run['status'] not in ('waiting', 'running'):
                break
            time.sleep(0.1)
        return {n['node_id']: n for n in run['nodes']}

    def test_scan_past_actuals_match_official(self):
        reps = self.c.get('/api/broker/reports').json()['reports']
        self.assertGreaterEqual(self.scan['candidates'], 40)
        withtable = [r for r in reps if r['status'] == 'ok']
        self.assertTrue(withtable)
        self.assertTrue(all(r['past_check'] == 'match' for r in withtable if r['checks']))
        self.assertTrue(all(c['state'] == 'proposed' for c in self.c.get('/api/broker/reports').json()['candidates']))

    def test_unapproved_blocks_and_approved_applies(self):
        n = self.run_doc(doc())
        self.assertEqual((n['t04']['status'], n['t04']['error_code']), ('held', 'no_approved'))
        self.assertEqual(n['n02']['status'], 'succeeded')  # forecasts optional; N02 runs without them
        self.c.post('/api/broker/review', json={'file': F, 'action': 'approve_report'})
        n = self.run_doc(doc())
        self.assertEqual(n['t04']['status'], 'succeeded')
        p = self.c.get('/api/packets/' + n['n02']['output_packet']).json()['payload']
        self.assertEqual([a['fiscal_year'] for a in p['forecast_applied']], [2026, 2027])
        self.assertIn('forecast_external', {i['kind'] for i in p['inputs']})
        g = float(p['forecast_applied'][0]['growth'])
        self.assertAlmostEqual(g, (715889000 / 333605938 - 1) * 100, places=3)
        n = self.run_doc(doc(apply='no'))
        p = self.c.get('/api/packets/' + n['n02']['output_packet']).json()['payload']
        self.assertEqual(p['forecast_applied'], [])

    def test_edit_needs_note_and_is_used(self):
        cands = [c for c in self.c.get('/api/broker/reports').json()['candidates'] if c['file'] == F]
        rev26 = next(c for c in cands if c['metric'] == 'revenue' and c['fiscal_year'] == 2026)
        self.assertEqual(self.c.post('/api/broker/review', json={'id': rev26['id'], 'action': 'edit', 'value_mn': '700000000'}).status_code, 422)
        self.c.post('/api/broker/review', json={'id': rev26['id'], 'action': 'edit', 'value_mn': '700000000', 'note': '시험 수정'})
        for c in cands:
            if c['id'] != rev26['id']:
                self.c.post('/api/broker/review', json={'id': c['id'], 'action': 'approve'})
        n = self.run_doc(doc())
        p = self.c.get('/api/packets/' + n['n02']['output_packet']).json()['payload']
        self.assertEqual(p['forecast_applied'][0]['revenue'], '700000000')

    def test_compare_and_timeline_no_merge(self):
        d = self.c.get('/api/broker/compare').json()
        self.assertEqual(len(d['rows']), self.scan['reports'])
        s = d['summary']['2026:revenue']
        self.assertIsNone(s['approved'])
        self.assertGreater(s['all']['count'], 5)
        self.assertIn('컨센서스가 아닙니다', d['notice'])
        mirae = d['timeline'].get('미래에셋증권', [])
        self.assertTrue(any(p['kind'] == 'prior_mention' and p['tp'] == 370000 for p in mirae))

    def test_rescan_keeps_reviews(self):
        self.c.post('/api/broker/review', json={'file': F, 'action': 'approve_report'})
        r = self.c.post('/api/broker/scan').json()
        self.assertEqual(r['reset'], 0)
        approved = [c for c in self.c.get('/api/broker/reports').json()['candidates'] if c['file'] == F and c['state'] == 'approved']
        self.assertEqual(len(approved), 4)


if __name__ == '__main__':
    unittest.main()
