"""v0.16 C: 스스로 고치는 근거 사슬 — 제안·승인·재계산·영수증 기록."""
import json, time, unittest
from mrn.repair import suggest, apply
from mrn.easy import plan
from mrn.workflow import WorkflowDoc, validate, blocking
from mrn import nodes as N
from tests.test_easy import EasyBase
from tests.test_universe import CUT


class RepairUnit(unittest.TestCase):
    def test_swap_t01_to_t11_marks_downgrade(self):
        doc = plan('earnings', '000660', '2026-09-30T16:00:00+09:00')
        run = {'doc': doc, 'nodes': [{'node_id': n['id'], 'node_type': n['type'], 'status': 'held' if n['type'] == 'T01' else 'blocked',
                                       'error_code': 'cutoff_before_corpus' if n['type'] == 'T01' else 'upstream_unavailable',
                                       'output_packet': None, 'reason': ''} for n in doc['nodes']]}
        ps = suggest(run, lambda pid: None)
        self.assertEqual([p['id'] for p in ps], ['swap-t01-t01'])
        self.assertTrue(ps[0]['downgrade'])
        nd = apply(doc, ps, {'swap-t01-t01'})
        types = {n['type'] for n in nd['nodes']}
        self.assertNotIn('T01', types)
        self.assertIn('T11', types)
        self.assertEqual(blocking(validate(WorkflowDoc.model_validate(nd), N.check_assumptions)), [])
        self.assertEqual(nd['meta']['repairs'][0]['id'], 'swap-t01-t01')
        self.assertIn('T01', {n['type'] for n in doc['nodes']})          # 원래 문서는 그대로

    def test_nothing_chosen_is_refused(self):
        with self.assertRaises(ValueError):
            apply(plan('price', '042700'), [], set())


class RepairApi(EasyBase):
    def run_card(self, card, co, cut):
        rid = self.c.post('/api/easy/run', json={'card': card, 'company': co, 'cutoff': cut}).json()['id']
        self.wait(rid)
        return rid

    def test_years_repair_flow_and_receipt(self):
        rid = self.run_card('earnings', '042700', '2026-01-15T16:00:00+09:00')
        before = self.c.get(f'/api/easy/answer/{rid}').json()
        ps = self.c.get(f'/api/easy/repairs/{rid}').json()['proposals']
        self.assertEqual([p['id'] for p in ps], ['years-n01'])
        self.assertNotIn('patch', ps[0])                                   # 내부 변경 내용은 화면에 보내지 않음
        new = self.c.post('/api/easy/repair', json={'run_id': rid, 'ids': ['years-n01']}).json()['id']
        self.wait(new)
        after = self.c.get(f'/api/easy/answer/{new}').json()
        self.assertEqual(after['repaired_from'], rid)
        self.assertEqual(after['repairs'][0]['id'], 'years-n01')
        self.assertTrue(any('2024년 매출액' in i['label'] for i in after['items']))
        self.assertEqual(self.c.get(f'/api/easy/answer/{rid}').json()['count'], before['count'])   # 원래 답은 그대로
        rc = self.c.get(f'/api/easy/receipt/{new}').json()
        self.assertEqual(rc['repairs'][0]['id'], 'years-n01')
        v = self.c.post('/api/easy/verify', json={'receipt': rc}).json(); self.assertTrue(v['ok'], v)
        bad = json.loads(json.dumps(rc)); bad['repairs'] = []                # 고친 이력을 지우면 영수증 번호가 안 맞음
        self.assertFalse(self.c.post('/api/easy/verify', json={'receipt': bad}).json()['ok'])

    def test_missing_data_skips_only_dependent_steps(self):
        rid = self.run_card('events', '066570', CUT)                        # 시세·공시 파일이 없는 회사
        ids = [p['id'] for p in self.c.get(f'/api/easy/repairs/{rid}').json()['proposals']]
        self.assertIn('skip-t06', ids)
        self.assertIn('lookback-t08', ids)
        r = self.c.post('/api/easy/repair', json={'run_id': rid, 'ids': ['skip-t06']})
        self.assertEqual(r.status_code, 201)
        run = self.wait(r.json()['id'])
        self.assertNotIn('n12', {n['node_id'] for n in run['nodes']})
        self.assertIn('n11', {n['node_id'] for n in run['nodes']})

    def test_unknown_id_refused(self):
        rid = self.run_card('price', '042700', CUT)
        self.assertEqual(self.c.post('/api/easy/repair', json={'run_id': rid, 'ids': ['nope']}).status_code, 422)


if __name__ == '__main__':
    unittest.main()
