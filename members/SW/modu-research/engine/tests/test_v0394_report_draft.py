"""v0.39.4 근거 고정 보고서 초안: 근거 번호·숫자·판단 표현 검사, 규칙 초안, AI 초안(가짜 모델), API. 네트워크 없음."""
import os, tempfile, unittest
from unittest import mock

from mrn import report_draft as RD

A = {'run_id': 'r1', 'name': '삼성전자', 'card_title': '실적은 어땠나?', 'cutoff': '2026-11-14T16:00:00+09:00',
     'headline': '삼성전자 — 실적은 어땠나? 자료로 확인 14건 · 계산 9건',
     'key': [{'label': '삼성전자 2025년 매출액', 'text': '333조 6,059억 원 (연결)', 'kind_label': '공식 원문 확인 사실', 'source': {'title': 'DART 사업보고서'}},
             {'label': '삼성전자 2025년 영업이익', 'text': '43조 6,011억 원 (연결)', 'kind_label': '공식 원문 확인 사실', 'source': {'title': 'DART 사업보고서'}}],
     'items': [{'label': '삼성전자 2025년 매출액', 'text': '333조 6,059억 원 (연결)'},
               {'label': '영업이익률', 'text': '13.1%', 'kind_label': '계산 파생값', 'formula': '영업이익 ÷ 매출액'}],
     'unknown': [{'text': '분기 값을 만들 수 없어 비워 둔 칸 5개', 'node_name': '사업부별 분기 매출'}],
     'held': [], 'not_this': '매수·매도 추천이나 주가 예측이 아닙니다.', 'notices': [], 'limits': []}


class Evidence(unittest.TestCase):
    def test_numbered_and_deduplicated(self):
        ev = RD.evidence(A)
        self.assertEqual(ev[0]['id'], 1); self.assertEqual(ev[0]['kind'], '정리 문장')
        texts = [e['text'] for e in ev]
        self.assertEqual(sum('2025년 매출액' in t for t in texts), 1)                       # 같은 줄은 한 번
        self.assertTrue(any('계산: 영업이익 ÷ 매출액' in t for t in texts))
        self.assertTrue(any(t.startswith('아직 모르는 것') for t in texts))

    def test_check_drops_bad_sentences(self):
        ev = RD.evidence(A)
        n_rev = next(e['id'] for e in ev if '매출액' in e['text'])
        n_rate = next(e['id'] for e in ev if '영업이익률' in e['text'])
        n_not = next(e['id'] for e in ev if e['kind'] == '이 결과가 아닌 것')
        text = ('## 확인된 사실\n'
                f'- 2025년 매출액은 333조 6,059억 원이었다 [E{n_rev}]\n'
                f'- 영업이익률은 13.1%였다 [E{n_rate}]\n'
                '- 근거 없는 문장\n'
                f'- 매출액은 400조 원이었다 [E{n_rev}]\n'
                f'- 실적이 좋아 매수할 만하다 [E{n_rev}]\n'
                '- 없는 번호 [E99]\n'
                f'- 매수·매도 추천이나 주가 예측이 아닙니다 [E{n_not}]\n'
                f'- 매수 추천이 아닌 이유는 없다 [E{n_rev}]\n')
        keep, drop = RD.check(text, ev)
        body = [k['text'] for k in keep if not k['heading']]
        self.assertEqual(len(body), 3); self.assertTrue(body[2].startswith('매수·매도 추천이나')); self.assertTrue(body[0].startswith('2025년 매출액은 333조')); self.assertTrue(body[1].startswith('영업이익률은 13.1%'))
        self.assertEqual([d['why'].split()[0] for d in drop], ['근거', '근거에', '판단', '없는', '판단'])


