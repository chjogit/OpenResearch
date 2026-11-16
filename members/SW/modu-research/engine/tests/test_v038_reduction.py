"""v0.38 T2-3 감자 결정: 원문 읽기 · 방식 가르기 · 주식 수·자본금·비율 대조 · 정정 전후 차이 · 빈 정정 공시 · 시험용 표본 받기 도구 · 실제 원문 전부."""
import json, os, tempfile, unittest, urllib.parse
from pathlib import Path
from mrn import dartdocs as D, dartsamples as DS, filing as FL, filing2 as F2
from tests.test_v038_filing import html

REAL_DOCS = Path(__file__).resolve().parents[2] / '_sources' / 'dart_docs'


def red(qty='654,612', other='-', par='500', cap=('40,662,398,000', '40,335,092,000'), sh=('73,799,619', '73,145,007'), sho=('-', '-'), ratio='0.89',
        base='-', method='자기주식 소각', corr=None, relist='-'):
    r = []
    if corr:
        r += [['정정신고(보고)'], ['1. 정정대상 공시서류 :', '주요사항보고서(감자결정)'], ['2. 정정대상 공시서류의 최초제출일 :', corr[0]],
              ['3. 정정사항'], ['항목', '정정사유', '정정전', '정정후'], ['6. 감자기준일', corr[1], '-', '2025.05.07']]
    r += [['감자 결정'], ['1. 감자주식의 종류와 수', '보통주식 (주)', qty, '기타주식 (주)', other], ['2. 1주당 액면가액 (원)', par],
          ['3. 감자전후 자본금', '감자전 (원)', '감자후 (원)'], [cap[0], cap[1]], ['4. 감자전후 발행주식수', '구 분', '감자전 (주)', '감자후 (주)'],
          ['보통주식(주)', sh[0], sh[1]], ['기타주식(주)', sho[0], sho[1]], ['5. 감자비율', '보통주식 (%)', ratio, '기타주식 (%)', '-'], ['6. 감자기준일', base],
          ['7. 감자방법', method], ['8. 감자사유', '주주가치 제고'], ['9. 감자일정', '주주총회 예정일', '2025-03-20'], ['명의개서정지기간', '-'],
          ['매매거래정지예정기간', '시작일', '-', '종료일', '-'], ['신주상장예정일', relist], ['12. 이사회결의일(결정일)', '2025.01.06']]
    return html(r)


def run(doc, mkt=None, history=(), newer=(), no='20250106000195'):
    f = {'kind': 'capital_reduction', 'parsed': F2.parse_capital_reduction(doc), 'report_nm': '주요사항보고서(감자결정)', 'rcept_dt': '2025-01-06', 'url': '', 'rcept_no': no,
         'history': list(history), 'newer': list(newer)}
    F, held, T, notes = FL.compute(json.loads(json.dumps(f)), mkt)
    return {x['name']: x for x in F}, held, notes


