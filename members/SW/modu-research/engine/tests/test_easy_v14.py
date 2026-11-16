"""v0.23 쉬운 화면 1.4: 세 개의 문 · 카드 묶음 · 다음 걸음 · 작동 원리 띠(정직하게: 실행 기록에서만, AI 모델 호출 수 표시)."""
import re
import unittest
from pathlib import Path
from mrn.easy import CARDS, CARD, GROUPS, DOORS
from tests.test_easy import EasyBase, CUT, BANNED

WEB = Path(__file__).resolve().parents[1] / 'web'


class CardMeta(unittest.TestCase):
    def test_every_card_has_group_door_next(self):
        gids, dids = {g['id'] for g in GROUPS}, {d['id'] for d in DOORS}
        for c in CARDS:
            self.assertIn(c['group'], gids, c['id'])
            self.assertIn(c['kind'], ('사실', '관계', '가정'), c['id'])
            self.assertTrue(set(c['doors']) <= dids and c['doors'], c['id'])
            self.assertTrue(c['next'] and all(x in CARD and x != c['id'] for x in c['next']), c['id'])
        self.assertEqual([d['id'] for d in DOORS], ['ask', 'test', 'check'])
        # 가정·전망 카드는 「앞으로에 대한 가정」 묶음에만 (사실과 섞지 않음)
        for cid in ('forecasts', 'edi', 'nowcast', 'macro'):
            self.assertEqual(CARD[cid]['group'], 'ahead')
            self.assertEqual(CARD[cid]['kind'], '가정')


class Strip(EasyBase):
    def test_cards_api_has_groups_and_doors(self):
        r = self.c.get('/api/easy/cards?company=042700').json()
        self.assertEqual(len(r['doors']), 3)
        self.assertTrue(all('group' in c and 'next' in c for c in r['cards']))

    def test_process_strip_is_honest(self):
        rid = self.c.post('/api/easy/run', json={'card': 'earnings', 'company': '042700', 'cutoff': CUT}).json()['id']
        self.wait(rid)
        a = self.c.get(f'/api/easy/answer/{rid}').json()
        P = a['process']
        self.assertEqual([s['id'] for s in P['steps']], ['plan', 'find', 'calc', 'check', 'receipt'])
        self.assertEqual(P['model_calls'], 0)
        self.assertIn('AI 모델 호출 0회', P['ai_note'])
        self.assertIn('미리 정해 둔 순서', P['steps'][0]['text'])
        self.assertNotEqual(P['steps'][0]['tech_name'], '에이전트')        # 카드 경로는 고정 사슬 — 에이전트라고 부풀리지 않음
        self.assertNotIn('RAG', P['steps'][1]['tech_name'])                  # 원문 검색을 안 했으면 RAG라고 하지 않음
        self.assertIn(f"숫자 {len(a['items'])}개", P['steps'][3]['text'])
        self.assertIn('매매·추천 표현은 0건', P['steps'][3]['text'])
        self.assertEqual([x['id'] for x in a['next']], CARD['earnings']['next'])
        for s in P['steps']:
            for w in BANNED:
                self.assertNotIn(w, s['title'] + s['text'] + s['tech_name'])

    def test_rag_named_only_when_doc_search_ran(self):
        rid = self.c.post('/api/easy/run', json={'card': 'holders', 'company': '005930', 'cutoff': CUT}).json()['id']
        self.wait(rid)
        P = self.c.get(f'/api/easy/answer/{rid}').json()['process']
        find = P['steps'][1]
        self.assertIn('RAG', find['tech_name'])
        self.assertIn('BM25', find['tech'])


