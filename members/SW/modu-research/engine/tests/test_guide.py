"""v0.26 AI 길잡이: 기본 꺼짐 · 숫자·판단을 만들지 않음 · 고른 카드/바꾼 질문은 앱 규칙으로 다시 확인 · 호출 수 정직하게 표시."""
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from mrn import guide as G

ANSWER = {'v': {}}


class Fake(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']))
        body = json.dumps({'choices': [{'message': {'content': json.dumps(ANSWER['v'], ensure_ascii=False)}}]}).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


class Guide(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(('127.0.0.1', 0), Fake)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def setUp(self):
        os.environ['MODU_NODES_LLM_URL'] = f'http://127.0.0.1:{self.srv.server_port}/v1'
        os.environ['MODU_NODES_LLM_MODEL'] = 'fake-model'

    def tearDown(self):
        os.environ.pop('MODU_NODES_LLM_URL', None); os.environ.pop('MODU_NODES_LLM_MODEL', None)

    def test_off_by_default_uses_rules_only(self):
        r = G.translate('삼성전자 돈 잘 벌어?', '삼성전자', None, use_model=False)
        self.assertEqual((r['mode'], r['model_calls']), ('rule', 0))
        self.assertTrue(r['suggestions'])

    def test_good_answer_passes_and_is_rechecked(self):
        ANSWER['v'] = {'card': 'earnings', 'rewrite': '영업이익과 현금흐름', 'why': '돈을 잘 버는지는 영업이익과 현금흐름으로 볼 수 있어요.'}
        r = G.translate('삼성전자 돈 잘 벌어?', '삼성전자', None, use_model=True)
        self.assertEqual(r['mode'], 'model'); self.assertEqual(r['model_calls'], 1)
        self.assertEqual(r['card']['id'], 'earnings')
        self.assertEqual(r['rewrite'], '삼성전자 영업이익과 현금흐름')          # 회사 이름을 붙이고, 규칙 엔진이 알아듣는지 다시 확인
        self.assertTrue(r['ai_written'] and r['prompt_sha'])

    def test_numbers_and_judgement_are_dropped(self):
        ANSWER['v'] = {'card': 'no_such_card', 'rewrite': '영업이익이 30조 넘으면 매수', 'why': '목표주가는 10만원이에요.'}
        r = G.translate('삼성전자 돈 잘 벌어?', '삼성전자', None, use_model=True)
        self.assertIsNone(r['card']); self.assertIsNone(r['rewrite'])
        self.assertEqual(r['mode'], 'rule')                                     # 통과한 것이 없으면 규칙 결과만
        self.assertNotIn('10만', r['why'])
        self.assertTrue(any('목록에 없는 카드' in c for c in r['checks']))

    def test_year_from_question_allowed(self):
        ANSWER['v'] = {'card': None, 'rewrite': '2025년 영업이익', 'why': '연도를 살렸어요.'}
        r = G.translate('삼성전자 2025년에 돈 많이 벌었어?', '삼성전자', None, use_model=True)
        self.assertEqual(r['rewrite'], '삼성전자 2025년 영업이익')

    def test_trade_question_refused_without_model(self):
        ANSWER['v'] = {'card': 'earnings', 'rewrite': '영업이익', 'why': 'x'}
        r = G.translate('삼성전자 지금 사도 돼?', '삼성전자', None, use_model=True)
        self.assertTrue(r['refused']); self.assertEqual(r['model_calls'], 0)
        self.assertTrue(r['suggestions'])

    def test_model_failure_falls_back(self):
        os.environ['MODU_NODES_LLM_URL'] = 'http://127.0.0.1:9/v1'
        r = G.translate('삼성전자 돈 잘 벌어?', '삼성전자', None, use_model=True)
        self.assertEqual(r['mode'], 'rule'); self.assertIn('모델 호출 실패', r['checks'])

    def test_audit_has_no_question_text(self):
        r = G.translate('삼성전자 비밀 질문', '', None, use_model=False)
        d = G.audit_detail('삼성전자 비밀 질문', r)
        self.assertNotIn('비밀', json.dumps(d, ensure_ascii=False))


class GuideApi(unittest.TestCase):
    def test_status_and_translate_endpoints(self):
        import tempfile
        from fastapi.testclient import TestClient
        from mrn.server import create_app
        with tempfile.TemporaryDirectory() as d:
            with TestClient(create_app(data_dir=d)) as c:
                c.get('/api/health'); c.headers['X-CSRF-Token'] = c.cookies.get('mrn_csrf')
                s = c.get('/api/guide/status').json()
                self.assertIn('available', s); self.assertNotIn('key', json.dumps(s).lower().replace('how', ''))
                r = c.post('/api/guide/translate', json={'question': '지금 사도 돼?'}).json()
                self.assertTrue(r['refused'])
                self.assertEqual(c.post('/api/guide/translate', json={'question': ''}).status_code, 422)


class RunMeta(unittest.TestCase):
    def test_process_counts_guide_calls(self):
        from mrn.easy import process
        run = {'doc': {'meta': {'ui': 'easy', 'guide': {'model': 'm', 'calls': 1}}, 'cutoff': '2026-11-09'}, 'nodes': []}
        P = process(run, lambda pid: {}, [], [], [], [])
        self.assertEqual(P['model_calls'], 1)
        self.assertIn('질문을 앱의 말로 바꾸는 데만', P['ai_note'])
        run['doc']['meta'] = {'ui': 'easy'}
        self.assertEqual(process(run, lambda pid: {}, [], [], [], [])['model_calls'], 0)


if __name__ == '__main__':
    unittest.main()


class PromptV2(unittest.TestCase):
    """v0.33: 낱말→카드 길잡이표, 수급 용어(순매수 등)는 판단 표현이 아님."""
    def test_prompt_v2(self):
        from mrn import guide as G
        p = G._prompt('빚이 많아?', '삼성전자', G._cards())
        self.assertEqual(G.PROMPT_VERSION, 'guide-t1-v2')
        self.assertIn('카드 고르는 길잡이', p)
        ids = {c['id'] for c in G._cards()}
        for line in G.HINTS.splitlines():                      # 길잡이표의 카드는 모두 등록부에 있거나 null
            self.assertIn(line.rsplit('→ ', 1)[1], ids | {'null'})

    def test_flow_words_not_judgement(self):
        from mrn import guide as G
        self.assertEqual(G._clean_text('삼성전자 외국인 순매수 추세는?', 'q', 80)[1], '')
        self.assertEqual(G._clean_text('삼성전자 기관 매수세와 매도세 흐름', 'q', 80)[1], '')
        self.assertEqual(G._clean_text('삼성전자 지금 매수할 때인가', 'q', 80)[1], '판단 표현')
        self.assertEqual(G._clean_text('삼성전자 순매수 늘면 사야 하나', 'q', 80)[1], '판단 표현')