class Reduction(unittest.TestCase):
    def test_parse_and_types(self):
        p = F2.parse_capital_reduction(red())
        self.assertEqual((p['qty'], p['qty_other'], p['par'], p['capital'], p['shares'], p['ratio_text'][0], p['type'], p['agm'], p['decided']),
                         (654612, None, 500, {'before': 40662398000, 'after': 40335092000}, {'before': 73799619, 'after': 73145007}, '0.89', 'treasury', '2025-03-20', '2025-01-06'))
        for m, t in (('자기주식소각', 'treasury'), ('주식병합(보통주 5주를 1주로 병합)', 'merge'), ('액면가액 감액(500원→100원)', 'par_cut'), ('유상감자(주식소각)', 'paid'),
                     ('무상감자(주식소각)', 'free_retire'), ('강제 무상', 'other'), ('-', 'empty')):
            self.assertEqual(F2.reduction_type(m), t, m)

    def test_treasury_checks(self):
        F, held, notes = run(red(), {'date': '2025-01-03', 'close': 60000.0, 'market_cap': 4.4e12, 'shares': 73799619, 'avg_value_20': 1e10})
        self.assertIn('73,145,007주 · 공시의 감자 후 값과 같음', F['감자 후 주식 수 대조(보통주)']['claim'])
        self.assertIn('0.89% · 공시 값 0.89%와 같음', F['감자비율(보통주)']['claim'])
        self.assertIn('감자 주식 수 × 액면가와 같음', F['줄어드는 자본금']['claim'])
        self.assertEqual(F['감자 주식의 시가 환산']['value'], 654612 * 60000.0)
        self.assertTrue(any('회사 밖으로 나가는 돈이 없고' in n for n in notes))
        self.assertFalse(any('검증한 뒤 붙임' in h for h in held))
        blob = json.dumps([list(F.values()), held, notes], ensure_ascii=False)
        for w in ('호재', '악재', '긍정적', '부정적', '매수', '매도'):
            self.assertNotIn(w, blob)

    def test_mismatches_are_flagged(self):
        F, *_ = run(red(sh=('73,799,619', '73,145,000'), ratio='0.95', cap=('40,662,398,000', '40,335,000,000')))
        self.assertIn('-7주 다름', F['감자 후 주식 수 대조(보통주)']['claim'])
        self.assertIn('공시 값 0.95%와 -0.06%p 다름', F['감자비율(보통주)']['claim'])
        self.assertIn('다름 — 원문을 직접 확인', F['줄어드는 자본금']['claim'])

    def test_ratio_decimals_of_filing(self):
        self.assertIn('같음(공시는 소수 1자리)', F2._ratio_check(0.2924, '0.3'))
        self.assertIn('같음(공시는 소수 0자리)', F2._ratio_check(0.3, '0'))
        self.assertIn('올림 또는 버림', F2._ratio_check(0.887, '0.88'))
        self.assertEqual(F2._ratio_check(1.0, '-'), '')

    def test_merge_uniform_value(self):                              # 5주→1주: 손으로 계산한 값과 견줌
        mk = {'date': '2025-01-03', 'close': 800.0, 'market_cap': 800.0 * 25_000_000, 'shares': 25_000_000}
        F, held, notes = run(red(qty='20,000,000', sh=('25,000,000', '5,000,000'), ratio='80.00', cap=('12,500,000,000', '2,500,000,000'), method='주식병합(보통주 5주를 동일 액면 1주로 병합하는 무상감자)'), mk)
        self.assertEqual(F['감자 방식(방법 칸의 글로 가름)']['claim'], '주식 병합(무상감자)')
        self.assertEqual(F['감자비율(보통주)']['value'], 80.0); self.assertIn('공시 값 80.00%와 같음', F['감자비율(보통주)']['claim'])
        self.assertIn('20,000,000주 · 감자 주식 수 칸과 같음', F['줄어드는 주식 수(보통주)']['claim'])
        self.assertIn('줄어드는 주식 수 × 액면가와 같음', F['줄어드는 자본금']['claim'])
        self.assertEqual(F['병합 배수']['value'], 5.0)
        self.assertIn('5,000,000주 · 공시의 감자 후 값과 같음', F['병합 뒤 주식 수 대조(보통주)']['claim'])
        self.assertIn('20주 (단주 없음)', F['100주를 가진 주주의 병합 뒤 주식 수']['claim'])
        self.assertEqual(F['병합 뒤 1주의 산술 값']['value'], 4000.0)
        self.assertIn('실제 거래 재개 가격은 다를 수 있음', F['병합 뒤 1주의 산술 값']['formula'])
        self.assertEqual(F['자본잠식을 가르는 선(자본총계가 이 값보다 작으면 자본잠식)']['value'], 2_500_000_000)
        self.assertEqual(F['자본잠식률 50%가 되는 자본총계']['value'], 1_250_000_000)
        self.assertTrue(any('자본잠식률: 이 회사의 자본총계가 감자 결정 공시에 없어' in h for h in held))
        self.assertFalse(any('검증한 뒤 붙임' in h for h in held))

    def test_merge_whole_qty_and_fraction(self):                     # 감자 주식 수 칸에 전체 주식을 적은 공시 · 3주→1주의 단주
        F, held, notes = run(red(qty='30,000,001', sh=('30,000,001', '10,000,000'), ratio='66.67', cap=('15,000,000,500', '5,000,000,000'), method='기명식 보통주 3주를 같은 액면주식 1주로 무상병합'))
        self.assertIn('20,000,001주 · 감자 주식 수 칸(30,000,001주)에는 병합 대상 주식 전체를 적은 공시', F['줄어드는 주식 수(보통주)']['claim'])
        self.assertIn('33주 + 1주에 못 미치는 단주 0.3333주', F['100주를 가진 주주의 병합 뒤 주식 수']['claim'])
        self.assertIn('10,000,000주 · 공시의 감자 후 값과 같음', F['병합 뒤 주식 수 대조(보통주)']['claim'])
        self.assertIn('66.67%', F['감자비율(보통주)']['claim']); self.assertNotIn('다름', F['감자비율(보통주)']['claim'])

    def test_merge_decimal_ratio_and_nominal_rate(self):             # 1.37주→1주: 회사는 병합 비율로 계산한 감자비율을 적음
        F, held, notes = run(red(qty='6,000,000', sh=('22,256,689', '16,256,689'), ratio='27.0073', cap=('11,128,344,500', '8,128,344,500'), method='액면가 500원의 보통주 1.37주를 동일 액면금액 보통주 1주로 무상병합'))
        self.assertEqual(F['병합 배수']['value'], 1.37)
        self.assertIn('병합 비율(1.37주→1주)로 계산한 값과 같음', F['감자비율(보통주)']['claim'])
        self.assertIn('차이(주주별 단주 처리', F['병합 뒤 주식 수 대조(보통주)']['claim'])

    def test_merge_capital_proportional(self):                       # 자본금 ≠ 주식 수 × 액면가인 회사: 자본금을 병합 비율만큼 줄임
        F, held, notes = run(red(qty='9,000,000', par='1,000', sh=('10,000,000', '1,000,000'), ratio='90', cap=('10,839,700,000', '1,083,970,000'), method='보통주식 10주를 동일 액면가의 보통주식 1주로 병합하는 무상감자'))
        self.assertIn('감자 전 자본금을 병합 비율만큼 줄인 값과 같음', F['줄어드는 자본금']['claim'])

    def test_differential_merge_is_held(self):
        F, held, notes = run(red(qty='20,000,000', sh=('59,171,967', '2,782,098'), ratio='95.30', cap=('29,585,983,500', '1,391,049,000'),
                                 method='1. 최대주주가 보유하는 10,590,000주는 감자 후 353,000주로(감자비율 30:1) 2. 그외 주주들이 보유하는 48,581,967주는 2,429,098주로(감자비율 20:1) 병합하는 차등무상감자'))
        self.assertIn('차등·일부 병합', F['감자 방식(방법 칸의 글로 가름)']['claim'])
        self.assertNotIn('병합 뒤 1주의 산술 값', F); self.assertIn('방법 칸에 적힌 병합 비율', F)
        self.assertTrue(any('1주의 산술 값·주주별 주식 수는 계산하지 않음' in h for h in held))

    def test_par_cut(self):
        mk = {'date': '2025-01-03', 'close': 800.0, 'market_cap': 800.0 * 45_235_478, 'shares': 45_235_478}
        F, held, notes = run(red(qty='45,235,478', par='5,000', sh=('45,235,478', '45,235,478'), ratio='80', cap=('226,177,390,000', '45,235,478,000'), method='액면가 5,000원의 보통주를액면가 1,000원으로 감액함(액면가 감액 무상감자)'), mk)
        self.assertEqual(F['감자 방식(방법 칸의 글로 가름)']['claim'], '액면 감액(무상감자)')
        self.assertIn('감자 전과 같음', F['감자 후 주식 수 대조(보통주)']['claim'])
        self.assertEqual(F['1주당 액면가']['claim'], '5,000원 → 1,000원')
        self.assertIn('발행주식 수 × 액면가 감소분과 같음', F['줄어드는 자본금']['claim'])
        self.assertEqual(F['감자비율(자본금 기준)']['value'], 80.0); self.assertIn('같음', F['감자비율(자본금 기준)']['claim'])
        self.assertNotIn('감자 주식의 시가 환산', F); self.assertNotIn('감자비율(보통주)', F)
        self.assertTrue(any('1주의 산술 값도 바뀌지 않습니다' in x for x in notes))

    def test_par_cut_by_numbers_and_capital_above_par(self):
        F, held, notes = run(red(qty='51,746,348', sh=('51,746,348', '51,746,348'), ratio='80', cap=('25,873,174,000', '5,174,634,800'), method='무상감자'))   # 글로는 못 가름 → 숫자로
        self.assertEqual(F['감자 방식(방법 칸의 글로 가름)']['claim'], '액면 감액(무상감자)'); self.assertEqual(F['1주당 액면가']['claim'], '500원 → 100원')
        F, held, notes = run(red(qty='31,119,588', par='5,000', sh=('31,119,588', '31,119,588'), ratio='70.94', cap=('267,727,320,000', '77,798,970,000'), method='액면액 감소(금 5,000원→금 2,500원)'))
        self.assertIn('감자 후 자본금이 발행주식 수 × 감액 후 액면가와 같음', F['줄어드는 자본금']['claim'])
        self.assertIn('공시 값 70.94%와 같음', F['감자비율(자본금 기준)']['claim']); self.assertEqual(F['감자비율(액면가 기준)']['claim'], '50.00%')

    def test_paid(self):                                             # 12,683,181주 × 1,000원, 종가 1,250원
        mk = {'date': '2026-01-30', 'close': 1250.0, 'market_cap': 1250.0 * 63_415_904, 'shares': 63_415_904}
        F, held, notes = run(red(qty='12,683,181', par='1,000', sh=('63,415,904', '50,732,723'), ratio='20', cap=('70,784,607,000', '58,101,426,000'),
                                 method='- 유상소각대금 : 1주당 1,100원- 유상소각대금 지급 예정일 : 2026년 5월 7일'), mk)
        self.assertEqual(F['감자 방식(방법 칸의 글로 가름)']['claim'], '유상 소각(유상감자)')
        self.assertEqual(F['주주에게 지급되는 돈(회사 밖으로 나가는 돈)']['value'], 12_683_181 * 1100)
        self.assertEqual(F['감자차익 또는 감자차손']['value'], 12_683_181 * (1000 - 1100)); self.assertIn('감자차손', F['감자차익 또는 감자차손']['claim'])
        self.assertEqual(F['유상소각대금 ÷ 종가']['value'], -12.0)
        self.assertEqual(F['감자 뒤 1주의 산술 값']['value'], round((1250.0 * 63_415_904 - 12_683_181 * 1100) / (63_415_904 - 12_683_181), 2))
        self.assertNotIn('자본잠식을 가르는 선(자본총계가 이 값보다 작으면 자본잠식)', F)
        F, held, notes = run(red(qty='12,683,181', par='1,000', sh=('63,415,904', '50,732,723'), ratio='20', cap=('70,784,607,000', '58,101,426,000'), method='유상감자(주식소각)'))
        self.assertTrue(any('1주당 유상소각대금: 방법 칸·참고사항에서 읽지 못함' in h for h in held))

    def test_free_retire_and_mixed(self):
        mk = {'date': '2025-01-03', 'close': 2000.0, 'market_cap': 2000.0 * 8_000_000, 'shares': 8_000_000}
        F, held, notes = run(red(qty='1,000,000', sh=('8,000,000', '7,000,000'), ratio='12.50', cap=('4,000,000,000', '3,500,000,000'), method='최대주주 소유주식 1,000,000주 전부에 대하여 임의/무상 소각하여 감자'), mk)
        self.assertEqual(F['감자 방식(방법 칸의 글로 가름)']['claim'], '무상 소각')
        self.assertEqual(F['소각되지 않는 주식의 몫 배수']['value'], round(8 / 7, 6)); self.assertEqual(F['남는 주식 1주의 산술 값']['value'], round(2000 * 8 / 7, 2))
        self.assertIn('자기주식이면 해당 없음', F['남는 주식 1주의 산술 값']['formula'])
        F, held, notes = run(red(qty='100,000,000', sh=('200,000,000', '100,000,000'), ratio='50.00', cap=('100,000,000,000', '50,000,000,000'),
                                 method='1) 자기주식 10,054,236주(100.00%) : 무상감자 2) 자기주식을 제외한 발행주식 189,945,764주 중 89,945,764주 (47.35%) : 유상감자 3) 유상소각대금 : 1주당 470원'))
        self.assertEqual(F['감자 방식(방법 칸의 글로 가름)']['claim'], '여러 방식을 함께 쓰는 감자'); self.assertEqual(F['1주당 유상소각대금']['value'], 470)
        self.assertTrue(any('유상으로 소각되는 주식 수를 표에서 따로 가를 수 없어' in h for h in held)); self.assertNotIn('주주에게 지급되는 돈(회사 밖으로 나가는 돈)', F)

    def test_method_facts(self):
        mf = F2.method_facts
        self.assertEqual(mf('1) 액면금액 5,000원의 보통주식 1주를 액면금액 500원의 보통주식 10주로 주식분할 함.2) 1주당 액면금액 500원의 보통주 10주를 동일한 액면금액의 보통주 1주로 무상병합 함.')['ratios'], [[10.0, 1.0]])
        self.assertEqual(mf('액면가 100원의 우선주 10,000주를 동일 금액의 우선주 8,867주로 병합')['ratios'], [[10000.0, 8867.0]])
        self.assertEqual(mf('액면가액500원의 보통주4.7500주를 1주로 병합. 단, 이때 발생하는1주 미만의 단주는 관리인이 법원의 허가를 받아 무상 소각.')['kinds'], ['merge'])
        self.assertEqual(mf('10 :1 주식병합(기명식 보통주 10주를 같은 액면주식 1주로 병합하는 무상감자)')['ratios'], [[10.0, 1.0]])
        self.assertEqual(mf('- 발행주식(67,730,338주) 중 자기주식 제외 총수(63,415,904주)에 대해 감자비율 20% 적용- 유상소각대금 : 1주당 1,000원')['kinds'], ['paid'])
        self.assertEqual(mf('1주당 액면금액 500원의 보통주 5주를 동일 액면금액 보통주 1주로 무상감자')['kinds'], ['merge'])
        self.assertEqual(mf('주식 액면액을 오천원에서 일천원으로 감액하여 자본금 감소 (무상 액면감소)')['kinds'], ['par_cut'])

    def test_method_in_several_cells(self):
        doc = red(qty='202,356,634', par='5,000', sh=('202,356,634', '202,356,634'), ratio='80', cap=('1,011,783,170,000', '202,356,634,000'), method='액면가 5,000원의 보통주를')
        doc = doc.replace('8. 감자사유', '액면가 1,000원으로 감액함</td></tr><tr><td>(액면가 감액 무상감자)</td></tr><tr><td>8. 감자사유', 1)
        p = F2.parse_capital_reduction(doc)
        self.assertEqual(p['method'], '액면가 5,000원의 보통주를 액면가 1,000원으로 감액함 (액면가 감액 무상감자)'); self.assertEqual((p['type'], p['new_par']), ('par_cut', 1000))

    def test_empty_correction_is_not_called_withdrawal(self):
        F, held, notes = run(red(qty='-', par='-', cap=('-', '-'), sh=('-', '-'), ratio='-', method='-'))
        self.assertEqual(F, {}); self.assertIn('모두 비어 있어요', held[0]); self.assertNotIn('철회했', json.dumps(held, ensure_ascii=False))
        old = {'rcept_no': '20260114000080', 'rcept_dt': '2026-01-14', 'url': '', 'report_nm': 'x', 'parsed': F2.parse_capital_reduction(red())}
        F, held, notes = run(red(qty='-', par='-', cap=('-', '-'), sh=('-', '-'), ratio='-', method='-'), history=[old])
        self.assertTrue(any('이 공시에서는 모두 빈칸' in x for x in notes)); self.assertFalse(any('값은 같습니다' in x for x in notes))

    def test_correction_diff_and_reason(self):
        old = {'rcept_no': '20250106000195', 'rcept_dt': '2025-01-06', 'url': '', 'report_nm': 'x', 'parsed': F2.parse_capital_reduction(red())}
        new = red(sh=('72,563,745', '71,909,133'), ratio='0.90', base='2025.05.07', corr=('2025.01.06', '감자기준일 확정'))
        p = F2.parse_capital_reduction(new)
        self.assertEqual((p['corrects'], p['base_date'], p['shares']['before']), ('2025-01-06', '2025-05-07', 72563745))      # 정정표가 아니라 본문
        F, held, notes = run(new, history=[old], no='20250213001658')
        d = next(v for k, v in F.items() if '달라진 곳' in k)
        self.assertIn('달라진 곳 4곳', d['name'])
        self.assertIn('감자 전 주식 수(보통주) 73,799,619주 → 72,563,745주 (-1,235,874, -1.67%)', d['claim'])
        self.assertIn('감자기준일 — → 2025-05-07', d['claim'])
        self.assertTrue(any('정정사유(원문 그대로): 「감자기준일 확정」' in x for x in notes))            # 표 머리(정정전)가 아니라 첫 줄의 사유 칸
        empty = html([['정정신고(보고)'], ['2. 정정대상 공시서류의 최초제출일 :', '2026.01.14'], ['3. 정정사항'], ['항 목', '정정사유', '정 정 전', '정 정 후'],
                      ['주요사항보고서 / 거래소 신고의무 사항'], ['금융위원회 / 한국거래소 귀중']])
        self.assertIsNone(F2._correction_head(F2.tokens(empty))['correction_reason'])                   # 사유 줄이 없으면 지어내지 않음

    def test_decision_key(self):
        self.assertEqual(F2._decision_key({'corrects': '2025-01-06'}, '2025-02-13'), F2._decision_key({'corrects': None}, '2025-01-06'))


