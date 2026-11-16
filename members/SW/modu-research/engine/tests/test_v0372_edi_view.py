"""v0.37.2: 「주가가 실적보다 몇 년 앞서 있나?」 답의 그림 — 답 묶음에 edi 기록이 더해지고(더하기만), 화면에 그림 코드가 있다."""
import re, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


class EdiView(unittest.TestCase):
    def test_answer_carries_series_and_screen_draws_it(self):
        py = (ROOT / 'mrn' / 'easy.py').read_text(encoding='utf-8'); js = (ROOT / 'web' / 'easy.js').read_text(encoding='utf-8'); css = (ROOT / 'web' / 'easy.css').read_text(encoding='utf-8')
        self.assertIn("'edi': edi_view,", py); self.assertIn("if t == 'N17' and p.get('series'):", py)
        for s in ('function ediHtml(v){', 'function bindEdi(a){', "${a.edi ? ediHtml(a.edi) : ''}", 'if (a.edi) bindEdi(a);'):
            self.assertIn(s, js)
        self.assertIn('.edi .eleg{', css)
        block = js.split('function ediHtml(v){', 1)[1]
        for bad in ('저평가', '고평가', '싸다', '비싸다', '매수', '매도', '목표주가'):          # 그림은 계산값을 그릴 뿐 판단하지 않는다
            self.assertNotIn(bad, block)
        self.assertIn('주가가 얼마여야 한다는 뜻이 아니고', block)
        self.assertEqual(len(re.findall(r'viewBox="0 0 680 270"', block)), 1)                       # 축은 하나(원) — 두 축 그림을 만들지 않는다


if __name__ == '__main__':
    unittest.main()