class Draft(unittest.TestCase):
    def test_rule_draft_passes_its_own_checks(self):
        r = RD.draft(A, use_model=False)
        self.assertEqual((r['mode'], r['model_calls']), ('rule', 0)); self.assertEqual(r['dropped'], [])
        self.assertIn('[E', r['draft_md']); self.assertIn('333조 6,059억 원', r['draft_md'])

    def test_model_draft_and_fallback(self):
        env = {'MODU_NODES_LLM_URL': 'http://x/v1', 'MODU_NODES_LLM_MODEL': 'claude-sonnet-5-5'}
        ev = RD.evidence(A); n = next(e['id'] for e in ev if '매출액' in e['text'])
        good = f'## 한 줄 정리\n- 2025년 매출액은 333조 6,059억 원으로 확인됐다 [E{n}]\n- 실적이 좋아 매수할 만하다 [E{n}]\n- 매출은 공시 원문에서 왔다 [E{n}]'
        with mock.patch.dict(os.environ, env):
            r = RD.draft(A, True, call=lambda p: good)
            self.assertEqual((r['mode'], r['model_calls'], len(r['dropped'])), ('model', 1, 1)); self.assertIn('뺐어요', r['why'])
            self.assertIn('근거 줄', RD._prompt(A, ev))
            bad = RD.draft(A, True, call=lambda p: '- 매수 추천 [E1]\n- 목표주가 30만 원 [E1]')
            self.assertEqual((bad['mode'], bad['model_calls']), ('rule', 1)); self.assertIn('규칙 초안', bad['why'])
            boom = RD.draft(A, True, call=lambda p: (_ for _ in ()).throw(TimeoutError()))
            self.assertEqual(boom['mode'], 'rule'); self.assertIn('TimeoutError', boom['why'])
        with mock.patch.dict(os.environ, {'MODU_NODES_LLM_URL': '', 'MODU_NODES_LLM_MODEL': ''}):
            self.assertIn('설정되지 않아', RD.draft(A, True)['why'])


class Dates(unittest.TestCase):
    """2026-11-15 PM PC에서 실제로 나온 사례: 가격(11-13)과 수급(11-05)을 「같은 날」로 이음."""
    EV = [{'id': 2, 'text': '기준 종가: 2026-11-13 종가 209,000원 (거래량 12,829,515주)', 'kind': '사실', 'source': ''},
          {'id': 4, 'text': '기준일 주체별 순매수: 2026-11-05 외국인 -5,772,197주 · 기관 +75,714주 · 개인 +6,012,006주', 'kind': '사실', 'source': ''}]

    def test_date_rules(self):
        text = '\n'.join([
            '- 기준 종가는 2026-11-13 종가 209,000원입니다. [E2]',
            '- 같은 날 기관은 +75,714주, 개인은 +6,012,006주입니다. [E4]',
            '- 기관은 +75,714주를 순매수했습니다. [E4]',
            '- 2026-11-13 기관은 +75,714주입니다. [E4]',
            '- 2026-11-05 기준 기관은 +75,714주, 개인은 +6,012,006주입니다. [E4]',
            '- 기준일 주체별 순매수: 2026-11-05 외국인 -5,772,197주 · 기관 +75,714주 · 개인 +6,012,006주 [E4]',
        ])
        keep, drop = RD.check(text, self.EV)
        self.assertEqual(len([k for k in keep if not k['heading']]), 3)
        whys = [d['why'] for d in drop]
        self.assertIn('같은 날', whys[0]); self.assertIn('날짜를 빼고', whys[1]); self.assertIn('없는 날짜', whys[2])


class Api(unittest.TestCase):
    def test_unknown_run_404_and_csrf(self):
        from fastapi.testclient import TestClient
        from mrn.server import create_app
        with tempfile.TemporaryDirectory() as d, TestClient(create_app(data_dir=d)) as c:
            c.get('/api/health')
            tok = c.cookies.get('mrn_csrf')
            self.assertEqual(c.post('/api/report/draft', json={'run_id': 'nope'}).status_code, 403)
            self.assertEqual(c.post('/api/report/draft', json={'run_id': 'nope'}, headers={'X-CSRF-Token': tok}).status_code, 404)


if __name__ == '__main__':
    unittest.main()