class Samples(unittest.TestCase):
    """시험용 표본 받기: 기간으로 훑고 · 상장사·종류만 · 근거 사본과 다른 폴더 · 키를 남기지 않음."""
    def test_fetch_filters_and_resume(self):
        import io, zipfile
        rows = [{'rcept_no': '20250301000001', 'report_nm': '주요사항보고서(감자결정)', 'rcept_dt': '20250301', 'corp_cls': 'K', 'stock_code': '123456', 'corp_code': '1', 'corp_name': '가나'},
                {'rcept_no': '20250301000002', 'report_nm': '주요사항보고서(감자결정)(종속회사의주요경영사항)', 'rcept_dt': '20250301', 'corp_cls': 'Y', 'stock_code': '222222', 'corp_code': '2', 'corp_name': '다라'},
                {'rcept_no': '20250301000003', 'report_nm': '주요사항보고서(감자결정)', 'rcept_dt': '20250301', 'corp_cls': 'E', 'stock_code': '', 'corp_code': '3', 'corp_name': '비상장'},
                {'rcept_no': '20250301000004', 'report_nm': '주요사항보고서(유상증자결정)', 'rcept_dt': '20250301', 'corp_cls': 'Y', 'stock_code': '333333', 'corp_code': '4', 'corp_name': '마바'}]
        calls = []

        def get(url, *a, **k):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)); calls.append(q)
            if 'document.xml' in url:
                b = io.BytesIO()
                with zipfile.ZipFile(b, 'w') as z:
                    z.writestr('a.xml', red())
                return b.getvalue()
            self.assertNotIn('corp_code', q)                                     # 회사를 정하지 않고 기간으로
            rs = [r for r in rows if q['bgn_de'] <= r['rcept_dt'] <= q['end_de']]
            return json.dumps({'status': '000', 'list': rs, 'total_page': 1} if rs else {'status': '013'}).encode()
        with tempfile.TemporaryDirectory() as d:
            n = DS.fetch(['capital_reduction'], '2025-01-01', '2025-08-01', out_root=d, get=get, env={'DART_API_KEY': 'SECRETKEY'}, sleep=0, log=lambda *a: None)
            self.assertEqual(n, 1)                                                # 상장사 · 자회사 아님 · 종류 맞음 → 1건
            man = D.load_manifest(d)
            self.assertEqual(list(man['docs']), ['20250301000001']); self.assertEqual(man['docs']['20250301000001']['added_by'], 'sample')
            self.assertEqual(D.verify_all(d)['bad'], [])
            self.assertNotIn('SECRETKEY', Path(d, 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(DS.fetch(['capital_reduction'], '2025-01-01', '2025-08-01', out_root=d, get=get, env={'DART_API_KEY': 'SECRETKEY'}, sleep=0, log=lambda *a: None), 0)
            p = F2.parse_capital_reduction('\n'.join(t for _, t in D.open_doc('20250301000001', d)[0]))
            self.assertEqual(p['type'], 'treasury')
        self.assertTrue(all((date_gap(a, b) <= 86) for a, b in DS.windows('2025-01-01', '2026-11-12')))
        self.assertNotEqual(DS.samples_dir(), D.docs_dir())

    def test_refuses_without_key_or_bad_kind(self):
        with self.assertRaises(D.DartDocsError) as e:
            DS.fetch(['capital_reduction'], '2025-01-01', env={})
        self.assertEqual(e.exception.code, 'no_key')
        with self.assertRaises(D.DartDocsError) as e:
            DS.fetch(['nope'], '2025-01-01', env={'DART_API_KEY': 'k'})
        self.assertEqual(e.exception.code, 'bad_kind')


def date_gap(a, b):
    from datetime import date
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


@unittest.skipUnless(REAL_DOCS.is_dir() and any(d['kind'] == 'capital_reduction' for d in D.load_manifest(REAL_DOCS)['docs'].values()), '이 PC에 감자 결정 원문 사본이 있을 때만')
class RealDocs(unittest.TestCase):
    def test_all_read_and_checks_hold(self):
        man = D.load_manifest(REAL_DOCS); n = 0; types = {}
        for no, d in sorted(man['docs'].items()):
            if d['kind'] != 'capital_reduction':
                continue
            f = FL.load(d['ticker'], no, '2099-01-01', REAL_DOCS); p = f['parsed']; n += 1; types[p['type']] = types.get(p['type'], 0) + 1
            F, held, T, notes = FL.compute(json.loads(json.dumps(f)), None)
            self.assertFalse(any('읽지 못함' in h for h in held), no)
            if p['type'] == 'empty' or f.get('newer'):
                continue
            self.assertIsNotNone(p['shares'].get('before'), no); self.assertIsNotNone(p['capital'].get('after'), no)
            for x in F:
                if x['name'].startswith(('감자 후 주식 수 대조', '줄어드는 자본금')):
                    self.assertIn('같음', x['claim'], (no, x['name'], x['claim']))
                if x['name'].startswith('감자비율'):
                    self.assertNotIn('다름', x['claim'], (no, x['claim']))
        self.assertGreaterEqual(n, 20); self.assertGreaterEqual(types.get('treasury', 0), 15)


SAMPLES = Path(__file__).resolve().parents[2] / '_sources' / 'dart_docs_samples'


@unittest.skipUnless((SAMPLES / 'manifest.json').is_file(), '이 PC에 시험용 표본(_sources/dart_docs_samples)이 있을 때만')
class Samples(unittest.TestCase):
    def test_market_wide_reduction_samples(self):                    # 상장사 전체의 감자 결정 원문: 멈추지 않고, 방식을 가르고, 대조가 어긋나는 것은 드물어야 한다
        man = D.load_manifest(SAMPLES); n = 0; types = {}; off = []
        mk = {'date': '2025-01-02', 'close': 1234.0, 'market_cap': 1234.0 * 50_000_000, 'shares': 50_000_000}
        for no, d in sorted(man['docs'].items()):
            if d['kind'] != 'capital_reduction':
                continue
            p = F2.parse_capital_reduction('\n'.join(t for _, t in D.open_doc(no, SAMPLES, man)[0])); n += 1; types[p['type']] = types.get(p['type'], 0) + 1
            self.assertIn(p['type'], F2.RED_TYPE, no)
            for m in (None, mk):
                f = {'kind': 'capital_reduction', 'parsed': p, 'report_nm': d['report_nm'], 'rcept_dt': d['rcept_dt'], 'url': d['url'], 'rcept_no': no, 'history': [], 'newer': []}
                F, held, T, notes = FL.compute(json.loads(json.dumps(f)), m)
            if p['type'] == 'merge':
                self.assertTrue(any(x['name'] == '병합 배수' for x in F), no)
            off += [(no, x['name']) for x in F if '다름' in x['claim'] and '작은 차이' not in x['claim']]
        self.assertGreaterEqual(n, 200)
        for t in ('merge', 'par_cut', 'treasury', 'free_retire', 'paid', 'mixed', 'merge_diff'):
            self.assertGreaterEqual(types.get(t, 0), 1, t)
        self.assertLessEqual(len(off), max(3, n // 50), off)             # 회사가 표를 다르게 채운 드문 경우만(2% 안)


if __name__ == '__main__':
    unittest.main()
