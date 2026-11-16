"""v0.38 T2-3 유상증자 결정: 원문 읽기(주주배정·제3자배정) · 기본 계산 · 예정→확정 · 산식 재계산 · 시나리오 표 · 시장 대비 확률 · 실제 원문 전부."""
import json, math, unittest
from datetime import date, timedelta
from pathlib import Path
from mrn import dartdocs as D, filing as FL, filing2 as F2, filing3 as F3, prob as PB, tradecal as C
from tests.test_v038_filing import html
from tests.test_v038_prob import fake

REAL_DOCS = Path(__file__).resolve().parents[2] / '_sources' / 'dart_docs'
TEXT = ['24. 기타 투자판단에 참고할 사항', '가. 신주 발행가액 산정방법',
        '① 예정발행가액 : 이사회결의일 전일(2026년 02월 09일)을 기산일로 하여 1개월 가중산술평균주가, 1주일 가중산술평균주가 및 기산일 종가를 산술평균하여 산정한 가액과 기산일 종가 중 낮은 금액을 기준주가로 하여 할인율 20%를 적용',
        '* 예정발행가액 = [기준주가 × (1-할인율)] / [1+(증자비율 × 할인율)]',
        '② 1차 발행가액 : 신주배정기준일(2026년 03월 18일) 전 제3거래일({d1})을 기산일로 하여 1개월 가중산술평균주가, 1주일 가중산술평균주가 및 기산일 종가를 산술평균하여 산정한 가액과 기산일 종가 중 낮은 금액을 1차 기준주가로 하며 할인율 20%를 적용',
        '* 1차 발행가액 = [1차 기준주가 × (1-할인율)] / [1 + (증자비율 × 할인율)]',
        '③ 2차 발행가액 : 구주주 청약일(2026년 04월 20일) 전 제3거래일({d2})을 기산일로 하여 1주일 가중산술평균주가 및 기산일 종가를 산술평균하여 산정한 가액과 기산일 종가 중 낮은 금액을 2차 기준주가로 하여 할인율은 20%를 적용',
        '④ 확정 발행가액 : 확정 발행가액은 1차 발행가액과 2차 발행가액 중 낮은 가액으로 합니다. 다만 청약일 전 과거 제3거래일부터 제5거래일까지의 가중산술평균주가에 40% 할인율을 적용하여 산정한 가격보다 낮은 경우 그 가격을 확정발행가액으로 합니다.',
        '* 확정 발행가액 = Max{Min[1차 발행가액, 2차 발행가액], 기준주가의 60%}', '나. 신주의 배정방법', '① 우리사주조합: 20%']


def ri(new='10,000,000', pre='50,000,000', plan='8,500', final='-', record='2026년 03월 18일', sub=('2026년 04월 20일', '2026년 04월 21일'), funds=('60,000,000,000', '25,000,000,000'),
       method='주주배정후 실권주 일반공모', corr=None, d1='2026년 03월 13일', d2='2026년 04월 15일', text=True, split=False):
    r = []
    if corr:
        r += [['정정신고(보고)'], ['1. 정정대상 공시서류 :', '주요사항보고서(유상증자결정)'], ['2. 정정대상 공시서류의 최초제출일 :', corr[0]], ['3. 정정사항'],
              ['항목', '정정사유', '정정전', '정정후'], ['6. 신주 발행가액', corr[1], '-', '-']]
    r += [['유상증자 결정'], ['1. 신주의 종류와 수', '보통주식 (주)', new, '기타주식 (주)', '-'], ['2. 1주당 액면가액 (원)', '500'],
          ['3. 증자전 발행주식총수 (주)', '보통주식 (주)', pre, '기타주식 (주)', '-'],
          ['4. 자금조달의 목적', '시설자금 (원)', funds[0]], ['영업양수자금 (원)', '-'], ['운영자금 (원)', funds[1]], ['채무상환자금 (원)', '-'], ['타법인 증권취득자금 (원)', '-'], ['기타자금 (원)', '-'],
          ['5. 증자방식', method], ['6. 신주 발행가액', '확정발행가', '보통주식 (원)', final, '기타주식 (원)', '-'], ['예정발행가', '보통주식 (원)', plan, '확정예정일', '2026년 04월 15일'], ['기타주식 (원)', '-', '확정예정일', '-'],
          ['7. 발행가 산정방법', '24. 기타 투자판단에 참고할 사항 가. 참조'], ['8. 신주배정기준일', record], ['9. 1주당 신주배정주식수 (주)', '0.16'], ['10. 우리사주조합원 우선배정비율 (%)', '20'],
          ['11. 청약예정일', '우리사주조합', '시작일', sub[0], '종료일', sub[0]], ['구주주', '시작일', sub[0], '종료일', sub[1]], ['12. 납입일', '2026년 04월 28일'],
          ['13. 실권주 처리계획', '참조'], ['16. 신주의 상장예정일', '2026년 05월 12일'], ['18. 신주인수권양도여부', '예'], ['19. 이사회결의일(결정일)', '2026년 02월 10일']]
    if text:
        for t in TEXT:
            t = t.replace('{d1}', d1).replace('{d2}', d2)
            if split and '{' not in t and '제3거래일(' in t:                         # 날짜가 다른 칸으로 끊긴 서식(색을 입힌 정정 표시)
                a, b = t.split('제3거래일(', 1); c, e = b.split(')', 1); r += [[a + '제3거래일('], [c], [')' + e]]
            else:
                r.append([t])
    return html(r)


