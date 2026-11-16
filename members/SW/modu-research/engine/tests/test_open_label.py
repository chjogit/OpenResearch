"""v0.31 「어떻게 일하나요?」 → 「작동 원리 공개」."""
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / 'web'


class OpenLabel(unittest.TestCase):
    def test_button_and_title(self):
        s = (WEB / 'easy.html').read_text(encoding='utf-8')
        self.assertIn('>앱의 작동원리</button>', s)   # v0.38 이름 바꿈
        self.assertIn('<h2>앱의 작동원리', s)
        self.assertNotIn('>어떻게 일하나요?<', s)
        self.assertIn('id="nAbout"', s)     # 동작(openAbout) 연결은 그대로

    def test_style(self):
        self.assertIn('.open-src', (WEB / 'easy.css').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
