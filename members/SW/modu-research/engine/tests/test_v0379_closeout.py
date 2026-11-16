"""v0.37.9 v0.37 마무리.
- P02-11 (박상혁 「페르소나 12조합 숫자·근거 동일」 → 우리 앱에 맞춤, PM 판단): 같은 질문을 여러 입구·여러 화면으로 봐도 숫자·근거·보류가 같은가.
  입구 2개(쉬운 화면 카드 / 전문가 모드 직접 실행) × 보는 곳 4개(답 카드 / 전문가 모드 결과 / 근거 확인서 / 공유용 페이지) × 질문 카드 5개, 그리고 같은 입력 두 번.
- P04-10 「예측: 보류」, CH-N05-7 거시 지표 PIT 한계: 고정 문구가 늘 보이고, 단계 상태를 바꾸지 않는다."""
import html, re
from mrn.easy import plain, plan
from mrn.nodes import PRED_HOLD, PIT_HOLD
from tests.test_easy import EasyBase, CUT

CARDS = ('events', 'price', 'earnings', 'macro', 'holders')
CO = '042700'


def _norm(a):
    """답 카드에서 실행마다 달라도 되는 것(실행 번호·작동 원리 띠의 시각)을 뺀 나머지."""
    return {'items': [(i['label'], i['text'], i['formula'], i['kind'], str(i.get('value')), i.get('unit')) for i in a['items']],
            'key': [(i['label'], i['text']) for i in a['key']], 'count': a['count'], 'headline': a['headline'],
            'unknown': [(u['id'], u['text']) for u in a['unknown']], 'held': [(h['id'], h['status'], h['text']) for h in a['held']],
            'limits': a['limits'], 'notices': a['notices'], 'tables': a['tables'], 'sources': a['sources'], 'edi': a.get('edi'),
            'status': a['status'], 'nodes': [(n['id'], n['status']) for n in a['nodes']]}


class SameNumbersEverywhere(EasyBase):
    CARDS = CARDS

    def run_card(self, card):
        card, _, no = card.partition(':')                         # v0.38 T2-4e 공시 카드는 'filing:접수번호'
        rid = self.c.post('/api/easy/run', json={'card': card, 'company': CO, 'cutoff': CUT, **({'rcept_no': no} if no else {})}).json()['id']
        self.wait(rid)
        return rid

    def run_direct(self, card):
        card, _, no = card.partition(':')
        r = self.c.post('/api/runs', json={'doc': plan(card, CO, CUT, no)})
        self.assertEqual(r.status_code, 201, r.text)
        self.wait(r.json()['id'])
        return r.json()['id']

    def ans(self, rid):
        return self.c.get(f'/api/easy/answer/{rid}').json()

    def test_cards_actually_produce_numbers(self):
        """시험이 빈 답끼리 비교해 통과하는 일을 막는다."""
        for card in self.CARDS:
            a = self.ans(self.run_card(card))
            self.assertTrue(a['items'], card)

    def test_same_input_twice_same_everything(self):
        for card in self.CARDS:
            r1, r2 = self.run_card(card), self.run_card(card)
            self.assertEqual(_norm(self.ans(r1)), _norm(self.ans(r2)), card)
            k1, k2 = (self.c.get(f'/api/easy/receipt/{r}').json() for r in (r1, r2))
            self.assertEqual(k1['receipt_id'], k2['receipt_id'], card)              # 확인 번호까지 같다

    def test_expert_entrance_same_as_easy_card(self):
        for card in self.CARDS:
            e, x = self.run_card(card), self.run_direct(card)
            self.assertEqual(_norm(self.ans(e)), _norm(self.ans(x)), card)
            self.assertEqual(self.c.get(f'/api/easy/receipt/{e}').json()['receipt_id'],
                             self.c.get(f'/api/easy/receipt/{x}').json()['receipt_id'], card)

    def test_answer_matches_expert_results_and_receipt(self):
        for card in self.CARDS:
            rid = self.run_card(card)
            a, run = self.ans(rid), self.c.get(f'/api/runs/{rid}').json()
            rc = self.c.get(f'/api/easy/receipt/{rid}').json()
            dig = {r['node']: r['payload_digest'] for r in rc['results']}
            packets = {}
            for n in run['nodes']:
                if n['output_packet']:
                    pk = self.c.get(f"/api/packets/{n['output_packet']}").json()
                    packets[n['node_id']] = pk
                    if n['node_type'] != 'T05':
                        self.assertEqual(dig[n['node_id']], pk['header']['payload_digest'], (card, n['node_id']))
            for i in a['items']:
                if i['node_type'] in ('N01',):
                    continue                                    # 공식 재무는 원 단위 값을 읽기 쉬운 말로 바꿔 보임(근거 서랍에 원래 값)
                fs = packets[i['node']]['payload'].get('findings') or []
                if not fs:
                    continue
                self.assertIn(i['text'], [plain(f.get('claim')) for f in fs], (card, i['label']))
            items = {(i['label'], i['text']) for i in a['items']}
            self.assertTrue(all((k['label'], k['text']) in items for k in a['key']), card)   # 요약 줄은 전체 줄 안에 있다
            self.assertIn(f"아직 모르는 것 {len(a['unknown'])}건", a['headline'])
            self.assertIn(f"자료로 확인 {a['count']['fact']}건", a['headline'])

    def test_share_page_shows_same_text(self):
        for card in self.CARDS:
            rid = self.run_card(card)
            a = self.ans(rid)
            page = self.c.get(f'/api/share/{rid}').text
            for i in a['key']:
                self.assertIn(html.escape(i['text'], quote=True), page, (card, i['label']))
            for t in a['limits'] + [u['text'] for u in a['unknown']]:
                self.assertIn(html.escape(t, quote=True), page, (card, t[:30]))
            rc = self.c.get(f'/api/easy/receipt/{rid}').json()
            self.assertIn(rc['receipt_id'][:8], page)

    def test_receipt_reverifies_all_cards(self):
        for card in self.CARDS:
            rid = self.run_card(card)
            rc = self.c.get(f'/api/easy/receipt/{rid}').json()
            v = self.c.post('/api/easy/verify', json={'receipt': rc}).json()
            self.assertTrue(v['ok'], (card, v.get('reason')))
            self.assertEqual(v['matched'], v['total'], card)