def third(price='75,974', base='67,908', prem='11.876'):
    return html([['유상증자 결정'], ['1. 신주의 종류와 수', '보통주식 (주)', '-', '기타주식 (주)', '1,000,000'], ['2. 1주당 액면가액 (원)', '500'],
                 ['3. 증자전 발행주식총수 (주)', '보통주식 (주)', '60,000,000', '기타주식 (주)', '-'], ['4. 자금조달의 목적', '시설자금 (원)', '75,974,000,000'], ['운영자금 (원)', '-'],
                 ['5. 증자방식', '제3자배정증자'], ['6. 신주 발행가액', '보통주식 (원)', '-', '기타주식 (원)', price], ['7. 기준주가', '보통주식 (원)', '-', '기타주식 (원)', base],
                 ['7-1. 기준주가 산정방법', '최소값[1개월·1주일·최근일 가중산술평균주가의 단순평균, 최근일 가중산술평균주가]'], ['7-2. 기준주가에 대한 할인율 또는 할증율 (%)', prem],
                 ['9. 납입일', '2025년 04월 07일'], ['15. 이사회결의일(결정일)', '2025년 03월 26일']])


def run(doc, mkt=None, history=(), newer=(), prices=None, rcept='2026-02-10', ticker='000010'):
    f = {'kind': 'rights_issue', 'parsed': F3.parse_rights_issue(doc), 'report_nm': '주요사항보고서(유상증자결정)', 'rcept_dt': rcept, 'url': '', 'rcept_no': '20260210000001',
         'history': list(history), 'newer': list(newer)}
    F, held, T, notes = FL.compute(json.loads(json.dumps(f)), mkt, prices=prices, ticker=ticker)
    return {x['name']: x for x in F}, held, notes, T


def days(start='2026-01-02', n=120):
    d = date.fromisoformat(start); out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def px(levels, upto=None):
    """levels = [(이 날짜부터, 종가)…] → 평일마다 한 줄(거래량 1,000주, 거래대금 = 종가 × 1,000)."""
    out = []
    for d in days():
        if upto and d > upto:
            break
        c = [v for s, v in levels if s <= d][-1]
        out.append({'trade_date': d, 'close': c, 'volume': 1000, 'trade_value': c * 1000, 'market_cap': c * 50_000_000})
    return out


MK = {'date': '2026-02-09', 'close': 10000.0, 'market_cap': 10000.0 * 50_000_000, 'shares': 50_000_000}


