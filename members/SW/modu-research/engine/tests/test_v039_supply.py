"""v0.39 T3-2(J31·J32) 공급계약·타법인 주식(2등급)을 공시 숫자로만.
- 비율은 다시 계산하지 않고 공시 값을 그대로 · 계약기간 1년치(1년 = 365일) · 1년 이하·종료일 미정은 나누지 않음.
- 정정 공시: 원래 공시일·정정까지 걸린 기간 · 계약일이 1년 넘게 앞서면 「이미 맺은 계약」 · 정정사항 표 원문 그대로 ·
  문구 항목은 새로 들어가거나 바뀐 문장만 · 금액이 처음 공개되면 알림 · 같은 계약의 정정 묶음(정정의 정정 포함) · 기준 연도가 오래되면 알림.
- 타법인: 취득 전 지분(이미 100% 가진 회사에 더 넣는 돈) · 처분 전 지분 · 풋옵션 등 계약 · 주요사항보고서 정정표(표지 글은 표가 아님).
- 받는 종류: 제목으로 4종 분류(자회사 공시 제외), 계산 종류에 들어감, 자동 받기는 3등급만 건너뜀(J32).
표본 문서는 실제 DART 원문(2025~2026)의 칸 순서를 줄여 옮긴 합성 문서다(숫자는 원문 값)."""
import inspect
import unittest

from mrn import autocheck as AC, dartdocs as D, filing as FL, filing4 as F4, filing_grade as G
from mrn.filing import _won, _p, _pct, stated_check


def doc(*cells):
    return ''.join(f'<td>{c}</td>' for c in cells)


SUPPLY_BODY = lambda amt, rev, ratio, s, e, cd, etc=(), name='윤활기유 제품 공급계약', party='MOTIVA ENTERPRISES LLC.', title='단일판매ㆍ공급계약 체결': (
    title, '1. 판매ㆍ공급계약 구분', '상품공급', '- 체결계약명', name, '2. 계약내역', '계약금액(원)', amt, '최근매출액(원)', rev, '매출액대비(%)', ratio,
    '대규모법인여부', '해당', '3. 계약상대', party, '- 회사와의 관계', '-', '4. 판매ㆍ공급지역', '북미', '5. 계약기간', '시작일', s, '종료일', e,
    '6. 주요 계약조건', '계약금ㆍ선급금 유무', '무', '7. 계약(수주)일자', cd, '8. 공시유보 관련내용', '유보사유', '-', '유보기한', '-',
    '9. 기타 투자판단과 관련한 중요사항', *etc, '※ 관련공시', '-')

HMM = doc(*SUPPLY_BODY('4,697,159,508,000', '10,891,442,877,031', '43.13', '2030-04-01', '2056-10-31', '2026-09-07', name='장기화물운송계약', party='Vale International SA'))
SOIL_FIX = doc('정정신고(보고)', '정정일자', '2026-01-14', '1. 정정관련 공시서류', '단일판매ㆍ공급계약 체결', '2. 정정관련 공시서류제출일', '2023-01-18',
               '3. 정정사유', '계약금액 변경', '4. 정정사항', '정정항목', '정정전', '정정후',
               '2. 계약내역 / 계약금액(원)', '1,540,351,481,571', '1,382,746,748,686', '2. 계약내역 / 매출액대비(%)', '9.2', '8.2',
               '9. 기타 투자판단과 관련한 중요사항', '- 상기 2. 계약금액은 추정 공급물량과 2021년 3월 평균 환율을 기초로 산정함.',
               '- 상기 2. 계약금액은 해당 제품의 2022년~2025년 실제 공급 실적임.', '- 계약 종료에 따라 거래금액이 확정되어 정정공시합니다.',
               *SUPPLY_BODY('1,382,746,748,686', '16,829,680,770,391', '8.2', '2022-01-01', '2025-12-31', '2021-06-01',
                            etc=('- 상기 2. 계약금액은 해당 제품의 2022년~2025년 실제 공급 실적임.', '- 상기 2. 최근매출액은 2020년 연결재무제표 기준임.')))