class Screen(unittest.TestCase):
    def test_new_screen_parts(self):
        html = (WEB / 'easy.html').read_text(encoding='utf-8'); js = (WEB / 'easy.js').read_text(encoding='utf-8')
        for s in ('id="doors"', 'id="path"', 'id="about"', 'id="pPhase"', 'id="hvFile"'):
            self.assertIn(s, html)
        for s in ("UI_VERSION = '쉬운 화면 1.4'", '궁금한 것 묻기', '내 생각 시험하기', '근거 검증하기', '작동 원리', '다음 걸음', '감성분석'):
            self.assertIn(s, js)
        block = js.split('const AB_ATTRS = [', 1)[1].split('];', 1)[0]
        self.assertEqual(re.findall(r"^  \['([^']+)'", block, re.M),
                         ['실시간', '에이전트', '전문', '교육', '맞춤', '반응', '개방', '재귀발전', '예측', '감성분석'])   # 10가지 성질 모두


if __name__ == '__main__':
    unittest.main()


class ModeBar(unittest.TestCase):
    """v0.23.1: 두 화면 맨 위에 같은 모양의 모드 띠 — 쉬운 화면(주황) / 전문가 모드(남색), 지금 화면이 켜져 있음."""
    def test_both_pages_have_mode_bar(self):
        easy = (WEB / 'easy.html').read_text(encoding='utf-8'); exp = (WEB / 'index.html').read_text(encoding='utf-8')
        self.assertIn('class="modebar mb-easy"', easy); self.assertIn('class="modebar mb-expert"', exp)
        self.assertRegex(easy, r'class="mode on" aria-current="page" href="/"')
        self.assertRegex(exp, r'class="mode on" aria-current="page" href="/expert"')
        self.assertIn('id="nExpert"', easy); self.assertIn('id="bEasy"', exp)
        self.assertIn("'/expert#run=' + E.rid", (WEB / 'easy.js').read_text(encoding='utf-8'))       # 보던 답을 들고 넘어감
        self.assertIn("'/#answer=' + S.runId", (WEB / 'app.js').read_text(encoding='utf-8'))


class ModeChoice(unittest.TestCase):
    """v0.23.2: 넘어가기 전에 1차 판단 — 「언제 전문가 모드로?」 안내, 답마다 「전문가 모드에서 더 알 수 있는 것」."""
    def test_tips_on_both_pages(self):
        easy = (WEB / 'easy.html').read_text(encoding='utf-8'); exp = (WEB / 'index.html').read_text(encoding='utf-8')
        self.assertIn('언제 전문가 모드로?', easy); self.assertIn('쉬운 화면에서는 알기 어려운 것', easy); self.assertIn('전문가 모드에서 알 수 있는 것', easy)
        self.assertIn('언제 쉬운 화면으로?', exp); self.assertIn('쉬운 화면에서 바로 되는 것', exp)
        for w in BANNED:
            self.assertNotIn(w, re.sub(r'<[^>]+>', ' ', easy), w)

    def test_every_card_has_expert_hint_naming_real_screens(self):
        exp = (WEB / 'index.html').read_text(encoding='utf-8')
        for c in CARDS:
            self.assertGreaterEqual(len(c['expert']), 2, c['id'])
            for h in c['expert']:
                for name in re.findall(r'「([^」]+)」', h):
                    self.assertIn(f'>{name}<', exp, (c['id'], name))       # 적은 화면 이름이 전문가 모드에 실제로 있음
                for w in BANNED:
                    self.assertNotIn(w, h, (c['id'], w))


class ExpertHintApi(EasyBase):
    def test_answer_carries_expert_hint(self):
        rid = self.c.post('/api/easy/run', json={'card': 'earnings', 'company': '042700', 'cutoff': CUT}).json()['id']
        self.wait(rid)
        a = self.c.get(f'/api/easy/answer/{rid}').json()
        self.assertEqual(a['expert']['hints'], CARD['earnings']['expert'])
        self.assertIsInstance(a['expert']['stuck'], int)