class Rights(unittest.TestCase):
    def test_parse_holders_form_and_pricing_terms(self):
        p = F3.parse_rights_issue(ri())
        self.assertEqual((p['new'], p['pre'], p['plan'], p['final'], p['mode']), (10_000_000, 50_000_000, 8500, None, 'holders'))
        self.assertEqual((p['record_date'], p['sub'], p['alloc'], p['esop'], p['fix_date']), ('2026-03-18', ['2026-04-20', '2026-04-21'], 0.16, 20.0, '2026-04-15'))
        self.assertEqual(p['funds']['facility'], 60_000_000_000); self.assertEqual(p['funds']['operating'], 25_000_000_000)
        q = p['pricing']
        self.assertEqual((q['standard'], q['disc1'], q['disc2'], q['floor'], q['day1'], q['day2']), (True, 20.0, 20.0, 0.6, '2026-03-13', '2026-04-15'))
        self.assertEqual(F3.parse_rights_issue(ri(split=True))['pricing'], q)                       # 날짜가 다른 칸으로 끊겨도 같은 값
        self.assertFalse(F3.parse_rights_issue(ri(text=False))['pricing']['standard'])

    def test_basic_numbers_by_hand(self):
        F, held, notes, T = run(ri(), MK)
        self.assertEqual(F['증자비율']['value'], 20.0); self.assertEqual(F['증자 후 발행주식 총수']['value'], 60_000_000)
        self.assertEqual(F['새 주식을 받지 않는 주주의 지분율이 줄어드는 정도']['value'], 16.6667)
        self.assertEqual(F['조달 금액(예정 발행가 기준)']['value'], 85_000_000_000); self.assertEqual(F['자금 목적 합계와 조달 금액의 대조']['claim'], '같음')
        self.assertEqual(F['조달 금액 ÷ 시가총액']['value'], 17.0); self.assertEqual(F['예정 발행가 ÷ 종가']['value'], -15.0)
        self.assertEqual(F['이론 권리락 주가(예정 발행가 기준)']['value'], 9750.0); self.assertIn('종가 대비 -2.50%', F['이론 권리락 주가(예정 발행가 기준)']['claim'])
        self.assertEqual(F['100주를 가진 주주에게 배정되는 주식 수']['value'], 16); self.assertIn('모두 청약하면 136,000원(예정 발행가)', F['100주를 가진 주주에게 배정되는 주식 수']['claim'])
        self.assertTrue(any('예정 발행가로 계산했습니다(확정 예정일 2026-04-15)' in x for x in notes))
        F, held, notes, T = run(ri(funds=('60,000,000,000', '24,000,000,000')), MK)
        self.assertIn('합계가 조달 금액보다 1,000,000,000원 적음(-1.18%) — 발행 비용', F['자금 목적 합계와 조달 금액의 대조']['claim'])
        F, held, notes, T = run(ri(funds=('60,000,000,000', '30,000,000,000')), MK)
        self.assertIn('합계가 +5,000,000,000원 다름(+5.88%) — 원문 표를 직접 확인', F['자금 목적 합계와 조달 금액의 대조']['claim'])

    def test_third_party_premium_sign(self):                                                        # J13
        F, held, notes, T = run(third(), MK)
        self.assertNotIn('이론 권리락 주가(확정 발행가 기준)', F)
        self.assertIn('할증 11.88% · 공시 값 11.876%와 크기가 같음', F['기준주가 대비 발행가']['claim'])
        F, held, notes, T = run(third(price='61,000', base='67,908', prem='10.17'), MK)
        self.assertIn('할인 10.17%', F['기준주가 대비 발행가']['claim']); self.assertIn('크기가 같음', F['기준주가 대비 발행가']['claim'])
        F, held, notes, T = run(third(price='61,000', base='67,908', prem='5'), MK)
        self.assertIn('다름 — 원문을 직접 확인', F['기준주가 대비 발행가']['claim'])
        self.assertTrue(any('권리락도 없습니다' in x for x in notes))

    def test_plan_to_final_and_diff(self):                                                          # 결정 2·5
        old = {'rcept_no': '20260210000001', 'rcept_dt': '2026-02-10', 'url': '', 'report_nm': 'x', 'parsed': F3.parse_rights_issue(ri())}
        F, held, notes, T = run(ri(plan='-', final='7,700', corr=('2026.02.10', '발행가액 확정')), MK, history=[old], rcept='2026-04-16')
        self.assertEqual(F['신주 발행가액(확정)']['value'], 7700); self.assertEqual(F['조달 금액(확정 발행가 기준)']['value'], 77_000_000_000)
        self.assertIn('8,500원 → 7,700원 (-9.41%)', F['예정 발행가 대비 확정 발행가']['claim'])
        d = next(v for k, v in F.items() if k.startswith('앞선 공시(2026-02-10'))
        self.assertIn('확정 발행가(보통주) — → 7,700원', d['claim']); self.assertIn('예정 발행가(보통주) 8,500원 → —', d['claim'])
        self.assertTrue(any('정정사유(원문 그대로): 「발행가액 확정」' in x for x in notes))
        self.assertFalse(any(k.startswith('확정 발행가 추정') for k in F))
        newer = [{'rcept_no': '20260416000009', 'rcept_dt': '2026-04-16', 'url': '', 'report_nm': 'x'}]
        F, held, notes, T = run(ri(), MK, newer=newer)
        self.assertTrue(any('최신본(접수번호 20260416000009)' in h for h in held)); self.assertNotIn('증자비율', F)

    def test_tick_and_base_prices(self):
        self.assertEqual([F3.tick_up(x) for x in (1999.2, 2001, 19991, 49960, 146101, 499900, 1173001)], [2000, 2005, 20000, 50000, 146200, 500000, 1174000])
        R = F3._rows(px([('2026-01-01', 10000), ('2026-03-10', 9000)]))
        w = 9000.0; m = F3._vwap(R, '2026-02-14', '2026-03-13')                                      # 1개월: 2/14~3/13
        self.assertAlmostEqual(F3.base_first(R, '2026-03-13'), min((m + w + 9000) / 3, 9000)); self.assertEqual(F3.base_second(R, '2026-03-13'), 9000)
        self.assertEqual(F3._trading_before(R, '2026-03-18', 3), '2026-03-13'); self.assertEqual(F3._trading_before(R[:10], '2026-03-18', 3), '2026-03-13')
        self.assertIsNone(F3.base_first(R, '2026-03-14'))                                            # 토요일(시세 없음)

    def test_first_and_final_recomputed_from_prices(self):                                           # 주가 10,000원 그대로: 1차 7,700 · 2차 8,000 · 하한 6,000
        F, held, notes, T = run(ri(), MK, prices=px([('2026-01-01', 10000)], upto='2026-03-16'))
        self.assertIn('7,700원', F['1차 발행가(시세로 계산 — 회사 공시 전)']['claim'])
        F, held, notes, T = run(ri(plan='7,700'), MK, prices=px([('2026-01-01', 10000)], upto='2026-03-17'), rcept='2026-03-16')
        self.assertIn('7,700원 · 공시 값과 같음', F['1차 발행가를 시세로 다시 계산']['claim'])
        for after, want in ((12000, '7,700원 — 1차 7,700원 · 2차 9,600원 · 하한 7,200원'), (6000, '4,800원 — 1차 7,700원 · 2차 4,800원 · 하한 3,600원'), (14000, '8,400원 — 1차 7,700원 · 2차 11,200원 · 하한 8,400원')):
            F, held, notes, T = run(ri(plan='7,700'), MK, prices=px([('2026-01-01', 10000), ('2026-03-16', after)], upto='2026-04-15'), rcept='2026-03-16')
            self.assertIn(want, F['확정 발행가(시세로 계산 — 회사의 확정 공시 전)']['claim'], after)
            self.assertFalse(T)

    def test_scenario_table_by_hand(self):
        F, held, notes, T = run(ri(), MK, prices=px([('2026-01-01', 10000)], upto='2026-02-10'))
        t = next(x for x in T if x['title'].startswith('확정 발행가 시나리오'))
        self.assertEqual(t['rows'][3], ['지금 수준', '10,000원', '7,700원', '8,000원', '6,000원', '7,700원', '-9.4%'])
        self.assertEqual(t['rows'][0], ['-30%', '7,000원', '5,390원', '5,600원', '4,200원', '5,390원', '-36.6%'])
        self.assertIn('어느 수준이 될지는 말하지 않습니다', t['hint'])
        F, held, notes, T = run(ri(plan='7,700'), MK, prices=px([('2026-01-01', 10000)], upto='2026-03-17'), rcept='2026-03-16')       # 1차가 정해진 뒤
        t = next(x for x in T if x['title'].startswith('확정 발행가 시나리오'))
        self.assertEqual(t['rows'][6], ['+30%', '13,000원', '7,700원', '10,400원', '7,800원', '7,800원', '+1.3%']); self.assertIn('1차 발행가(정해짐)', t['cols'])

    def test_nonstandard_text_and_missing_prices_are_held(self):
        F, held, notes, T = run(ri(text=False), MK, prices=px([('2026-01-01', 10000)], upto='2026-02-10'))
        self.assertTrue(any('표준 꼴' in h for h in held)); self.assertFalse(T)
        F, held, notes, T = run(ri(), MK)
        self.assertTrue(any('가격 자료(또는 보통주 수)가 없어' in h for h in held))

    def test_calendar_base_day(self):                                                               # J22(J14 수정): 휴장일 표가 있는 해는 달력으로 센 기산일을 믿는다
        from unittest import mock
        from mrn import tradecal as C
        doc = ri(d1='', d2='').replace('전 제3거래일()을', '전 제3거래일을')
        self.assertIsNone(F3.parse_rights_issue(doc)['pricing']['day1'])
        F, held, notes, T = run(doc, MK, prices=px([('2026-01-01', 10000)], upto='2026-03-16'))
        self.assertIn('7,700원', F['1차 발행가(시세로 계산 — 회사 공시 전)']['claim'])
        self.assertIn('기산일 2026-03-13(원문에 날짜가 없어 거래일 달력으로 셈)', F['확정 발행가 산식(원문 글에서 읽은 값)']['claim'])
        with mock.patch.object(C, 'covered', lambda day: False):                                     # 표가 없는 해: 예전처럼 단정하지 않음
            F, held, notes, T = run(doc, MK, prices=px([('2026-01-01', 10000)], upto='2026-03-16'))
            self.assertNotIn('1차 발행가(시세로 계산 — 회사 공시 전)', F); self.assertIn('휴장일 표가 없는 해라 평일로 센 어림값', F['확정 발행가 산식(원문 글에서 읽은 값)']['claim'])
            old = {'rcept_no': '1', 'rcept_dt': '2026-02-10', 'url': '', 'report_nm': 'x', 'parsed': F3.parse_rights_issue(doc)}
            F, held, notes, T = run(doc.replace('8,500', '7,700'), MK, history=[old], prices=px([('2026-01-01', 10000)], upto='2026-03-16'), rcept='2026-03-16')
            self.assertTrue(any('회사가 계산한 1차 발행가로 보았습니다' in x for x in notes))

    def test_holiday_shifts_base_day(self):                                                          # 기준일 앞에 휴장일(2026-03-02 삼일절 대체휴일)이 끼면 하루 더 앞으로
        doc = ri(record='2026년 03월 04일', sub=('2026년 04월 20일', '2026년 04월 21일'), d1='', d2='').replace('전 제3거래일()을', '전 제3거래일을')
        F, held, notes, T = run(doc, MK, prices=px([('2026-01-01', 10000)], upto='2026-02-20'))
        self.assertIn('기산일 2026-02-26(원문에 날짜가 없어 거래일 달력으로 셈)', F['확정 발행가 산식(원문 글에서 읽은 값)']['claim'])

