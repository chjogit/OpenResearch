"""v0.15 쉬운 화면: 질문 카드 사슬 · 답 카드 · 근거 영수증(C2) · 화면 용어 검사."""
import json, os, re, tempfile, time, unittest
from pathlib import Path
from fastapi.testclient import TestClient
from mrn import market
from mrn.easy import CARDS, plan, answer, TIER
from mrn.server import create_app
from mrn.workflow import WorkflowDoc, validate, blocking
from mrn import nodes as N
from tests.test_universe import make_v3, CUT
from tests.test_kit2_events import add_tables

WEB = Path(__file__).resolve().parents[1] / 'web'
BANNED = ['노드', '워크플로', '패킷', '포트', 'payload', 'T0', 'N0', 'N1']   # 쉬운 화면에 보이면 안 되는 말


class Plans(unittest.TestCase):
    def test_every_card_plan_is_valid(self):
        for co in ('005930', '042700'):
            for c in CARDS:
                d = WorkflowDoc.model_validate(plan(c['id'], co, CUT))
                self.assertEqual(blocking(validate(d, N.check_assumptions)), [], (co, c['id']))
                self.assertEqual(d.meta['card'], c['id'])

    def test_other_company_never_uses_base_corpus(self):
        for c in ('earnings', 'macro'):
            types = {n['type'] for n in plan(c, '042700')['nodes']}
            self.assertIn('T11', types)
            self.assertNotIn('T01', types)

    def test_tier_covers_all_kinds(self):
        from mrn.specs import KINDS
        self.assertEqual(set(TIER), set(KINDS))


class EasyBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ['MODU_NODES_NEON_DIR'] = self.tmp.name
        market._UNI.clear()
        snap = make_v3(self.tmp.name, days=370)
        add_tables(snap)
        # 근거 지도 개수표에 042700 재무·민감도·공시·지분을 표시
        cov_p = os.path.join(snap, 'coverage.jsonl')
        with open(cov_p, encoding='utf-8') as f:
            rows = [json.loads(l) for l in f]
        for r in rows:
            if r['ticker'] == '042700':
                for k in ('fin_annual', 'exposure', 'disclosure', 'holder'):
                    r[k] = {'n': 3, 'x': None}
        from tests.test_universe import _w, _h
        h, n = _w(cov_p, rows)
        mp = os.path.join(snap, 'manifest.json')
        with open(mp, encoding='utf-8') as f:
            man = json.load(f)
        man['tables']['coverage'].update(sha256=h, rows=n)
        with open(mp, 'w', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(man))
        with open(os.path.join(snap, 'manifest.sha256'), 'w', encoding='utf-8', newline='\n') as f:
            f.write(_h(mp) + '  manifest.json\n')
        self.c = TestClient(create_app(data_dir=os.path.join(self.tmp.name, 'data')))
        self.c.__enter__()
        self.c.get('/api/health')
        self.c.headers['X-CSRF-Token'] = self.c.cookies.get('mrn_csrf')

    def tearDown(self):
        self.c.__exit__(None, None, None)
        os.environ.pop('MODU_NODES_NEON_DIR', None)
        market._UNI.clear()
        self.tmp.cleanup()

    def wait(self, rid):
        for _ in range(100):
            r = self.c.get(f'/api/runs/{rid}').json()
            if r['status'] not in ('waiting', 'queued', 'running'):
                return r
            time.sleep(0.05)
        self.fail('run did not finish')


