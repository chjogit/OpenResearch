"""v0.36 내 질문 카드 — 저장(회사 비움) · 쉬운 화면 카드 · 다른 회사로 실행 · 묶음 내보내기/가져오기 · 숨기기 · 복잡도(카드 없으면 화면 그대로)."""
import json
import tempfile
import time
import unittest
from fastapi.testclient import TestClient
from mrn import mycards as M
from mrn.easy import plan


def relations_doc(co='005930'):
    d = plan('relations', co)
    d.pop('meta', None)
    d['name'] = f'환율과 함께 움직였나? — {co}'
    return d


class Template(unittest.TestCase):
    def test_company_fields_become_placeholder(self):
        tpl, probs = M.to_template(relations_doc('003490'))
        self.assertEqual(probs, [])
        t06 = next(n for n in tpl['nodes'] if n['type'] == 'T06')
        self.assertEqual(t06['config']['company'], M.PH)
        self.assertNotIn('003490', json.dumps(tpl))
        nodes, _ = M.fill(tpl, '000660')
        self.assertEqual(next(n for n in nodes if n['type'] == 'T06')['config']['company'], '000660')

    def test_not_portable_nodes_refused(self):
        d = relations_doc()
        d['nodes'].append({'id': 't03', 'type': 'T03', 'config': {}, 'x': 0, 'y': 0})
        _, probs = M.to_template(d)
        self.assertTrue(any('T03' in p for p in probs))

    def test_base_only_node_reason(self):
        d = plan('earnings', '005930')          # T01·N01(두 기준 회사만)
        tpl, probs = M.to_template(d)
        self.assertEqual(probs, [])
        with self.assertRaises(ValueError):
            M.fill(tpl, '003490')
        M.fill(tpl, '000660')

    def test_no_company_slot_refused(self):
        d = plan('macro', '005930')             # v0.37.7: 기준 회사 거시 카드에 T11이 붙어 회사 칸이 생겼으므로, 회사 칸 없는 사슬을 직접 만든다
        d['nodes'] = [n for n in d['nodes'] if n['type'] != 'T11']; d['edges'] = [e for e in d['edges'] if e['from_node'] != 't11']
        _, probs = M.to_template(d)
        self.assertTrue(any('회사를 고르는 노드' in p for p in probs))

    def test_bundle_tamper_detected(self):
        tpl, _ = M.to_template(relations_doc())
        b = M.bundle({'title': 't', 'sub': '', 'kind': '관계', 'template': tpl})
        self.assertEqual(M.check_bundle(b), tpl)
        b2 = json.loads(json.dumps(b)); b2['template']['nodes'][0]['config']['lookback'] = 260
        with self.assertRaises(ValueError):
            M.check_bundle(b2)
        self.assertNotIn('추천', json.dumps({k: v for k, v in b.items() if k != 'not_this'}, ensure_ascii=False))