class Probability(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S, cls.D = fake()
        cls.keep = PB.series_from_snapshot
        PB.series_from_snapshot = lambda snapshot='': (cls.S, 'fake')

    @classmethod
    def tearDownClass(cls):
        PB.series_from_snapshot = cls.keep; PB._LIB.clear()

    def rows(self, upto):
        return [{'trade_date': d, 'close': c, 'volume': 1000, 'trade_value': c * 1000, 'market_cap': c * 50_000_000} for d, c in self.S['000010'] if d <= upto]

    def doc(self, i1, i2):
        f = lambda d: f'{d[:4]}년 {d[5:7]}월 {d[8:]}일'
        return ri(record=f(self.D[i1 + 3]), sub=(f(self.D[i2 + 3]), f(self.D[i2 + 4])), d1=f(self.D[i1]), d2=f(self.D[i2]))

    def test_market_scenarios_and_units(self):
        L = self.D[300]; P0 = self.S['000010'][300][1]
        F, held, notes, T = run(self.doc(310, 330), MK, prices=self.rows(L), rcept=L)
        E = {k: v for k, v in F.items() if k.startswith('확정 발행가 추정')}
        self.assertEqual(len(E), 3); self.assertTrue(all(v['kind'] == 'forecast_model' for v in E.values()))
        lo, mid, hi = (E[f'확정 발행가 추정 — 시장 전체가 {x}']['value'] for x in ('10% 내릴 때', '제자리일 때', '10% 오를 때'))
        self.assertTrue(lo < mid < hi, (lo, mid, hi)); self.assertTrue(0.6 * P0 < mid < 0.85 * P0, (mid, P0))      # 할인율 20% 근처
        c = E['확정 발행가 추정 — 시장 전체가 제자리일 때']
        self.assertRegex(c['claim'], r'예정 발행가\(8,500원\)보다 낮게 정해질 확률 (약 \d0%|\d+% 미만|\d+% 넘음)'); self.assertIn(f"{sum(C.is_open(d) for d in self.D[301:331])}거래일(한국거래소 휴장일 반영)", c['formula'])   # v0.38 T2-5: 시험 자료의 2022년 날짜에도 휴장일 표가 생김; self.assertIn('과거 검증', c['formula'])
        t = next(x for x in T if x['title'].startswith('확정 발행가 추정')); self.assertEqual(len(t['rows']), 3); self.assertIn('더 넓을 수 있습니다', t['hint'])
        again = run(self.doc(310, 330), MK, prices=self.rows(L), rcept=L)[0]
        self.assertEqual(again['확정 발행가 추정 — 시장 전체가 제자리일 때']['claim'], c['claim'])                    # 난수 없음

    def test_too_far_or_unknown_company_is_held(self):
        L = self.D[150]
        F, held, notes, T = run(self.doc(200, 290), MK, prices=self.rows(L), rcept=L)
        self.assertTrue(any('너무 멀어요' in h for h in held)); self.assertFalse(any(k.startswith('확정 발행가 추정') for k in F))
        self.assertTrue(any(x['title'].startswith('확정 발행가 시나리오') for x in T))                               # 표는 그대로 보임
        L = self.D[300]
        F, held, notes, T = run(self.doc(310, 330), MK, prices=self.rows(L), rcept=L, ticker='999999')
        self.assertTrue(any('변동성(또는 과거 경로)을 구하지 못해' in h for h in held))


class Card(__import__('tests.test_easy', fromlist=['EasyBase']).EasyBase):
    """카드 한 장으로 끝까지: 원문 사본 → T15 → T06 시세 → N20 → 답 → 확인서 다시 계산."""
    NO = '20261005800001'

    def setUp(self):
        import io, os, tempfile, zipfile
        super().setUp()
        self.docs = tempfile.TemporaryDirectory(); root = Path(self.docs.name) / 'dart_docs'; root.mkdir(parents=True)
        os.environ['MODU_NODES_DART_DOCS'] = str(root)
        body = ri(record='2026년 11월 20일', sub=('2026년 12월 21일', '2026년 12월 22일'), d1='2026년 11월 17일', d2='2026년 12월 16일')
        b = io.BytesIO()
        with zipfile.ZipFile(b, 'w') as z:
            z.writestr(f'{self.NO}.xml', body.encode('utf-8'))
        b = b.getvalue(); (root / f'{self.NO}.zip').write_bytes(b)
        man = {'tool': 'mrn.dartdocs', 'tool_version': 1, 'origin': '시험', 'listed': {}, 'failed': {}, 'docs': {self.NO: {
            'ticker': '042700', 'corp_code': '00000001', 'name': '한미반도체', 'report_nm': '주요사항보고서(유상증자결정)', 'rcept_dt': '2026-10-05', 'kind': 'rights_issue',
            'file': f'{self.NO}.zip', 'bytes': len(b), 'sha256': D._sha(b), 'members': [], 'url': 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' + self.NO}}}
        D._save_manifest(root, man)

    def tearDown(self):
        import os
        os.environ.pop('MODU_NODES_DART_DOCS', None); self.docs.cleanup()
        super().tearDown()

    def test_end_to_end_with_receipt(self):
        r = self.c.post('/api/easy/run', json={'card': 'filing', 'company': '042700', 'cutoff': '2026-10-20T16:00:00+09:00', 'rcept_no': self.NO})
        self.assertEqual(r.status_code, 201, r.text); rid = r.json()['id']; self.wait(rid)
        a = self.c.get(f'/api/easy/answer/{rid}').json(); txt = {i['label']: i['text'] for i in a['items']}; js = json.dumps(a, ensure_ascii=False)
        self.assertIn('20.00%', txt['증자비율']); self.assertIn('이론 권리락 주가(예정 발행가 기준)', txt); self.assertIn('확정 발행가 산식(원문 글에서 읽은 값)', txt)
        self.assertIn('확정 발행가 시나리오', js)                                                       # 표가 답에 실림
        self.assertIn('변동성(또는 과거 경로)을 구하지 못해', js)                                        # 시험 사본은 회사가 2곳뿐 → 확률은 보류
        self.assertNotIn('호재', js.replace('호재·악재 같은 방향 판단: 하지 않음', ''))
        rc = self.c.get(f'/api/easy/receipt/{rid}').json()
        v = self.c.post('/api/easy/verify', json={'receipt': rc}).json()
        self.assertTrue(v['ok'], v); self.assertEqual(v['matched'], v['total'])


@unittest.skipUnless(REAL_DOCS.is_dir() and any(d['kind'] == 'rights_issue' for d in D.load_manifest(REAL_DOCS)['docs'].values()), '이 PC에 유상증자 결정 원문 사본이 있을 때만')
class RealDocs(unittest.TestCase):
    def test_all_read_and_formula_reproduces_final_price(self):
        """실제 원문 전부: 멈추지 않고 읽고, 주주배정 증자의 확정 발행가를 「그 전 공시 + 기산일까지의 시세」만으로 다시 계산하면 회사가 공시한 값과 같아야 한다."""
        from mrn import market as M
        man = D.load_manifest(REAL_DOCS); n = 0; modes = {}; hit = miss = 0
        try:
            mroot = M.resolve(''); mman = M.load_manifest(mroot)
        except Exception:
            mroot = None
        G = {}
        for no, d in sorted(man['docs'].items()):
            if d['kind'] != 'rights_issue':
                continue
            f = FL.load(d['ticker'], no, '2099-01-01', REAL_DOCS); p = f['parsed']; n += 1; modes[p['mode']] = modes.get(p['mode'], 0) + 1
            FL.compute(json.loads(json.dumps(f)), None)
            self.assertTrue(p['new'] or p['new_other'], no); self.assertIsNotNone(p['mode'], no)
            if p['mode'] == 'holders':
                G.setdefault(d['ticker'], []).append((d['rcept_dt'], no, p))
        self.assertGreaterEqual(n, 50); self.assertGreaterEqual(modes.get('holders', 0), 30); self.assertGreaterEqual(modes.get('third', 0), 10)
        for t, L in G.items():
            L.sort(); fin = [x for x in L if x[2]['final']]
            stage = [x for x in L if not x[2]['final'] and x[2]['pricing']['standard'] and x[2]['record_date'] and x[2]['sub'][0]]
            if not fin or not stage or mroot is None:
                continue
            try:
                rows, _ = M.read_rows(mroot, mman, 'price_daily', t)
            except M.SnapshotError:
                continue
            day, no, p = stage[-1]; want = fin[-1][2]['final']; fday = fin[-1][0]
            pr = sorted((r for r in rows if r.get('source') == 'fsc' and str(r['trade_date'])[:10] < fday), key=lambda r: str(r['trade_date']))
            f = FL.load(t, no, day + 'T23:59:59+09:00', REAL_DOCS)
            F, held, T, notes = FL.compute(json.loads(json.dumps(f)), None, prices=pr, ticker=t)
            got = next((x['value'] for x in F if x['name'].startswith('확정 발행가(시세로 계산')), None)
            if got is None:
                continue
            hit += got == want; miss += got != want
            self.assertLessEqual(abs(got - want) / want, 0.003, (t, got, want))
        self.assertGreaterEqual(hit, 5, (hit, miss)); self.assertLessEqual(miss, 1)


if __name__ == '__main__':
    unittest.main()