UNHOLD = doc('정정신고(보고)', '정정일자', '2025-12-17', '1. 정정관련 공시서류', '단일판매ㆍ공급계약 체결', '2. 정정관련 공시서류제출일', '2024-10-15',
             '3. 정정사유', '공시유보 해제 및 계약해지 사실 안내', '4. 정정사항', '정정항목', '정정전', '정정후',
             "'2. 계약내역'의 '계약금액(원)'", '-', '9,603,075,000,000', "'8. 공시유보 관련내용'의 '유보사유'", '경영상 비밀유지', '-',
             '9. 기타 투자판단과 관련한 중요사항', "라. 상기 ‘2.계약내역’의 ‘계약금액(원)'은 유보기한 종료 후 공시 예정임", '바. 본 계약은 2025년 12월 17일자로 해지되었음.', '-',
             *SUPPLY_BODY('9,603,075,000,000', '33,745,469,740,463', '28.5', '2027-01-01', '2032-12-31', '2024-10-14', party='Ford Motor Company',
                          etc=('바. 본 계약은 2025년 12월 17일자로 해지되었음.', "- 상기 '2.계약내역'의 최근매출액은 2023년 연결재무제표 기준임")))
SHORT = doc(*SUPPLY_BODY('155,283,839,000', '2,889,412,422,255', '5.37', '2026-01-01', '2026-12-31', '2026-06-15', etc=('- 상기 2의 최근 매출액은 2025년 연결재무제표 기준입니다.',)))
NOAMT = doc(*SUPPLY_BODY('-', '2,416,184,211,886', '-', '2021-09-09', '-', '2021-09-09'))
CANCEL_FIX = doc('정정신고(보고)', '정정일자', '2026-07-31', '1. 정정관련 공시서류', '단일판매ㆍ공급계약 해지', '2. 정정관련 공시서류제출일', '2026-04-29',
                 '3. 정정사유', '효력 정지 가처분 신청 인용', '4. 정정사항', '정정항목', '정정전', '정정후', '8. 기타 투자판단과 관련한 중요사항',
                 '- 가처분 신청이 인용(2026.04.29)되어 당사의 시공자 지위가 임시로 회복되었습니다.', '- 가처분 신청이 인용(2026.04.29)되어 당사의 시공자 지위가 임시로 회복되었습니다.',
                 '- 가처분 신청이 다시 인용(2026.07.31)됨으로써 당사의 시공자 지위가 임시로 회복되었습니다.', '-', '단일판매ㆍ공급계약 해지',
                 '1. 판매ㆍ공급계약 해지 구분', '공사수주', '- 해지계약명', '상대원2구역 주택재개발정비사업', '2. 해지내역', '해지금액(원)', '984,880,974,835',
                 '최근매출액(원)', '7,402,425,126,660', '매출액대비(%)', '13.30', '3. 계약상대', '상대원2구역 조합', '- 회사와의 관계', '-', '4. 계약기간', '시작일', '-', '종료일', '-',
                 '5. 해지 주요사유', '발주처(조합)의 해지 결정 통보', '6. 해지일자', '2026-04-11', '7. 공시유보 관련내용', '유보사유', '-',
                 '8. 기타 투자판단과 관련한 중요사항', '- 가처분 신청이 인용(2026.04.29)되어 당사의 시공자 지위가 임시로 회복되었습니다.',
                 '- 가처분 신청이 다시 인용(2026.07.31)됨으로써 당사의 시공자 지위가 임시로 회복되었습니다.')