class AssetVersion(EasyBase):
    """v0.23.3: 화면을 바꾸면 브라우저가 예전 디자인(CSS·JS)을 쓰지 않도록 주소에 버전을 붙임."""
    def test_pages_link_versioned_assets(self):
        for path, assets in (('/', ('easy.css', 'easy.js')), ('/expert', ('app.css', 'app.js'))):
            html = self.c.get(path).text
            for a in assets:
                self.assertRegex(html, rf'/static/{re.escape(a)}\?v=\d+', (path, a))
        self.assertIn('쉬운 화면으로', self.c.get('/expert').text)
        self.assertIn('전문가 모드로 →', self.c.get('/').text)


class PlanBox(unittest.TestCase):
    """v0.24.1: 조사 계획 — 기본 분석은 항상 포함(체크 없음), 체크는 「심층 분석 추가」에만."""
    def test_basic_always_and_check_only_for_deep(self):
        html = (WEB / 'index.html').read_text(encoding='utf-8'); js = (WEB / 'app.js').read_text(encoding='utf-8')
        self.assertIn('기본 분석은 체크하지 않아도 항상 들어가요', html)
        body = js.split('function renderPersp(){', 1)[1].split('\nfunction ', 1)[0]
        self.assertIn('기본 분석 <b>항상 포함</b>', body)
        self.assertIn('＋ 심층 분석 추가', body)
        self.assertEqual(body.count('type="checkbox"'), 1)                      # 체크 칸은 심층 줄에만
        self.assertIn('<label class="pext"><input type="checkbox" value="${id}">', body)   # 값(관점 id)은 그대로 → 배치 동작 불변


class RunSummary(EasyBase):
    """v0.24.2: 전문가 모드에서 직접 짠 구성은 「직접 구성」으로(에이전트라고 부르지 않음) · 실행 결과 요약 화면."""
    def test_manual_run_is_not_called_agent(self):
        from mrn.easy import plan
        doc = plan('earnings', '042700', CUT)
        doc['meta'] = {}                                   # 전문가 모드에서 사람이 짠 것과 같은 상태(카드·질문 없음)
        r = self.c.post('/api/runs', json={'doc': doc})
        self.assertEqual(r.status_code, 201, r.text)
        rid = r.json()['id']
        self.wait(rid)
        P = self.c.get(f'/api/easy/answer/{rid}').json()['process']
        self.assertEqual(P['steps'][0]['tech_name'], '직접 구성')
        self.assertIn('직접 고른 구성', P['steps'][0]['text'])
        self.assertEqual(P['planned_by'], 'manual')

    def test_summary_code_present(self):
        js = (WEB / 'app.js').read_text(encoding='utf-8')
        for s in ('실행 결과 요약', '결과 요약 보기', '요약을 글로 복사', "'/api/easy/answer/' + id", '쉬운 화면 답 카드'):
            self.assertIn(s, js)


class FreeAskExamples(unittest.TestCase):
    """v0.24.3: 직접 물어보기 예시 질문 — 예시마다 조립 에이전트가 의도한 목표 하나 이상을 잡고, 회사 이름 속 낱말이 목표로 새지 않음."""
    def test_examples_parse_to_intended_goals(self):
        from mrn.assembler import assemble
        want = {'실적·현금흐름': 'N01', '수급 엇갈림': 'N08', '환율 영향': 'N06', '변동성·국면': 'N10', '공시 뒤 반응': 'N12'}
        js = (WEB / 'easy.js').read_text(encoding='utf-8')
        ex = re.findall(r"\['([^']+)', '\{co\} ([^']+)'\]", js)
        self.assertEqual({t for t, _ in ex}, set(want))
        for t, q in ex:
            r = assemble('삼성전자 ' + q)
            ids = [x['type'] for x in r['targets']]
            self.assertIn(want[t], ids, (t, ids))

    def test_company_name_does_not_leak_into_goals(self):
        from unittest import mock
        from mrn.assembler import parse
        with mock.patch('mrn.assembler._names', return_value={'현대차': '005380', '삼성전자': '005930'}):   # 사본에 관계없이 같은 조건
            P = parse('현대차 2025년 영업이익')
        self.assertNotIn('N07', [g for _, g, _ in P['goals']])          # 「현대차」 안의 「대차」(대차잔고)
