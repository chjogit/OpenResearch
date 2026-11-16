"""v0.37.6: 수집 확인 규칙(그림 PDF · 띄어쓰기)과 「증권사 전망」 카드가 흐린 이유 문구."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '_tools' / 'broker_fetch'))
from mrn.easy import CARD, card_status


class Gaps(unittest.TestCase):
    def test_mentions(self):
        try:
            import bulk_fetch as B
        except ImportError:                      # 실행 묶음에는 수집 도구(_tools/broker_fetch)가 없다
            self.skipTest('_tools/broker_fetch 없음')
        self.assertTrue(B.mentions(None, '066570', 'LG전자'))
        self.assertTrue(B.mentions('', '066570', 'LG전자'))
        self.assertTrue(B.mentions('▪ ▪ ▪', '047050', '포스코인터내셔널'))          # 글자가 거의 없는 그림 PDF
        self.assertTrue(B.mentions('LG 전자 3Q26 잠정실적 디바이스 수요와 AI 신사업 전망을 정리', '066570', 'LG전자'))   # 띄어쓰기
        self.assertFalse(B.mentions('세아베스틸 지주 (001430) 2027년을 바라보며 목표주가 하향 현재주가', '003030', '세아제강지주'))   # 다른 회사 보고서는 계속 거른다

    def test_card_reason(self):
        c = CARD['forecasts']
        self.assertEqual(card_status(c, '005930', None, {'005930'}, {'005930'}), (True, ''))
        ok, why = card_status(c, '042700', None, {'005930'}, {'005930'})
        self.assertFalse(ok); self.assertIn('올라오지 않아', why)
        ok, why = card_status(c, '055550', None, {'005930'}, {'005930', '055550'})
        self.assertFalse(ok); self.assertIn('받아 두었지만', why)
        ok, why = card_status(c, '042700', None, {'005930'})                          # 옛 호출 방식도 그대로 동작
        self.assertFalse(ok)


if __name__ == '__main__':
    unittest.main()