EQ_BODY = lambda w, target, rel, tot, qty, amt, eq, ratio, aq, ap, purpose, put='아니오', ctr='-', etc=(): (
    f'타법인 주식 및 출자증권 {w}결정', '1. 발행회사', '회사명', target, '국적', '대한민국', '회사와 관계', rel, '발행주식총수(주)', tot,
    f'2. {w}내역', f'{w}주식수(주)', qty, f'{w}금액(원)', amt, '자기자본(원)', eq, '자기자본대비(%)', ratio, '대규모법인여부', '해당',
    f'3. {w}후 소유주식수 및 지분비율', '소유주식수(주)', aq, '지분비율(%)', ap, '4. 취득방법', '현금취득', f'5. {w}목적', purpose, f'6. {w}예정일자', '2026-05-15',
    '7. 이사회결의일(결정일)', '2025-11-05', '8. 풋옵션 등 계약 체결여부', put, '- 계약내용', ctr, '9. 기타 투자판단과 관련한 중요사항', *etc, '※ 관련공시', '-')
SUBSID = doc(*EQ_BODY('취득', '(주)더현대광주', '계열회사', '6,200,000', '3,000,000', '150,000,000,000', '6,234,443,481,814', '2.41', '9,200,000', '100', '종속회사의 유상증자 참여',
                      etc=("3. 상기 '2.취득내역'의 자기자본은 당사의 2024년 연결재무제표 기준임",)))
PUT = doc(*EQ_BODY('취득', '주식회사 쿠오카스킨', '-', '6,596,153', '3,547,176', '9,599,999,230', '198,554,792,679', '4.83', '3,547,176', '33.61', '지분투자', put='예',
                   ctr='- 기존주주의 풋옵션 (당사의 매수의무) : 기존주주는 보유지분을 당사에 매도할 수 있는 풋옵션을 보유합니다.'))
SALE = doc(*EQ_BODY('처분', '삼성전자주식회사', '계열회사', '5,919,637,922', '1,091,273', '227,530,420,500', '15,602,214,746,140', '1.46', '86,967,675', '1.47', '위험 사전 해소'))
MAJOR_FIX = doc('타법인 주식 및 출자증권 양도결정', '정 정 신 고 (보고)', '2026년 07월 09일', '1. 정정대상 공시서류 :', '주요사항보고서(타법인 주식 및 출자증권 양도 결정)',
                '2. 정정대상 공시서류의 최초제출일 :', '2026년 05월 27일', '3. 정정사항', '항 목', '정정사유', '정 정 전', '정 정 후',
                '5. 양도예정일자', "'7. 거래대금지급'의 '나. Milestone Payment'", '가 완료될 것으로 예상되는 시점으로 양도예정일자 변경', '2026년 08월 24일', '2035년 04월 15일',
                '13. 기타 투자판단과 관련한 중요사항', '양도예정일자 정정', "- 상기 '5. 양도예정일자'는 본 건 계약상 거래종결 기한임.", '거래종결 조건이 충족됨에 따라', '2027.07.09(목)에 대금수령 완료함.',
                '주요사항보고서 / 거래소 신고의무 사항', '금융위원회 / 한국거래소 귀중', '회 사 명 :', '주식회사 녹십자',
                '타법인 주식 및 출자증권 양도결정', '1. 발행회사', '회사명', 'Curevo, Inc.', '회사와 관계', '-', '발행주식총수(주)', '91,030,254',
                '2. 양도내역', '양도주식수(주)', '21,075,336', '양도금액(원)(A)', '462,058,340,101', '총자산(원)(B)', '2,971,095,184,896', '총자산대비(%)(A/B)', '15.55',
                '자기자본(원)(C)', '1,394,272,744,164', '자기자본대비(%)(A/C)', '33.14', '3. 양도후 소유주식수 및 지분비율', '소유주식수(주)', '-', '지분비율(%)', '-',
                '4. 양도목적', '신사업 투자 재원 확보', '5. 양도예정일자', '2035년 04월 15일', '6. 거래상대방', '회사명(성명)', 'Eli Lilly and Company',
                '13. 기타 투자판단과 관련한 중요사항', "- 상기 '2. 양도내역'의 '자기자본'은 2025년말 연결재무제표 기준임")
