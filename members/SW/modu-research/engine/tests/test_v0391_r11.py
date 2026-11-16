"""v0.39.1 R11: 카드 짧은 이름이 화면 이름표(전태님 REQUESTS 2026-11-13)와 같다. 원래 질문형 제목은 그대로."""
import unittest
from mrn import easy as E

WANT = {'events': '최근 주요 사건', 'price': '주가 흐름·매매 주체', 'earnings': '실적 요약', 'macro': '환율·금리 영향', 'holders': '대주주·지분 변동',
        'relations': '함께 움직인 지표', 'forecasts': '증권사 실적 전망', 'edi': '주가 선반영 햇수', 'nowcast': '이번 분기 매출 조기 추정',
        'attention': '관심도 추이', 'reaction': '공시별 과거 주가 반응'}


class R11(unittest.TestCase):
    def test_short_matches_screen_table(self):
        self.assertEqual(E.SHORT, WANT)

    def test_titles_unchanged(self):
        t = {c['id']: c['title'] for c in E.CARDS}
        self.assertEqual(t['edi'], '주가가 실적보다 몇 년 앞서 있나?')
        self.assertNotIn(t['events'], WANT.values())

    def test_cards_api_short(self):
        from fastapi.testclient import TestClient
        import tempfile
        from mrn.server import create_app
        with tempfile.TemporaryDirectory() as d:
            c = TestClient(create_app(data_dir=d))
            cards = c.get('/api/easy/cards', params={'company': '005930'}).json()
            got = {x['id']: x.get('short') for x in (cards.get('cards') if isinstance(cards, dict) else cards)}
            for k, v in WANT.items():
                if k in got:
                    self.assertEqual(got[k], v, k)


if __name__ == '__main__':
    unittest.main()
