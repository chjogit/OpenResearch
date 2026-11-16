"""v0.37.4: 답 카드 그림 2종(사업부 매출 · 약속 대비 실제) — 화면만 바뀌고, 표 값을 그대로 그리며, 판단 표현과 좋고 나쁨의 색이 없다."""
import re, unittest
from pathlib import Path
WEB = Path(__file__).resolve().parents[1] / 'web'


class CardCharts(unittest.TestCase):
    def test_screen_draws_from_tables_without_judgement(self):
        js = (WEB / 'easy.js').read_text(encoding='utf-8'); css = (WEB / 'easy.css').read_text(encoding='utf-8')
        for s in ('function segHtml(a){', 'function promHtml(a){', '${visHtml(a)}', 'bindVis();', "/별 분기 매출 \\(억원/", "t.title.startsWith('자기주식 취득 결정과 결과')"):
            self.assertIn(s, js)
        block = js.split('표를 그림으로 (v0.37.4)', 1)[1]
        self.assertIsNone(re.search(r'매수|매도|목표\s*주가|호조|부진|우수|양호|약속을 지켰|주주친화', block))
        self.assertIn('회사에 대한 평가가 아니에요', block); self.assertIn('좋은지 나쁜지는 판단하지 않아요', block)
        vis = css.split('v0.37.4 표를 그림으로', 1)[1]
        self.assertEqual(set(re.findall(r'(?:background|stroke|fill):(#[0-9a-f]{6})', vis)) & {'#d32f2f', '#2e7d32', '#ff0000', '#00aa00'}, set())   # 빨강·초록으로 좋고 나쁨을 칠하지 않는다


if __name__ == '__main__':
    unittest.main()
