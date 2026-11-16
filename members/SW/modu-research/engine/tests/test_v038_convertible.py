"""v0.38 T2-3 전환사채·신주인수권부사채·교환사채 발행 결정(결정 3): 원문 읽기 · 최대 희석 · 교환사채 · 리픽싱 조건 · 지난 조정일 다시 계산 · 시나리오 표 · 시장 대비 확률 · 실제 원문 전부."""
import json, unittest
from datetime import date, timedelta
from pathlib import Path
from mrn import dartdocs as D, filing as FL, filing3 as F3, prob as PB
from tests.test_v038_filing import html
from tests.test_v038_prob import fake

REAL_DOCS = Path(__file__).resolve().parents[2] / '_sources' / 'dart_docs'
SAMPLES = Path(__file__).resolve().parents[2] / '_sources' / 'dart_docs_samples'
REFIX = ('(4) 위 (1) 내지 (3)과는 별도로 본 사채 발행 후 매 3개월이 경과한 날을 전환가액 조정일로 하고, 각 전환가액 조정일 전일을 기산일로 하여 그 기산일로부터 소급한 1개월 가중산술평균주가, '
         '1주일 가중산술평균주가 및 최근일 가중산술평균주가를 산술평균한 가액과 최근일 가중산술평균주가 중 높은 가액이 직전 전환가액보다 낮은 경우 그 가액으로 조정한다. 단, 발행당시 전환가액의 70% 이상으로 한다.')


def cb(kind='CB', face='10,000,000,000', price='5,000', shares='2,000,000', pct=('10',), floor='3,500', basis=('발행당시 전환가액의 70%',), refix=REFIX, pay='2026년 01월 05일',
       eb_target='주식회사 가나 기명식 보통주(자기주식)', corr=None, call=False, ytm='3'):
    word = {'CB': ('전환', '전환가액', '전환청구기간', '전환사채권'), 'BW': ('행사', '행사가액', '권리행사기간', '신주인수권부사채권'), 'EB': ('교환', '교환가액', '교환청구기간', '교환사채권')}[kind]
    head = {'CB': '9. 전환에 관한 사항', 'BW': '9. 신주인수권에 관한 사항', 'EB': '9. 교환에 관한 사항'}[kind]
    r = [[f'주요사항보고서({word[3]} 발행결정)']]
    if corr:
        r += [['정정신고(보고)'], ['2. 정정대상 공시서류의 최초제출일 :', corr[0]], ['3. 정정사항'], ['항목', '정정사유', '정정전', '정정후'], ['9. 전환가액', corr[1], '-', '-']]
    r += [[f'{word[3]} 발행결정'], ['1. 사채의 종류', '회차', '3', '종류', '무기명식 이권부 무보증 사모 사채'], ['2. 사채의 권면(전자등록)총액 (원)', face],
          ['3. 자금조달의 목적', '시설자금 (원)', '-', '운영자금 (원)', face, '채무상환자금 (원)', '-'], ['4. 사채의 이율', '표면이자율 (%)', '0', '만기이자율 (%)', ytm],
          ['5. 사채만기일', '2029년 01월 05일'], ['8. 사채발행방법', '사모'], [head], [f'{word[0]}비율 (%)', '100'], [f'{word[1]} (원/주)', price], [f'{word[1]} 결정방법', '기준주가의 100%'],
          ['종류', eb_target if kind == 'EB' else '주식회사 가나 기명식 보통주'], ['주식수', shares], ['주식총수 대비비율(%)', *pct], [word[2], '시작일', '2027년 01월 05일', '종료일', '2028년 12월 05일'],
          [f'{word[1]} 조정에 관한 사항', '(1) 시가를 하회하는 발행가액으로 유상증자를 하는 경우 조정한다.'], [refix]]
    if kind != 'EB':
        r += [[f'시가하락에따른{word[1]}조정'], ['최저 조정가액 (원)', floor], ['최저 조정가액 근거', *basis]]
    r += [['9-1. 옵션에 관한 사항', ('매도청구권(Call Option): 발행회사 또는 발행회사가 지정하는 자는 사채 권면총액의 30%에 해당하는 사채를 매수할 수 있다.' if call else '조기상환청구권(Put Option): 발행일 후 1년부터 매 3개월')],
          ['10. 합병 관련 사항', '-'], ['11. 청약일', '2026년 01월 05일'], ['12. 납입일', pay], ['17. 이사회결의일(결정일)', '2025년 12월 29일']]
    return html(r)