H = {'won': _won, 'p': _p, 'pct': _pct, 'check': stated_check, 'est': None}


def run(kind, html, rcept_dt, history=()):
    f = {'kind': kind, 'parsed': F4.PARSERS[kind](html), 'rcept_no': '20990101000001', 'rcept_dt': rcept_dt, 'report_nm': '시험', 'url': 'u',
         'history': list(history), 'newer': []}
    F, held, T, notes = [], [], [], []
    fact = lambda name, claim, value=None, unit=None, formula=None: F.append({'name': name, 'claim': claim, 'kind': 'fact_official', 'value': value})
    calc = lambda name, claim, formula, value=None, unit=None: F.append({'name': name, 'claim': claim, 'kind': 'derived', 'value': value, 'formula': formula})
    F4.compute(kind, f, None, fact, calc, held, T, notes, H)
    return {x['name']: x for x in F}, held, T, notes, f


class Supply(unittest.TestCase):
    def test_year_share_uses_days_365_and_keeps_stated_ratio(self):
        F, held, T, notes, f = run('supply_contract', HMM, '2026-09-08')
        n = 9711                                                   # 2030-04-01 ~ 2056-10-31 + 1일
        self.assertEqual(F['계약기간']['value'], n)
        self.assertAlmostEqual(F['계약금액의 1년치']['value'], 4697159508000 * 365 / n, places=3)
        self.assertAlmostEqual(F['1년치 ÷ 최근 매출액']['value'], 4697159508000 * 365 / n / 10891442877031 * 100, places=10)
        self.assertEqual(round(F['1년치 ÷ 최근 매출액']['value'], 2), 1.62)
        self.assertEqual(F['매출액 대비(공시)']['claim'], '43.13%')                       # 공시 값 그대로(다시 계산하지 않음 — J31)
        self.assertTrue(any('시작일(2030-04-01)이 공시일보다 3년' in x for x in notes))
        self.assertTrue(any('기준 연도: 원문 기타 사항에 적혀 있지 않아요' in x for x in notes))
        self.assertNotIn('정정 공시', F)

    def test_one_year_or_less_not_divided(self):
        F, held, T, notes, f = run('supply_contract', SHORT, '2026-06-15')
        self.assertNotIn('계약금액의 1년치', F)
        self.assertTrue(any('1년 이하라 1년치로 나누지 않았어요' in x for x in notes))
        self.assertTrue(any(x.startswith('매출액 기준: 2025년 연결') for x in notes))

    def test_dash_amount_and_open_end_are_held(self):
        F, held, T, notes, f = run('supply_contract', NOAMT, '2026-05-29')
        self.assertTrue(any(h.startswith('계약금액: 원문에 「-」') for h in held))
        self.assertTrue(any(h.startswith('계약기간: 원문에 시작일 또는 종료일이 「-」') for h in held))
        self.assertTrue('이미 맺은 계약' in F['계약(수주)일']['claim'])

    def test_correction_old_contract_table_and_stale_basis(self):
        F, held, T, notes, f = run('supply_contract', SOIL_FIX, '2026-01-14')
        self.assertEqual(F['정정 공시']['claim'], '원래 공시 2023-01-18 · 이 정정 2026-01-14 — 원래 공시 뒤 2년 11개월')
        self.assertEqual(F['회사가 적은 정정사유(원문 그대로)']['claim'], '「계약금액 변경」')
        self.assertEqual(F['계약(수주)일']['claim'], '2021-06-01 — 이 공시보다 4년 7개월 앞서요(새로 맺은 계약이 아니라 이미 맺은 계약에 관한 공시)')
        names = list(F)
        self.assertLess(names.index('정정 공시'), names.index('계약금액'))                 # 정정 사실이 맨 앞
        t = next(x for x in T if x['title'].startswith('정정사항'))
        self.assertEqual(t['rows'][0], ['2. 계약내역 / 계약금액(원)', '1,540,351,481,571', '1,382,746,748,686'])
        self.assertEqual(t['rows'][1], ['2. 계약내역 / 매출액대비(%)', '9.2', '8.2'])
        txt = t['rows'][2][2]
        self.assertIn('실제 공급 실적', txt); self.assertNotIn('추정 공급물량', txt); self.assertNotIn('확정되어 정정공시', txt)   # 본문에 있는 새 문장만
        self.assertTrue(any('매출액 기준(2020년)이 이 공시(2026-01-14)보다 6년 앞서요 — 정정 공시는' in x for x in notes))

    def test_amount_first_disclosed_and_sentence_labels(self):
        F, held, T, notes, f = run('supply_contract', UNHOLD, '2025-12-17')
        self.assertTrue(any(x.startswith('계약금액이 이 정정에서 처음 공개됐어요') for x in notes))
        items = [r[0] for r in next(x for x in T if x['title'].startswith('정정사항'))['rows']]
        self.assertFalse(any(i.startswith('라.') for i in items))                         # 「라. 상기 …임」은 항목이 아님
        self.assertIn("'8. 공시유보 관련내용'의 '유보사유'", items)

    def test_same_day_correction_wording(self):
        h = SHORT.replace('<td>단일판매ㆍ공급계약 체결</td>', doc('정정신고(보고)', '2. 정정관련 공시서류제출일', '2026-06-15', '3. 정정사유', '기재오류',
                                                              '4. 정정사항', '정정항목', '정정전', '정정후', '계약금액(원)', '1', '155,283,839,000', '단일판매ㆍ공급계약 체결'), 1)
        F, *_ = run('supply_contract', h, '2026-06-15')
        self.assertTrue(F['정정 공시']['claim'].endswith('— 원래 공시와 같은 날'))

    def test_cancel_correction_shows_new_sentence(self):
        F, held, T, notes, f = run('supply_cancel', CANCEL_FIX, '2026-07-31')
        self.assertEqual(F['해지금액']['value'], 984880974835)
        self.assertEqual(F['해지일자']['claim'], '2026-04-11')
        self.assertNotIn('계약금액의 1년치', F)
        row = next(x for x in T if x['title'].startswith('정정사항'))['rows'][0]
        self.assertIn('다시 인용(2026.07.31)', row[2]); self.assertNotIn('인용(2026.04.29)되어', row[2])

    def test_chain_follows_correction_of_correction(self):
        a = ('20260413800913', '2026-04-13', {'corrects': None})
        b = ('20260429801233', '2026-04-29', {'corrects': '2026-04-13'})
        c = ('20260731801378', '2026-07-31', {'corrects': '2026-04-29'})                 # 앞선 정정(04-29)을 가리킴
        other = ('20260501800001', '2026-05-01', {'corrects': None})
        g = F4.chain([a, b, c, other])
        self.assertIn(['20260413800913', '20260429801233', '20260731801378'], g)
        self.assertIn(['20260501800001'], g)

    def test_chain_diff_with_history(self):
        old = {'rcept_no': '20260728800266', 'rcept_dt': '2026-07-28', 'url': 'o', 'parsed': {**F4.parse_supply(SHORT), 'amount': 150_000_000_000, 'end': '2026-10-31'}}
        F, held, T, notes, f = run('supply_contract', SHORT, '2026-10-29', history=[old])
        d = next(x for k, x in F.items() if k.startswith('바로 앞 공시(2026-07-28'))
        self.assertIn('(+5,283,839,000원, +3.52%)', d['claim']); self.assertIn('종료일 2026-10-31 → 2026-12-31', d['claim'])
        self.assertTrue(any(x['title'].startswith('같은 계약의 공시 묶음') for x in T))


