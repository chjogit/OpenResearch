"""v0.27 이름 꼬리표 — 모두의리서치(우산) · 기업분석(첫 상품)."""
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / 'web'


class BrandDescriptor(unittest.TestCase):
    def read(self, n):
        return (WEB / n).read_text(encoding='utf-8')

    def test_easy_header_title_about(self):
        s = self.read('easy.html')
        self.assertIn('<title>모두의리서치 · 기업분석', s)
        self.assertIn('모두의리서치<span class="mb-desc">기업분석</span>', s)
        self.assertEqual(s.count('class="prodline"'), 2)   # 첫 화면 + 작동 원리 공개
        self.assertIn('첫 번째 분석', s)

    def test_expert_header_title(self):
        s = self.read('index.html')
        self.assertIn('<title>모두의리서치 · 기업분석', s)
        self.assertIn('<span class="mb-desc">기업분석</span>', s)
        self.assertIn("' · 모두의리서치 · 기업분석'", self.read('app.js'))

    def test_styles_both_modes(self):
        self.assertIn('.mb-easy .mb-desc', self.read('easy.css'))
        self.assertIn('.mb-expert .mb-desc', self.read('app.css'))

    def test_no_judgement_words_in_tagline(self):
        s = self.read('easy.html')
        for w in ('추천', '매수', '매도', '목표주가', '수익 보장'):
            self.assertNotIn(w, s[s.index('class="prodline"'):s.index('class="prodline"') + 200])


if __name__ == '__main__':
    unittest.main()