def run(doc, mkt=None, history=(), prices=None, rcept='2025-12-29', ticker='000010'):
    f = {'kind': 'convertible', 'parsed': F3.parse_convertible(doc), 'report_nm': '주요사항보고서', 'rcept_dt': rcept, 'url': '', 'rcept_no': '20251229000001', 'history': list(history), 'newer': []}
    F, held, T, notes = FL.compute(json.loads(json.dumps(f)), mkt, prices=prices, ticker=ticker)
    return {x['name']: x for x in F}, held, notes, T


def days(start='2025-01-01', n=320):
    d = date.fromisoformat(start); out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def px(levels, upto):
    out = []
    for d in days():
        if d > upto:
            break
        c = [v for s, v in levels if s <= d][-1]
        out.append({'trade_date': d, 'close': c, 'volume': 1000, 'trade_value': c * 1000, 'market_cap': c * 18_000_000})
    return out


MK = {'date': '2025-12-26', 'close': 4000.0, 'market_cap': 4000.0 * 18_000_000, 'shares': 18_000_000}


class Parse(unittest.TestCase):
    def test_cb_fields_and_split_cells(self):
        p = F3.parse_convertible(cb(pct=('1', '0.2'), basis=('「증권의 발행 및 공시 등에 관한 규정」 제5-23조에 따른 발행당시 전환가액의 100분의', '70', '에 해당하는 가액')))
        self.assertEqual((p['bond'], p['face'], p['price'], p['shares'], p['share_pct'], p['floor'], p['floor_pct_text']), ('CB', 10**10, 5000, 2_000_000, 10.2, 3500, 70.0))
        self.assertEqual((p['coupon'], p['ytm'], p['maturity'], p['pay_date'], p['period']), (0.0, 3.0, '2029-01-05', '2026-01-05', ['2027-01-05', '2028-12-05']))
        r = p['refix']; self.assertEqual((r['months'], r['standard_base'], r['up'], r['dates']), (3, True, False, []))
        self.assertEqual(p['funds']['operating'], 10**10)

    def test_refix_text_forms(self):
        t = F3.refix_terms
        self.assertEqual(t('본건사채의 발행후 매[6]개월이 되는 날을 전환가격조정일로 하고 1개월 가중산술평균주가, 1주일 가중산술평균주가')['months'], 6)
        r = t('본사채발행일로부터 매5개월이 경과한 날(2026년1월8일, 2026년6월8일, 2026년11월8일)을 전환가액 조정일로 하고 1개월 1주일')
        self.assertEqual((r['months'], r['dates']), (5, ['2026-01-08', '2026-06-08', '2026-11-08']))
        r = t('본 사채 발행일로부터 1년이 경과한 날부터 매3개월이 되는 날마다 전환가격조정일로 하고 1개월 1주일. 시가산정가액이 높은 경우에는 동 높은 가액을 새로운 전환가액으로 한다. 단 최초 전환가액 이내')
        self.assertEqual((r['months'], r['start_years'], r['up']), (3, 1, True))
        self.assertIsNone(t('이자는 매 3개월마다 연 표면금리의 1/4씩 후급한다.')['months'])
        self.assertTrue(t('(5) 시가하락에 따른 조정 : 없음')['none'])
        r = t('(2019년 12월 02일, 2020년 03월 02일, 2020년 06월 02일, 이하 "행사가액조정일")마다 행사가액을 조정하되 1개월 가중산술평균주가, 1주일 가중산술평균주가')
        self.assertEqual(r['dates'], ['2019-12-02', '2020-03-02', '2020-06-02']); self.assertTrue(r['standard_base'])

    def test_kinds_eb_target_and_dates(self):
        self.assertEqual(F3.parse_convertible(cb('BW'))['bond'], 'BW'); self.assertEqual(F3.parse_convertible(cb('BW'))['shares'], 2_000_000)
        p = F3.parse_convertible(cb('EB')); self.assertEqual((p['bond'], p['eb_own']), ('EB', True))
        self.assertFalse(F3.parse_convertible(cb('EB', eb_target='주식회사 다라 기명식 보통주'))['eb_own'])
        self.assertEqual(F3.refix_dates({'refix': {'months': 3, 'days': 0, 'dates': []}, 'pay_date': '2026-01-31', 'maturity': '2026-12-01'}, '2027-12-31'), ['2026-04-30', '2026-07-31', '2026-10-31'])
        self.assertEqual(F3.refix_dates({'refix': {'months': 3, 'days': 0, 'dates': [], 'start_years': 1}, 'pay_date': '2026-01-05'}, '2027-08-01'), ['2027-01-05', '2027-04-05', '2027-07-05'])