class EasyApi(EasyBase):

    def test_pages(self):
        self.assertIn('easy.js', self.c.get('/').text)
        self.assertIn('app.js', self.c.get('/expert').text)

    def test_cards_status(self):
        r = self.c.get('/api/easy/cards?company=042700').json()
        st = {c['id']: c for c in r['cards']}
        self.assertTrue(st['earnings']['ok'])
        self.assertFalse(st['nowcast']['ok'])                    # 두 기준 기업만
        self.assertFalse(r['cards'][0]['ok'] is None)
        r = self.c.get('/api/easy/cards?company=066570').json()    # 자료가 없는 회사
        self.assertIn('없어요', {c['id']: c for c in r['cards']}['price']['why'])

    def test_answer_receipt_verify(self):
        rid = self.c.post('/api/easy/run', json={'card': 'earnings', 'company': '042700', 'cutoff': CUT}).json()['id']
        self.wait(rid)
        a = self.c.get(f'/api/easy/answer/{rid}').json()
        self.assertEqual(a['name'], '한미반도체')
        self.assertTrue(a['key'])
        self.assertEqual(a['key'][0]['label'], '한미반도체 2025년 매출액')          # 최신 연도 먼저
        self.assertEqual(a['key'][0]['text'], '6,000억 원 (연결)')
        self.assertTrue(all(i['tier'] in ('fact', 'calc', 'estimate') and i['kind_label'] for i in a['items']))
        self.assertIn('매수·매도', a['not_this'])
        rc = self.c.get(f'/api/easy/receipt/{rid}').json()
        self.assertNotIn('t05', [r['node'] for r in rc['results']])
        v = self.c.post('/api/easy/verify', json={'receipt': rc}).json()
        self.assertTrue(v['ok'], v)
        bad = json.loads(json.dumps(rc)); bad['results'][0]['payload_digest'] = '0' * 64
        self.assertFalse(self.c.post('/api/easy/verify', json={'receipt': bad}).json()['ok'])
        bad = json.loads(json.dumps(rc)); bad['chain']['nodes'][0]['config']['company'] = '005930'
        self.assertIn('사슬', self.c.post('/api/easy/verify', json={'receipt': bad}).json()['reason'])
        self.assertEqual(self.c.post('/api/easy/verify', json={'receipt': {'x': 1}}).status_code, 422)

    def test_unknowns_and_limits_are_separated(self):
        rid = self.c.post('/api/easy/run', json={'card': 'events', 'company': '042700', 'cutoff': CUT}).json()['id']
        self.wait(rid)
        a = self.c.get(f'/api/easy/answer/{rid}').json()
        self.assertTrue(any('원인' in x for x in a['limits']))
        self.assertFalse(any('하지 않음' in u['text'] for u in a['unknown']))

    def test_time_machine_earlier_cutoff_has_less(self):
        ids = []
        for cut in (CUT, '2026-01-15T16:00:00+09:00'):
            rid = self.c.post('/api/easy/run', json={'card': 'earnings', 'company': '042700', 'cutoff': cut}).json()['id']
            self.wait(rid); ids.append(rid)
        now, then = (self.c.get(f'/api/easy/answer/{i}').json() for i in ids)
        self.assertGreater(now['count']['fact'], then['count']['fact'])      # 2025 사업보고서(2026-03 접수)는 그때 없었음


class Wording(unittest.TestCase):
    def test_no_jargon_on_easy_screen(self):
        html = (WEB / 'easy.html').read_text(encoding='utf-8')
        text = re.sub(r'<[^>]+>', ' ', html)
        js = (WEB / 'easy.js').read_text(encoding='utf-8')
        lits = ' '.join(re.findall(r"'([^'\n]*)'|`([^`]*)`", js) and [a or b for a, b in re.findall(r"'([^'\n]*)'|`([^`]*)`", js)])
        lits = re.sub(r'\$\{[^}]*\}', ' ', lits)
        lits = re.sub(r'/api/[^\s\'"`]*|#[a-zA-Z]+|\.[a-z][a-zA-Z]+|data-[a-z]+|[a-z]+\[[^\]]*\]', ' ', lits)
        for w in BANNED:
            self.assertNotIn(w, text, f'easy.html: {w}')
            hits = [m.start() for m in re.finditer(re.escape(w), lits) if not lits[max(0, m.start() - 1)].isalnum() or w[0].isalpha() is False]
            self.assertFalse(w in ('노드', '워크플로', '패킷', '포트') and hits, f'easy.js: {w}')


if __name__ == '__main__':
    unittest.main()


class Naming(unittest.TestCase):
    """v0.17.1: 「근거 영수증」 → 「근거 확인서」, 서랍 칸 제목 「출처근거」 (파일 형식 id는 그대로)."""
    def test_names_on_screen(self):
        js = (WEB / 'easy.js').read_text(encoding='utf-8'); html = (WEB / 'easy.html').read_text(encoding='utf-8')
        for s in (js, html):
            self.assertNotIn('영수증', s)
        self.assertIn('근거 확인서 내려받기', js)
        self.assertIn('<h3>출처근거</h3>', js)
        self.assertIn('확인서로 다시 계산해 보기', html)
        self.assertIn('보증이 아니에요', html)

    def test_format_id_unchanged(self):
        import inspect
        from mrn import easy
        self.assertIn("'modu-research-receipt/1'", inspect.getsource(easy))