class SameNumbersFilingCard(SameNumbersEverywhere):
    """v0.38 T2-4e: 공시 숫자 카드도 입구 2개 × 보는 곳 4개에서 숫자·근거·보류가 같고, 같은 입력 두 번이면 확인 번호까지 같다."""
    CARDS = ('filing:20260720800001', 'filing:20260720000002', 'filing:20260806800005', 'filing:20260714800007')   # 소각 · 자기주식 취득 · 배당 · 잠정실적

    def setUp(self):
        super().setUp()
        import os, tempfile
        from tests.test_v038_filing import make_docs
        self.docs = tempfile.TemporaryDirectory(); os.environ['MODU_NODES_DART_DOCS'] = os.path.join(self.docs.name, 'dart_docs')
        make_docs(os.environ['MODU_NODES_DART_DOCS'])

    def tearDown(self):
        import os
        os.environ.pop('MODU_NODES_DART_DOCS', None); self.docs.cleanup()
        super().tearDown()


class FixedLimits(EasyBase):
    def test_price_shows_prediction_hold_without_changing_status(self):
        rid = self.c.post('/api/easy/run', json={'card': 'price', 'company': CO, 'cutoff': CUT}).json()['id']
        self.wait(rid)
        a = self.c.get(f'/api/easy/answer/{rid}').json()
        self.assertIn(PRED_HOLD, a['limits'])
        self.assertFalse(any(PRED_HOLD in u['text'] for u in a['unknown']))
        n09 = next(n for n in a['nodes'] if n['id'] == 'n09')
        self.assertEqual(n09['status'], 'succeeded')                  # 고정 문구가 「일부 완료」로 바꾸지 않음
        self.assertTrue(PRED_HOLD.startswith('예측: 보류'))

    def test_macro_shows_pit_limit_and_share_shows_all_limits(self):
        rid = self.c.post('/api/easy/run', json={'card': 'macro', 'company': CO, 'cutoff': CUT}).json()['id']
        self.wait(rid)
        a = self.c.get(f'/api/easy/answer/{rid}').json()
        if not any(n['id'] == 'n06' and n['status'] in ('succeeded', 'partial') for n in a['nodes']):
            self.skipTest('이 시험 자료에서는 거시 시나리오 단계가 돌지 않음')
        self.assertIn(PIT_HOLD, a['limits'])
        page = self.c.get(f'/api/share/{rid}').text
        for t in a['limits']:
            self.assertIn(html.escape(t, quote=True), page)

    def test_no_banned_words_in_fixed_lines(self):
        for t in (PRED_HOLD, PIT_HOLD):
            for w in ('매수', '매도', '목표주가', '추천'):
                self.assertNotIn(w, t)
            self.assertTrue(re.search('하지 않음|않습니다', t))       # 「하지 않는 것」 상자로 간다


class WaitingIsStillRunning(EasyBase):
    """실행은 'waiting'으로 만들어진 뒤 'running'이 된다. 그 사이에 확인서·공유 페이지를 만들면 빈 결과가 나가던 빈틈을 막았다."""
    def test_waiting_run_is_not_finished(self):
        st = self.c.app.state.store
        owner = self.c.get('/api/easy/cards?company=' + CO).cookies.get('mrn_owner') or self.c.cookies.get('mrn_owner')
        rid = st.create_run(owner, plan('events', CO, CUT), ['t08', 't06', 'n11', 'n12', 't05'])
        self.assertEqual(self.c.get(f'/api/runs/{rid}').json()['status'], 'waiting')
        self.assertEqual(self.c.get(f'/api/easy/receipt/{rid}').status_code, 409)
        self.assertEqual(self.c.get(f'/api/share/{rid}').status_code, 409)
        from tests import test_easy, test_assembler, test_v036_mycards
        for m in (test_easy, test_assembler, test_v036_mycards):     # 시험 도우미도 'waiting'을 기다린다
            self.assertIn("('waiting', 'queued', 'running')", open(m.__file__, encoding='utf-8').read())
        from pathlib import Path
        web = Path(__file__).resolve().parents[1] / 'web'
        for f in ('easy.js', 'mycards.js'):
            js = (web / f).read_text(encoding='utf-8')
            self.assertNotIn("['queued', 'running']", js, f)