class Compute(unittest.TestCase):
    def test_dilution_by_hand(self):
        F, held, notes, T = run(cb(), MK)
        self.assertIn('2,000,000주 · 공시 값과 같음', F['전환하면 새로 생기는 주식 수(최대, 가정)']['claim'])
        self.assertEqual(F['모두 전환하면 기존 주주 지분이 줄어드는 정도(가정)']['value'], 10.0)
        self.assertIn('증자 뒤 주식 수 기준', F['새로 생기는 주식 수 ÷ 상장 주식 수']['claim'])
        self.assertEqual(F['전환가액 ÷ 종가']['value'], 25.0)
        self.assertEqual(F['최저 조정가액까지 내려가면 생기는 주식 수(최대, 가정)']['value'], 2_857_142); self.assertIn('+857,142주', F['최저 조정가액까지 내려가면 생기는 주식 수(최대, 가정)']['claim'])
        self.assertEqual(F['최저 조정가액에서 모두 전환하면 기존 주주 지분이 줄어드는 정도(가정)']['value'], round(2_857_142 / 20_857_142 * 100, 4))
        self.assertIn('매 3개월 · 내리는 쪽으로만 조정', F['전환가액 조정 주기(원문 글)']['claim'])
        self.assertEqual(F['자금 목적 합계와 사채 금액의 대조']['claim'], '같음')

    def test_share_check_rounding(self):
        self.assertEqual(F3._share_check(877_822, 877_820), ' · 공시 값 877,820주와 같음(사채권자별로 1주 미만을 버려 생기는 작은 차이 -2주)')
        self.assertIn('다름 — 원문을', F3._share_check(120_798, 63_025)); self.assertEqual(F3._share_check(10, 11), ' · 공시 값과 같음')

    def test_bw_and_eb(self):
        F, held, notes, T = run(cb('BW'), MK)
        self.assertIn('행사하면 새로 생기는 주식 수(최대, 가정)', F); self.assertIn('행사가액 조정 주기(원문 글)', F)
        self.assertFalse(any('신주인수권하면' in k or '가액가 ' in v['claim'] for k, v in F.items()))
        F, held, notes, T = run(cb('EB'), MK)
        self.assertNotIn('교환하면 새로 생기는 주식 수(최대, 가정)', F); self.assertNotIn('최저 조정가액(원문 표)', F)
        self.assertIn('2,000,000주 — 상장 주식 수의 11.11%', F['시장으로 나갈 수 있는 자기주식']['claim']); self.assertTrue(any('자기주식이 시장으로 나가' in x for x in notes))
        F, held, notes, T = run(cb('EB', eb_target='주식회사 다라 기명식 보통주'), MK)
        self.assertNotIn('시장으로 나갈 수 있는 자기주식', F); self.assertTrue(any('주식 수는 바뀌지 않습니다' in x for x in notes))

    def test_no_refix_withdrawn_and_call(self):
        F, held, notes, T = run(cb(floor='-', basis=('-',), refix='(5) 시가하락에 따른 조정 : 없음'), MK)
        self.assertTrue(any('리픽싱) 조건이 없는 사채' in x for x in notes)); self.assertFalse(T)
        F, held, notes, T = run(cb(floor='-', basis=('-',)), MK)
        self.assertTrue(any('최저 조정가액 칸이 비어 있어' in h for h in held))
        F, held, notes, T = run(cb(face='-', price='-', shares='-', corr=('2025.10.15', '발행대상자 납입의무 미이행에 따른 전환사채권 발행결정 철회')), MK)
        self.assertTrue(any('발행 결정을 거둔 공시일 수 있으니' in h for h in held)); self.assertTrue(any('철회' in x for x in notes))
        F, held, notes, T = run(cb(call=True), MK)
        self.assertIn('30%', F['콜옵션(매도청구권) 원문 일부']['claim']); self.assertTrue(any('최대 희석 계산은 바뀌지 않습니다' in x for x in notes))

    def test_scenario_table_by_hand(self):
        F, held, notes, T = run(cb(), MK, prices=px([('2025-01-01', 4000)], '2025-12-29'))
        t = next(x for x in T if x['title'].startswith('전환가액 조정 시나리오'))
        R = {r[0]: r for r in t['rows']}
        self.assertEqual(R['지금 수준'][1:], ['4,000원', '4,000원', '2,500,000주', '+500,000주', '12.20%'])
        self.assertEqual(R['-20%'][1:4], ['3,200원', '3,500원 (최저)', '2,857,142주'])
        self.assertEqual(R['+20%'][1:4], ['4,800원', '4,800원', '2,083,333주'])
        self.assertIn('지금 전환가액(5,000원, 원문 표) 대비', t['cols'])

    def test_past_refix_from_prices_and_up_rule(self):              # 발행 2025-09-01, 매 3개월 → 12-01 조정일. 주가 4,000 → 4,000원으로 조정됨
        F, held, notes, T = run(cb(pay='2025년 09월 01일'), MK, prices=px([('2025-01-01', 4000)], '2025-12-29'))
        self.assertIn('2025-12-01 4,000원', F['지난 조정일의 전환가액(시세로 다시 계산)']['claim'])
        t = next(x for x in T if x['title'].startswith('전환가액 조정 시나리오'))
        self.assertIn('지금 전환가액(4,000원, 시세로 다시 계산) 대비', t['cols'])
        self.assertEqual({r[0]: r for r in t['rows']}['+20%'][2], '4,000원')                                       # 내리는 쪽으로만
        up = cb(pay='2025년 09월 01일', refix=REFIX + ' 시가산정가액이 높은 경우에는 동 높은 가액을 새로운 전환가액으로 한다. 단, 최초 전환가액 이내로 한다.')
        F, held, notes, T = run(up, MK, prices=px([('2025-01-01', 4000)], '2025-12-29'))
        R = {r[0]: r for r in next(x for x in T if x['title'].startswith('전환가액 조정 시나리오'))['rows']}
        self.assertEqual((R['+20%'][2], R['-20%'][2]), ('4,800원', '3,500원 (최저)'))
        self.assertIn('시가가 오르면 최초 가액까지 다시 올림', F['전환가액 조정 주기(원문 글)']['claim'])


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
        return [{'trade_date': d, 'close': c, 'volume': 1000, 'trade_value': c * 1000, 'market_cap': c * 18_000_000} for d, c in self.S['000010'] if d <= upto]

    def setup_doc(self, **kw):
        L = self.D[300]; P0 = self.S['000010'][300][1]
        f = lambda d: f'{d[:4]}년 {d[5:7]}월 {d[8:]}일'
        doc = cb(price=f'{int(P0):,}', shares=f'{10**10 // int(P0):,}', floor=f'{int(P0 * 0.7):,}', pay=f(self.D[280]), **kw)
        return doc, L, {'date': L, 'close': P0, 'market_cap': P0 * 18e6, 'shares': 18_000_000}

    def test_market_scenarios(self):
        doc, L, mk = self.setup_doc()
        F, held, notes, T = run(doc, mk, prices=self.rows(L), rcept=L)
        E = {k: v for k, v in F.items() if k.startswith('전환가액 조정 추정')}
        self.assertEqual(len(E), 3, held); self.assertTrue(all(v['kind'] == 'forecast_model' for v in E.values()))
        lo, mid, hi = (E[f'전환가액 조정 추정 — 시장 전체가 {x}']['value'] for x in ('10% 내릴 때', '제자리일 때', '10% 오를 때'))
        self.assertTrue(lo >= mid >= hi, (lo, mid, hi))
        c = E['전환가액 조정 추정 — 시장 전체가 제자리일 때']
        self.assertRegex(c['claim'], r'전환가액이 지금\([\d,]+원\)보다 내려갈 확률 (약 \d0%|\d+% 미만|\d+% 넘음)'); self.assertIn('과거 검증', c['formula'])
        self.assertEqual(run(doc, mk, prices=self.rows(L), rcept=L)[0]['전환가액 조정 추정 — 시장 전체가 제자리일 때']['claim'], c['claim'])      # 난수 없음
        t = next(x for x in T if x['title'].startswith('전환가액 조정 추정')); self.assertEqual(len(t['rows']), 3)

    def test_unknown_company_or_unread_rule_held(self):
        doc, L, mk = self.setup_doc()
        F, held, notes, T = run(doc, mk, prices=self.rows(L), rcept=L, ticker='999999')
        self.assertTrue(any('변동성(또는 과거 경로)을 구하지 못해' in h for h in held))
        doc, L, mk = self.setup_doc(refix='시가하락 시 전환가액을 조정한다.')
        F, held, notes, T = run(doc, mk, prices=self.rows(L), rcept=L)
        self.assertTrue(any('조정일·시가 산식을 원문에서 읽지 못했거나' in h for h in held)); self.assertTrue(any(x['title'].startswith('전환가액 조정 시나리오') for x in T))