class Api(unittest.TestCase):
    def setUp(self):
        from mrn.server import create_app
        self.tmp = tempfile.TemporaryDirectory()
        self.c = TestClient(create_app(self.tmp.name, port=4395))
        self.c.get('/api/health')
        self.c.headers['X-CSRF-Token'] = self.c.cookies.get('mrn_csrf')

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, **kw):
        body = {'doc': relations_doc(), 'title': '환율과 함께 움직였나?', 'sub': '', 'kind': '관계'} | kw
        return self.c.post('/api/mycards', json=body)

    def test_easy_screen_unchanged_without_cards(self):
        d = self.c.get('/api/easy/cards?company=005930').json()
        self.assertFalse(any(g['id'] == 'mine' for g in d['groups']))
        self.assertFalse(any(c['id'].startswith('my:') for c in d['cards']))

    def test_save_shows_card_and_runs_other_company(self):
        r = self.save()
        self.assertEqual(r.status_code, 201, r.text)
        card = r.json()['card']
        d = self.c.get('/api/easy/cards?company=000660').json()
        self.assertTrue(any(g['id'] == 'mine' for g in d['groups']))
        mine = [c for c in d['cards'] if c['id'] == card]
        self.assertEqual(len(mine), 1)
        self.assertTrue(mine[0]['ok'])
        self.assertEqual(mine[0]['group'], 'mine')
        rr = self.c.post('/api/easy/run', json={'card': card, 'company': '000660'})
        self.assertEqual(rr.status_code, 201, rr.text)
        rid = rr.json()['id']
        run = None
        for _ in range(150):
            run = self.c.get(f'/api/runs/{rid}').json()
            if run['status'] not in ('waiting', 'queued', 'running'):
                break
            time.sleep(0.1)
        t06 = next(n for n in run['doc']['nodes'] if n['type'] == 'T06')
        self.assertEqual(t06['config']['company'], '000660')
        a = self.c.get(f'/api/easy/answer/{rid}').json()
        self.assertEqual(a['card_title'], '환율과 함께 움직였나?')
        self.assertEqual(a['card'], card)
        steps = {s['id']: s for s in a['process']['steps']} if isinstance(a.get('process'), dict) and 'steps' in a['process'] else {}
        if 'plan' in steps:
            self.assertIn('질문 카드', steps['plan']['text'])

    def test_receipt_bundled_when_saved_right_after_run(self):
        doc = relations_doc('003490')
        rid = self.c.post('/api/runs', json={'doc': doc}).json()['id']
        for _ in range(150):
            if self.c.get(f'/api/runs/{rid}').json()['status'] not in ('waiting', 'queued', 'running'):
                break
            time.sleep(0.1)
        r = self.save(doc=doc, source_run=rid).json()
        self.assertTrue(r['with_receipt'])
        b = self.c.get(f"/api/mycards/{r['id']}/export").json()
        self.assertEqual(b['receipt']['format'], 'modu-research-receipt/1')
        v = self.c.post('/api/easy/verify', json={'receipt': b['receipt']}).json()
        self.assertTrue(v['ok'], v)

    def test_judgement_words_refused_in_title(self):
        r = self.save(title='매수 타이밍 카드')
        self.assertEqual(r.status_code, 422)

    def test_portable_rule_enforced_by_api(self):
        d = relations_doc()
        d['nodes'].append({'id': 't04', 'type': 'T04', 'config': {'report': ''}, 'x': 0, 'y': 0})
        self.assertEqual(self.save(doc=d).status_code, 422)

    def test_export_import_roundtrip_and_hide(self):
        cid = self.save().json()['id']
        b = self.c.get(f'/api/mycards/{cid}/export').json()
        self.assertEqual(b['format'], M.FORMAT)
        self.assertIn('결론·종목 추천·적중률이 아닙니다', b['not_this'])
        self.assertEqual(self.c.post('/api/mycards/import', json={'bundle': b}).status_code, 422)   # 같은 카드가 이미 있음
        b['title'] = '받은 카드'
        b['template_digest'] = M.digest(b['template'])
        r = self.c.post('/api/mycards/import', json={'bundle': b})
        self.assertEqual(r.status_code, 201, r.text)
        lst = self.c.get('/api/mycards').json()['cards']
        self.assertEqual(len(lst), 2)
        self.assertEqual({c['origin'] for c in lst}, {'made', 'imported'})
        bad = json.loads(json.dumps(b)); bad['template']['edges'] = []
        self.assertEqual(self.c.post('/api/mycards/import', json={'bundle': bad}).status_code, 422)
        self.assertEqual(self.c.post(f'/api/mycards/{cid}/hide', json={}).status_code, 200)
        self.assertEqual(len(self.c.get('/api/mycards').json()['cards']), 1)
        d = self.c.get('/api/easy/cards?company=005930').json()
        self.assertFalse(any(c['id'] == 'my:' + cid for c in d['cards']))

    def test_cards_are_per_browser(self):
        self.save()
        other = TestClient(self.c.app)
        other.get('/api/health')
        d = other.get('/api/easy/cards?company=005930').json()
        self.assertFalse(any(c['id'].startswith('my:') for c in d['cards']))

    def test_expert_page_links_script(self):
        self.assertIn('mycards.js', self.c.get('/expert').text)
        js = self.c.get('/static/mycards.js').text
        self.assertIn('내 질문 카드', js)


if __name__ == '__main__':
    unittest.main()
