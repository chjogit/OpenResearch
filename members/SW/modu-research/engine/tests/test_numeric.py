"""Checker rules v0.3."""
import unittest
from mrn.official import load_corpus
from mrn.nodes import _fact
from mrn.numeric import analyze

FACTS = {}
for comp in load_corpus()['companies']:
    doc = comp['documents'][0]
    for y in comp['years']:
        for m in y['inputs']:
            f = _fact(comp, doc, y, m)
            FACTS[f['fact_id']] = f


def tiers(text, **kw):
    r = analyze(text, FACTS, **kw)
    return r, {(s['category'], s['tier']) for s in r['spans']}


class Numeric(unittest.TestCase):
    def test_slot_fact_and_calc_verified(self):
        r, t = tiers('매출은 {{fact:005930:2025:revenue}}, 증감 {{calc:pct(005930:2025:revenue,005930:2024:revenue)}}.')
        self.assertIn('333,605,938백만원', r['display'])
        self.assertIn('+10.88%', r['display'])
        self.assertIn(('slot:fact', 'verified'), t)
        self.assertIn(('slot:calc', 'computed'), t)

    def test_unknown_slot_is_flagged(self):
        r, t = tiers('{{fact:999999:2025:revenue}}')
        self.assertIn(('slot:fact', 'mismatch'), t)

    def test_free_number_red_and_cross_check(self):
        _, t = tiers('삼성전자 2025년 매출은 310조원입니다.')
        self.assertIn(('number', 'mismatch'), t)
        r, t = tiers('삼성전자 2025년 매출은 333.6조원입니다.')
        self.assertIn(('number', 'red'), t)
        self.assertIn('근사 일치', [s for s in r['spans'] if s['category'] == 'number'][0]['detail'])
        _, t = tiers('매출이 약 300조 원대입니다.')
        self.assertIn(('number', 'red'), t)

    def test_korean_numeral(self):
        _, t = tiers('삼백조원이 넘는 매출')
        self.assertIn(('kor_number', 'red'), t)
        _, t = tiers('일부 사업과 이만 줄입니다')
        self.assertNotIn(('kor_number', 'red'), t)

    def test_degree_vs_calc(self):
        _, t = tiers('전년 대비 {{calc:pct(005930:2025:revenue,005930:2024:revenue)}} 소폭 증가했습니다.')
        self.assertIn(('degree', 'mismatch'), t)
        _, t = tiers('영업이익은 {{calc:pct(000660:2025:operatingProfit,000660:2024:operatingProfit)}} 급증했습니다.')
        self.assertIn(('degree', 'match'), t)
        _, t = tiers('영업이익이 크게 늘었습니다.')
        self.assertIn(('degree', 'model'), t)

    def test_trade_words_hidden_valuation_flagged(self):
        r, t = tiers('저평가 구간이므로 매수 의견을 유지합니다.')
        self.assertIn(('trade', 'hidden'), t)
        self.assertIn(('valuation', 'model'), t)
        self.assertNotIn('매수 의견', r['display'])
        _, t = tiers('외국인 5일 연속 순매수')
        self.assertIn(('flow', 'model'), t)
        self.assertNotIn(('trade', 'hidden'), t)  # 순매수 is not a trade instruction

    def test_proper_nouns_and_periods_not_red(self):
        _, t = tiers('2025년 HBM3E와 3나노, 제57기 (주30)')
        self.assertFalse(any(x[1] == 'red' for x in t))

    def test_external_slot_without_data(self):
        _, t = tiers('목표주가 {{ext:abc}}, 컨센서스 상회')
        self.assertIn(('slot:ext', 'mismatch'), t)
        self.assertIn(('consensus', 'model'), t)

    def test_conservative_mode_drops_sentences(self):
        r = analyze('매출은 {{fact:005930:2025:revenue}}입니다. 매출이 약 300조원입니다.', FACTS, mode='conservative')
        self.assertIn('333,605,938', r['display'])
        self.assertNotIn('300조', r['display'])
        self.assertEqual(len(r['held']), 1)
        r = analyze('매출이 약 300조원입니다.', FACTS)
        self.assertIn('300조', r['display'])  # research mode never blocks

    def test_outlook_words(self):
        r, t = tiers('2025년 삼성전자 실적 모멘텀')
        self.assertIn(('outlook', 'model'), t)
        for w in ['업황 회복', '업사이클', 'HBM 수혜', '이익 체력', '펀더멘털 개선', '불확실성 확대', '투자 심리 위축', '실적 눈높이']:
            _, t = tiers(f'{w}이 이어진다')
            self.assertIn(('outlook', 'model'), t, w)

    def test_cmp(self):
        r, t = tiers('{{cmp:005930:2025:revenue,000660:2025:revenue}}')
        self.assertIn('큽니다', r['display'])
        self.assertIn(('slot:cmp', 'computed'), t)


if __name__ == '__main__':
    unittest.main()