class Card(__import__('tests.test_easy', fromlist=['EasyBase']).EasyBase):
    """카드 한 장으로 끝까지: 원문 사본 → T15 → T06 시세 → N20 → 답 → 확인서 다시 계산."""
    NO = '20261005800002'

    def setUp(self):
        import io, os, tempfile, zipfile
        super().setUp()
        self.docs = tempfile.TemporaryDirectory(); root = Path(self.docs.name) / 'dart_docs'; root.mkdir(parents=True)
        os.environ['MODU_NODES_DART_DOCS'] = str(root)
        b = io.BytesIO()
        with zipfile.ZipFile(b, 'w') as z:
            z.writestr(f'{self.NO}.xml', cb(pay='2026년 06월 01일').encode('utf-8'))
        b = b.getvalue(); (root / f'{self.NO}.zip').write_bytes(b)
        D._save_manifest(root, {'tool': 'mrn.dartdocs', 'tool_version': 1, 'origin': '시험', 'listed': {}, 'failed': {}, 'docs': {self.NO: {
            'ticker': '042700', 'corp_code': '00000001', 'name': '한미반도체', 'report_nm': '주요사항보고서(전환사채권발행결정)', 'rcept_dt': '2026-10-05', 'kind': 'convertible',
            'file': f'{self.NO}.zip', 'bytes': len(b), 'sha256': D._sha(b), 'members': [], 'url': 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' + self.NO}}})

    def tearDown(self):
        import os
        os.environ.pop('MODU_NODES_DART_DOCS', None); self.docs.cleanup()
        super().tearDown()

    def test_end_to_end_with_receipt(self):
        r = self.c.post('/api/easy/run', json={'card': 'filing', 'company': '042700', 'cutoff': '2026-10-20T16:00:00+09:00', 'rcept_no': self.NO})
        self.assertEqual(r.status_code, 201, r.text); rid = r.json()['id']; self.wait(rid)
        a = self.c.get(f'/api/easy/answer/{rid}').json(); txt = {i['label']: i['text'] for i in a['items']}; js = json.dumps(a, ensure_ascii=False)
        self.assertIn('2,000,000주 · 공시 값과 같음', txt['전환하면 새로 생기는 주식 수(최대, 가정)']); self.assertIn('최저 조정가액(원문 표)', txt)
        self.assertIn('전환가액 조정 시나리오', js)
        self.assertNotIn('호재', js.replace('호재·악재 같은 방향 판단: 하지 않음', ''))
        rc = self.c.get(f'/api/easy/receipt/{rid}').json()
        v = self.c.post('/api/easy/verify', json={'receipt': rc}).json()
        self.assertTrue(v['ok'], v); self.assertEqual(v['matched'], v['total'])


def _docs():
    out, seen = [], set()
    for root in (SAMPLES, REAL_DOCS):
        if (root / 'manifest.json').is_file():
            man = D.load_manifest(root)
            for no, d in sorted(man['docs'].items()):
                if d['kind'] == 'convertible' and no not in seen:
                    seen.add(no); out.append((no, root, man))
    return out


@unittest.skipUnless(len(_docs()) >= 100, '이 PC에 전환사채류 원문(표본 + 근거 사본)이 100건 이상 있을 때만')
class RealDocs(unittest.TestCase):
    def test_all_parse_compute_and_checks(self):
        kinds, n, diff, refix = {}, 0, 0, 0
        for no, root, man in _docs():
            d = man['docs'][no]
            doc = '\n'.join(t for _, t in D.open_doc(no, root, man)[0])
            p = F3.parse_convertible(doc); self.assertEqual(p, F3.parse_convertible(doc, d['report_nm']), no)
            kinds[p['bond']] = kinds.get(p['bond'], 0) + 1; n += 1
            f = {'kind': 'convertible', 'parsed': p, 'report_nm': d['report_nm'], 'rcept_dt': d['rcept_dt'], 'url': '', 'rcept_no': no, 'history': [], 'newer': []}
            F, held, T, notes = FL.compute(json.loads(json.dumps(f)), None)
            diff += any('주식 수' in x['name'] and '다름' in x['claim'] for x in F)
            refix += bool(p['floor'] and (p['refix']['months'] or p['refix']['dates']))
        self.assertGreaterEqual(n, 400); self.assertGreaterEqual(kinds.get('EB', 0), 30); self.assertGreaterEqual(kinds.get('BW', 0), 10)
        self.assertLessEqual(diff, n // 50, diff); self.assertGreaterEqual(refix, 240)


if __name__ == '__main__':
    unittest.main()