class Equity(unittest.TestCase):
    def test_already_full_owned_subsidiary(self):
        F, held, T, notes, f = run('equity_deal', SUBSID, '2025-11-05')
        self.assertEqual(F['취득 전 보유 주식·지분']['value'], 100.0)
        self.assertTrue(any('이미 지분 100%를 가진 회사' in x for x in notes))
        self.assertEqual(F['자기자본 대비(공시)']['claim'], '2.41%')
        self.assertTrue(any(x.startswith('자기자본 기준: 2024년 연결') for x in notes))

    def test_put_option_fact(self):
        F, held, T, notes, f = run('equity_deal', PUT, '2026-07-29')
        self.assertIn('매수의무', F['풋옵션 등 계약']['claim'])
        self.assertEqual(F['취득 전 보유 주식·지분']['value'], 0.0)
        self.assertFalse(any('100%' in x for x in notes))

    def test_disposal_before_share(self):
        F, held, T, notes, f = run('equity_deal', SALE, '2026-03-19')
        self.assertEqual(f['parsed']['deal'], '처분')
        self.assertAlmostEqual(F['처분 전 보유 주식·지분']['value'], (86967675 + 1091273) / 5919637922 * 100, places=12)
        self.assertNotIn('풋옵션 등 계약', F)

    def test_major_report_correction_table_stops_at_cover(self):
        F, held, T, notes, f = run('equity_deal_major', MAJOR_FIX, '2026-07-09')
        p = f['parsed']
        self.assertEqual((p['corrects'], p['deal'], p['amount'], p['when']), ('2026-05-27', '양도', 462058340101, '2035-04-15'))
        self.assertEqual(F['거래상대방']['claim'], 'Eli Lilly and Company')
        self.assertEqual(F['총자산 대비(공시)']['claim'], '15.55%')
        self.assertAlmostEqual(F['양도 전 보유 주식·지분']['value'], 21075336 / 91030254 * 100, places=12)
        t = next(x for x in T if x['title'].startswith('정정사항'))
        self.assertEqual(t['cols'], ['항목', '정정사유', '정정 전', '정정 후'])
        self.assertEqual([r[0] for r in t['rows']], ['5. 양도예정일자', '13. 기타 투자판단과 관련한 중요사항'])   # 표지(회사명 …)와 「2027.07.09(목)…」 줄은 항목이 아님
        self.assertEqual(t['rows'][0][2:], ['2026년 08월 24일', '2035년 04월 15일'])
        self.assertIn('Milestone Payment', t['rows'][0][1])
        self.assertEqual(t['rows'][1][1:3], ['양도예정일자 정정', '(문구)'])                 # 문구 항목도 짧은 첫 칸(정정사유)은 보임


class Wiring(unittest.TestCase):
    def test_titles_and_kinds(self):
        for nm, k in (('[기재정정]단일판매ㆍ공급계약체결(자율공시)', 'supply_contract'), ('단일판매ㆍ공급계약해지', 'supply_cancel'),
                      ('주요사항보고서(타법인주식및출자증권양수결정)', 'equity_deal_major'), ('타법인주식및출자증권처분결정(자율공시)', 'equity_deal'),
                      ('타법인주식및출자증권취득결정(자회사의주요경영사항)', None), ('자기주식취득결정', 'buyback_decision')):
            self.assertEqual(D.classify(nm), k, nm)
        for k in F4.KINDS:
            self.assertIn(k, FL.KINDS); self.assertIn(k, FL.KIND_LABEL); self.assertIn(k, D.KIND_LABEL)
        self.assertEqual(G.classify('단일판매ㆍ공급계약체결')['grade'], 2)                    # 화면의 등급 표시는 그대로(2등급)

    def test_auto_docs_skips_only_grade3(self):
        src = inspect.getsource(AC.auto_docs)
        self.assertIn("['grade'] == 3", src); self.assertNotIn("['grade'] != 1", src)


if __name__ == '__main__':
    unittest.main()
