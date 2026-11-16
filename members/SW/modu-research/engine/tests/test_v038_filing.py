"""v0.38 T1 공시 1건 숫자로 보기 — 원문 읽기(4종) · 계산 · 카드 · 확인서 · 막는 경우."""
import io, json, os, tempfile, unittest, zipfile
from pathlib import Path
from mrn import dartdocs as D, filing as FL
from mrn.easy import plan, CARDS, CARD
from tests.test_easy import EasyBase, CUT

CO = '042700'


def html(rows, title='한미반도체/공시/(2026.01.01)공시'):
    tr = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows)
    return f'<html><head><title>{title}</title><style>.x{{}}</style></head><body><table>{tr}</table></body></html>'


RETIRE = html([['1. 소각할 주식의 종류와 수', '보통주식', '1,000,000', '종류주식', '-'], ['2. 발행주식 총수', '보통주식', '100,000,000', '종류주식', '-'],
               ['3. 1주당 가액(원)', '500'], ['4. 소각예정금액(원)', '50,000,000,000'], ['5. 소각을 위한 자기주식 취득 예정기간', '시작일', '-', '종료일', '-'],
               ['6. 소각할 주식의 취득방법', '기취득 자기주식'], ['7. 소각 예정일', '2026-08-01'], ['8. 자기주식 취득 위탁 투자중개업자', '-'],
               ['9. 이사회결의일(결정일)', '2026-07-20']])
BUY = html([['1. 취득예정주식(주)', '보통주식', '2,000,000', '기타주식', '-'], ['2. 취득예정금액(원)', '보통주식', '40,000,000,000', '기타주식', '-'],
            ['3. 취득예상기간', '시작일', '2026년 07월 21일', '종료일', '2026년 10월 20일'], ['4. 보유예상기간', '시작일', '-', '종료일', '-'],
            ['5. 취득목적', '주주가치 제고'], ['6. 취득방법', '유가증권시장을 통한 장내 직접 취득'], ['9. 취득결정일', '2026년 07월 20일']])


def div(dps, rec, decided, cls='분기배당', total='10,000,000,000'):
    return html([['현금ㆍ현물배당 결정'], ['1. 배당구분', cls], ['2. 배당종류', '현금배당'], ['- 현물자산의 상세내역', '-'],
                 ['3. 1주당 배당금(원)', '보통주식', dps, '종류주식', '-'], ['- 차등배당 여부', '미해당'], ['4. 시가배당률(%)', '보통주식', '1.1', '종류주식', '-'],
                 ['5. 배당금총액(원)', total], ['6. 배당기준일', rec], ['7. 배당금지급 예정일자', '-'], ['8. 주주총회 개최여부', '미개최'],
                 ['9. 주주총회 예정일자', '-'], ['10. 이사회결의일(결정일)', decided]])


PRELIM = html([['영업(잠정)실적(공정공시)'], ['실적기간', '당기실적', '2026-04-01', '~', '2026-06-30'], ['전기실적', '2026-01-01', '~', '2026-03-31'],
               ['전년동기실적', '2025-04-01', '~', '2025-06-30'], ['1. 연결실적내용'], ['단위 : 백만원, %'],
               ['구분', '당기실적', '전기실적', '전기대비', '전년동기실적', '전년동기대비'], ["('26.2Q)", "('26.1Q)", '증감율(%)', '흑자적자전환여부', "('25.2Q)", '증감율(%)', '흑자적자전환여부'],
               ['매출액', '당해실적', '120,000', '100,000', '20.0', '-', '80,000', '50.0', '-'], ['누계실적', '220,000', '-', '-', '-', '150,000', '46.7', '-'],
               ['영업이익', '당해실적', '30,000', '25,000', '20.0', '-', '-5,000', '-', '흑자전환'], ['누계실적', '55,000', '-', '-', '-', '-8,000', '-', '흑자전환']],
              title='한미반도체/연결재무제표기준영업(잠정)실적(공정공시)/(2026.07.14)')

DOCS = {'20260720800001': ('retire', '주식소각결정', RETIRE), '20260720000002': ('buyback_decision', '주요사항보고서(자기주식취득결정)', BUY),
        '20250807800003': ('dividend', '현금ㆍ현물배당결정', div('1,500', '2025-06-30', '2025-08-07')),
        '20260211800004': ('dividend', '현금ㆍ현물배당결정', div('800', '2026-03-07', '2026-02-11', '결산배당')),
        '20260806800005': ('dividend', '현금ㆍ현물배당결정', div('1,800', '2026-06-30', '2026-08-06')),
        '20260806800006': ('dividend', '현금ㆍ현물배당결정(자회사의 주요경영사항)', div('9,999', '2026-06-30', '2026-08-06')),
        '20260714800007': ('prelim', '연결재무제표기준영업(잠정)실적(공정공시)', PRELIM),
        '20261120800008': ('prelim', '연결재무제표기준영업(잠정)실적(공정공시)', PRELIM)}


def make_docs(root):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    man = {'tool': 'mrn.dartdocs', 'tool_version': 1, 'origin': '시험', 'docs': {}, 'listed': {}, 'failed': {}}
    for no, (kind, nm, body) in DOCS.items():
        b = io.BytesIO()
        with zipfile.ZipFile(b, 'w') as z:
            z.writestr(f'{no}.xml', body.encode('utf-8'))
        b = b.getvalue(); (root / f'{no}.zip').write_bytes(b)
        man['docs'][no] = {'ticker': CO, 'corp_code': '00000001', 'name': '한미반도체', 'report_nm': nm, 'rcept_dt': f'{no[:4]}-{no[4:6]}-{no[6:8]}', 'kind': kind,
                           'file': f'{no}.zip', 'bytes': len(b), 'sha256': D._sha(b), 'members': [], 'url': f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={no}'}
    D._save_manifest(root, man)


class Parse(unittest.TestCase):
    def test_four_kinds(self):
        r = FL.parse('retire', RETIRE)
        self.assertEqual((r['qty'], r['shares_total'], r['amount'], r['method']), (1000000, 100000000, 50000000000, '기취득 자기주식'))
        b = FL.parse('buyback_decision', BUY)
        self.assertEqual((b['qty'], b['amount'], b['start'], b['end']), (2000000, 40000000000, '2026-07-21', '2026-10-20'))
        d = FL.parse('dividend', div('1,800', '2026-06-30', '2026-08-06'))
        self.assertEqual((d['dps'], d['yield'], d['total'], d['record_date'], d['div_class']), (1800, 1.1, 10000000000, '2026-06-30', '분기배당'))
        p = FL.parse('prelim', PRELIM)
        self.assertEqual(p['unit'], '백만원')
        self.assertEqual(p['rows']['revenue']['cur'], 120000 * 10**6)
        self.assertEqual(p['rows']['op']['yoy_turn'], '흑자전환'); self.assertEqual(p['rows']['op']['yoy_base'], -5000 * 10**6)
        with self.assertRaises(ValueError):
            FL.parse('valueup', '')

    def test_money_units_and_correction(self):
        self.assertEqual(FL._money('195.25', FL.MONEY_UNIT['조원']), 195_250_000_000_000)
        self.assertIsNone(FL._money('-', 10**6))
        doc = html([['정정신고(보고)'], ['2. 정정관련 공시서류제출일', '2026년 10월 08일']])
        from mrn.promise import tokens
        self.assertEqual(FL.correction_of(tokens(doc)), '2026-10-08')

    def test_compute_has_no_direction_words(self):
        mkt = {'date': '2026-07-17', 'close': 100.0, 'market_cap': 1e13, 'shares': 10**11, 'avg_value_20': 1e10}
        for kind, body in (('retire', RETIRE), ('buyback_decision', BUY), ('prelim', PRELIM)):
            f = {'kind': kind, 'parsed': FL.parse(kind, body), 'report_nm': '연결', 'rcept_dt': '2026-07-20', 'url': 'u', 'rcept_no': 'x', 'history': []}
            F, held, T, notes = FL.compute(f, mkt)
            txt = json.dumps([F, held, T, notes], ensure_ascii=False)
            for w in ('호재', '악재', '매수 추천', '목표주가', '긍정적', '부정적'):
                self.assertNotIn(w, txt, (kind, w))
            self.assertTrue(all(x['kind'] in ('fact_official', 'derived') for x in F))
            self.assertTrue(all(x.get('formula') for x in F if x['kind'] == 'derived'), kind)   # 계산은 식을 늘 함께
        f = {'kind': 'buyback_decision', 'parsed': FL.parse('buyback_decision', BUY), 'report_nm': 'x', 'rcept_dt': '2026-07-20', 'url': 'u', 'rcept_no': 'x'}
        F, _, _, _ = FL.compute(f, mkt)
        v = {x['name']: x['value'] for x in F}
        self.assertAlmostEqual(v['취득 예정 금액 ÷ 시가총액'], 0.4)
        self.assertAlmostEqual(v['취득 예정 주식 ÷ 상장 주식 수'], 0.002)
        self.assertEqual(FL.trading_days('2026-07-21', '2026-10-20'), (61, ''))      # v0.38 T2-5(J27): 평일 66일 − 휴장 5일(8/17·9/24·9/25·10/5·10/9)
        self.assertAlmostEqual(v['하루 평균 매입 필요 금액 ÷ 하루 평균 거래대금'], 4e10 / 61 / 1e10 * 100, places=6)

    def test_market_before_uses_only_days_before_filing(self):
        from datetime import date, timedelta
        rows = [{'trade_date': (date(2026, 6, 20) + timedelta(days=i)).isoformat(), 'close': '100', 'market_cap': '1000', 'trade_value': '5'} for i in range(35)]
        m = FL.market_before(rows, '2026-07-20')
        self.assertEqual(m['date'], '2026-07-19'); self.assertEqual(m['shares'], 10); self.assertEqual(m['avg_value_20'], 5)
        self.assertIsNone(FL.market_before(rows, '2026-06-20'))                              # 공시일 전 시세가 없으면 없음
        self.assertIsNone(FL.market_before(rows[:5], '2026-07-20')['avg_value_20'])          # 20거래일 미만이면 평균을 만들지 않음


class Card(EasyBase):
    def setUp(self):
        super().setUp()
        self.docs = tempfile.TemporaryDirectory(); os.environ['MODU_NODES_DART_DOCS'] = os.path.join(self.docs.name, 'dart_docs')
        make_docs(os.environ['MODU_NODES_DART_DOCS'])

    def tearDown(self):
        os.environ.pop('MODU_NODES_DART_DOCS', None); self.docs.cleanup()
        super().tearDown()

    def run_filing(self, no, cut=CUT, company=CO):
        r = self.c.post('/api/easy/run', json={'card': 'filing', 'company': company, 'cutoff': cut, 'rcept_no': no})
        self.assertEqual(r.status_code, 201, r.text)
        self.wait(r.json()['id'])
        return r.json()['id'], self.c.get(f"/api/easy/answer/{r.json()['id']}").json()

    def test_card_is_hidden_from_card_list_but_runs(self):
        self.assertNotIn('filing', [c['id'] for c in CARDS])
        self.assertNotIn('filing', [c['id'] for c in self.c.get('/api/easy/cards', params={'company': CO}).json()['cards']])
        self.assertIn('filing', CARD)
        self.assertEqual(plan('events', CO, CUT)['meta'], {'card': 'events', 'company': CO, 'ui': 'easy'})   # 다른 카드 확인서 사슬은 그대로

    def test_dividend_end_to_end_with_history_and_receipt(self):
        rid, a = self.run_filing('20260806800005')
        self.assertEqual(a['card'], 'filing'); self.assertEqual(a['card_title'], '이 공시는 숫자로 무엇인가?')
        txt = {i['label']: i['text'] for i in a['items']}
        self.assertEqual(txt['1주당 배당금(보통주)'], '1,800원')
        self.assertIn('1,500원 → 1,800원 (20.00%)', txt['직전 같은 구분 배당 대비'])          # 결산배당(800원)이 아니라 같은 분기배당과
        self.assertIn('1,500원 → 1,800원', txt['1년 전 같은 시기 배당 대비'])
        self.assertNotIn('9,999', json.dumps(a, ensure_ascii=False))                          # 자회사 공시는 비교에 안 씀
        self.assertTrue(any('방향 판단: 하지 않음' in x for x in a['limits']))
        hist = next(t for t in a['tables'] if t['title'].startswith('이 회사의 배당 결정'))
        self.assertEqual([r[3] for r in hist['rows']], ['1,800원', '800원', '1,500원'])
        rc = self.c.get(f'/api/easy/receipt/{rid}').json()
        v = self.c.post('/api/easy/verify', json={'receipt': rc}).json()
        self.assertTrue(v['ok'], v); self.assertEqual(v['matched'], v['total'])
        self.assertEqual(rc['meta']['rcept_no'], '20260806800005')

    def test_same_input_same_numbers_and_share_page(self):
        import html as H
        r1, a1 = self.run_filing('20260720000002'); r2, a2 = self.run_filing('20260720000002')
        self.assertEqual([(i['label'], i['text']) for i in a1['items']], [(i['label'], i['text']) for i in a2['items']])
        self.assertEqual(self.c.get(f'/api/easy/receipt/{r1}').json()['receipt_id'], self.c.get(f'/api/easy/receipt/{r2}').json()['receipt_id'])
        page = self.c.get(f'/api/share/{r1}').text
        for t in a1['limits'] + [i['text'] for i in a1['key']]:
            self.assertIn(H.escape(t, quote=True), page)

    def test_retire_buyback_prelim(self):
        _, a = self.run_filing('20260720800001')
        t = {i['label']: i['text'] for i in a['items']}
        self.assertEqual(t['발행주식 대비 소각 비율'], '1.00%')
        self.assertTrue(any('유통 주식 수는 같습니다' in n for n in a['notices']))
        _, a = self.run_filing('20260720000002')
        t = {i['label']: i['text'] for i in a['items']}
        self.assertIn('취득 예정 금액 ÷ 시가총액', t); self.assertIn('2026-07-21 ~ 2026-10-20', t['취득 예상 기간'])
        _, a = self.run_filing('20260714800007')
        t = {i['label']: i['text'] for i in a['items']}
        self.assertEqual(t['매출액 전년 동기 대비'], '50.00% · 공시 값과 같음')
        self.assertNotIn('영업이익 전년 동기 대비', t)                                         # 적자 → 흑자는 비율을 만들지 않음
        self.assertEqual(t['영업이익률(당기)'], '25.00%')

    def test_refusals_are_held_not_errors(self):
        for no, code in (('20260806800006', 'subsidiary'), ('20261120800008', 'after_cutoff'), ('20990101000000', 'doc_missing'), ('123', 'bad_rcept_no')):
            _, a = self.run_filing(no)
            h = next(h for h in a['held'] if h['node'] == 't15')
            self.assertEqual(h['code'], code, no)
        _, a = self.run_filing('20260806800005', company='005930')
        self.assertEqual(next(h for h in a['held'] if h['node'] == 't15')['code'], 'other_company')

    def test_filings_list_api_skips_subsidiary(self):
        r = self.c.get(f'/api/watch/filings/{CO}').json()
        self.assertEqual(len(r['rows']), 7)
        self.assertEqual(r['rows'][0]['rcept_no'], '20261120800008')                          # 최근 순
        self.assertNotIn('20260806800006', [x['rcept_no'] for x in r['rows']])

    def test_fetch_api_maps_errors(self):
        r = self.c.post('/api/watch/fetch', json={'ticker': CO, 'rcept_no': '20260806800005'})   # 이미 있으면 받지 않고 그대로
        self.assertEqual(r.status_code, 200, r.text); self.assertFalse(r.json()['new']); self.assertTrue(r.json()['computable'])
        self.assertEqual(self.c.post('/api/watch/fetch', json={'ticker': CO, 'rcept_no': 'x'}).status_code, 422)
        old = os.environ.pop('DART_API_KEY', None), os.environ.pop('MODU_NODES_DART_KEY', None)
        try:
            r = self.c.post('/api/watch/fetch', json={'ticker': CO, 'rcept_no': '20260101000000'})
            self.assertEqual(r.status_code, 409); self.assertEqual(r.json()['detail']['code'], 'no_key')
        finally:
            for k, v in zip(('DART_API_KEY', 'MODU_NODES_DART_KEY'), old):
                if v is not None:
                    os.environ[k] = v


OLD5 = html([['영업(잠정)실적(공정공시)'], ['1. 실적내용'], ['단위 : 백만원, %'], ['구분', '당기실적', '전기실적', '전기대비증감율(%)', '전년동기실적', '전년동기대비증감율(%)'],
             ['(-)', '(-)', '(-)'], ['매출액', '당해실적', '1,000', '800', '25.0', '500', '100.0'], ['누계실적', '1,800', '-', '-', '900', '100.0'],
             ['영업이익', '당해실적', '100', '80', '25.0', '50', '100.0'], ['누계실적', '180', '-', '-', '90', '100.0']])
UNITS = html([['영업(잠정)실적(공정공시)'], ['1. 실적내용'], ['단위 : 백만원, %'], ['구분', '당기실적', '전기실적', '전기대비증감율(%)', '전년동기실적', '전년동기대비증감율(%)'],
              ['매출액', '당해실적', '-', '-', '-', '-', '-'], ['누계실적', '-', '-', '-', '-', '-'], ['영업이익', '당해실적', '-', '-', '-', '-', '-'],
              ['구분(단위:대,%)', '당기실적'], ['국내', '61,323']])


class Layouts(unittest.TestCase):
    def test_old_five_column_form_is_not_shifted(self):
        p = FL.parse('prelim', OLD5)
        self.assertEqual(p['layout'], 5)
        r = p['rows']['revenue']
        self.assertEqual((r['cur'], r['prev'], r['yoy_base'], r['yoy_stated'], r['ytd'], r['ytd_prev']), (10**9, 8 * 10**8, 5 * 10**8, 100.0, 18 * 10**8, 9 * 10**8))
        self.assertEqual(FL.parse('prelim', PRELIM)['layout'], 7)

    def test_sales_volume_form_says_so(self):
        p = FL.parse('prelim', UNITS)
        self.assertTrue(p['money_empty']); self.assertTrue(p['units_table'])
        F, held, T, notes = FL.compute({'kind': 'prelim', 'parsed': p, 'report_nm': 'x', 'rcept_dt': '2026-01-03', 'url': 'u', 'rcept_no': 'x'}, None)
        self.assertEqual(F, []); self.assertIn('판매 대수', held[0])


REAL_DOCS = Path(__file__).resolve().parents[2] / '_sources' / 'dart_docs'


def _real_kinds():
    try:
        return {d['kind'] for d in D.load_manifest(REAL_DOCS)['docs'].values()}
    except D.DartDocsError:
        return set()


@unittest.skipUnless({'dividend', 'prelim'} <= _real_kinds(), '이 PC에 배당·잠정실적 DART 원문 사본이 있을 때만')
class RealDocs(unittest.TestCase):
    """실제 원문 전부로(v0.38 T1 재점검): 4종 모두 읽기 누락 0 · 공시 증감률과 다시 계산한 값이 같거나 반올림으로 설명됨."""
    def test_every_own_doc_is_read_or_explained(self):
        import collections
        man = D.load_manifest(REAL_DOCS); n = collections.Counter(); bad = []; chk = collections.Counter()
        for no, d in man['docs'].items():
            if d['kind'] not in FL.KINDS or D.OWN_EXCLUDE.search(d['report_nm']):
                continue
            files, _ = D.open_doc(no, REAL_DOCS, man); p = FL.parse(d['kind'], '\n'.join(t for _, t in files)); n[d['kind']] += 1
            f = {'kind': d['kind'], 'parsed': p, 'report_nm': d['report_nm'], 'rcept_dt': d['rcept_dt'], 'url': '', 'rcept_no': no, 'history': []}
            F, held, T, notes = FL.compute(f, {'date': '2000-01-01', 'close': 1.0, 'market_cap': 1e15, 'shares': 10**15, 'avg_value_20': 1e12})
            if any('읽지 못함' in h for h in held):
                bad.append((no, d['kind']))
            if d['kind'] == 'prelim':
                for r in p['rows'].values():
                    for base, st in ((r.get('yoy_base'), r.get('yoy_stated')), (r.get('prev'), r.get('qoq_stated'))):
                        m = FL._chg(r.get('cur'), base)
                        if m is not None and st is not None:
                            t = FL.stated_check(r['cur'], base, m, st, p['unit'])
                            chk['same' if '같음' in t else 'unit' if '표시 단위' in t else 'check'] += 1
        self.assertEqual(bad, [])
        self.assertGreater(n['dividend'], 20); self.assertGreater(n['prelim'], 50); self.assertGreater(n['retire'], 50)
        total = sum(chk.values())
        self.assertGreater(chk['same'], 0.9 * total)
        self.assertLessEqual(chk['check'], max(2, total // 1000))           # 원문 오기(부호·숫자) 몇 건만 남는다 — 화면에 「원문 확인」으로 보임


KQ = html([['연결재무제표 기준 영업(잠정)실적(공정공시)'], ['1. 연결실적내용'], ['구분(단위 : 백만원, %)', '당기실적', '전기실적', '전기대비증감액(증감율)', '전년동기실적', '전년동기대비증감액(증감율)'],
           ['(25년1분기)', '(24년4분기)', '(24년1분기)'], ['매출액', '당해실적', '120,846', '108,285', '12,561', '(+11.6%)', '56,571', '64,275', '(+113.6%)'],
           ['누계실적', '120,846', '-', '-', '56,571', '64,275', '(+113.6%)'], ['영업이익', '당해실적', '33,908', '1,932', '31,976', '(+1,655.1%)', '7,030', '26,878', '(+382.3%)']])
MONTHLY = html([['영업(잠정)실적(공정공시)'], ['1. 실적내용'], ['단위 : 백만원, %'], ['구분', '당기실적', '전기실적', '전기대비증감율(%)', '전년동기실적', '전년동기대비증감율(%)'],
                ['(2024년12월)', '(2024년11월)', '(2023년12월)'], ['매출액', '당해실적', '201,171', '170,902', '17.71', '190,320', '5.70'],
                ['영업이익', '당해실적', '-', '-', '-', '-', '-']])
RETIRE_PREF = html([['1. 소각할 주식의 종류와 수', '보통주식 (주)', '-', '종류주식 (주)', '156,425'], ['2. 발행주식 총수', '보통주식 (주)', '70,507,919', '종류주식 (주)', '19,603,474'],
                    ['4. 소각예정금액(원)', '11,121,817,500'], ['6. 소각할 주식의 취득방법', '기취득 자기주식']])
RETIRE_CORR = html([['정정신고(보고)'], ['1. 소각할 주식의 종류와 수', '/보통주식(주)', '156,957', '-'], ['2. 발행주식 총수', '/보통주식(주)', '100,249,166', '-'], ['4. 소각예정금액(원)', '7,163,924,130', '-']])
BUY_DASH = html([['1. 취득예정주식(주)', '보통주식', '546,120', '기타주식', '-'], ['2. 취득예정금액(원)', '보통주식', '-', '기타주식', '-'], ['3. 취득예상기간', '시작일', '2026년 03월 16일', '종료일', '2026년 04월 13일']])


class Recheck(unittest.TestCase):
    """v0.38 T1 재점검에서 실제 원문으로 찾은 서식들."""
    def comp(self, kind, body, report_nm='x', mkt=None):
        f = {'kind': kind, 'parsed': FL.parse(kind, body), 'report_nm': report_nm, 'rcept_dt': '2026-05-14', 'url': 'u', 'rcept_no': 'x', 'history': []}
        F, held, T, notes = FL.compute(f, mkt or {'date': '2026-05-13', 'close': 100.0, 'market_cap': 1e13, 'shares': 10**11, 'avg_value_20': 1e10})
        return {x['name']: x['claim'] for x in F}, held, T, notes

    def test_kosdaq_prelim_form(self):
        p = FL.parse('prelim', KQ)
        self.assertEqual(p['layout'], 'kq'); self.assertEqual(p['unit'], '백만원')
        r = p['rows']['revenue']
        self.assertEqual((r['cur'], r['prev'], r['qoq_stated'], r['yoy_base'], r['yoy_stated'], r['ytd'], r['ytd_prev']),
                         (120846 * 10**6, 108285 * 10**6, 11.6, 56571 * 10**6, 113.6, 120846 * 10**6, 56571 * 10**6))
        self.assertEqual(p['rows']['op']['qoq_stated'], 1655.1)
        c, *_ = self.comp('prelim', KQ, '연결재무제표기준영업(잠정)실적(공정공시)')
        self.assertIn('같음', c['매출액 직전 분기 대비']); self.assertIn('같음', c['영업이익 직전 분기 대비'])

    def test_monthly_prelim_names_months(self):
        c, held, T, _ = self.comp('prelim', MONTHLY)
        self.assertIn('매출액 (2024년12월, 회사 기준(별도 등 — 원문 4항 확인))', c)
        self.assertIn('매출액 직전 달 대비', c); self.assertNotIn('매출액 직전 분기 대비', c)
        self.assertEqual(T[0]['cols'][1:3], ['당기 (2024년12월)', '직전 달 (2024년11월)'])

    def test_preferred_only_and_correction_and_dash(self):
        c, held, _, notes = self.comp('retire', RETIRE_PREF)
        self.assertEqual(c['소각할 주식 수'], '보통주 없음 · 종류주 156,425주')
        self.assertIn('종류주 발행주식 대비 소각 비율', c); self.assertNotIn('소각 예정 금액 ÷ 시가총액', c)
        self.assertEqual(held, []); self.assertTrue(any('종류주' in n for n in notes))
        c, held, _, _ = self.comp('retire', RETIRE_CORR)
        self.assertEqual(c['발행주식 대비 소각 비율'], '0.16%')
        c, held, _, _ = self.comp('buyback_decision', BUY_DASH)
        self.assertTrue(any('「-」로 적혀 있음' in h for h in held)); self.assertFalse(any('읽지 못함' in h for h in held))
        d = FL.parse('dividend', div('1,139.61', '2026-03-31', '2026-02-25'))
        self.assertEqual(d['dps'], 1139.61)
        c, held, _, notes = self.comp('dividend', html([['3. 1주당 배당금(원)', '보통주식', '-', '종류주식', '25'], ['1. 배당구분', '결산배당']]))
        self.assertEqual(c['1주당 배당금'], '보통주 없음 · 종류주 25원'); self.assertFalse(any('읽지 못함' in h for h in held))

    def test_small_ratio_and_reversed_period(self):
        self.assertEqual(FL._p(FL._pct(1, 158363408)), '0.01% 미만')
        body = BUY.replace('2026년 10월 20일', '2026년 02월 10일').replace('2026년 07월 21일', '2026년 11월 11일')
        c, held, _, _ = self.comp('buyback_decision', body)
        self.assertIn('종료일이 시작일보다 앞섬', c['취득 예상 기간'])
        self.assertTrue(any('거래일 수를 셀 수 없음' in h for h in held))

    def test_stated_check_wording(self):
        M = 10**6                                                           # 금액은 원 단위로 넘긴다
        self.assertEqual(FL.stated_check(100 * M, 50 * M, 100.0, 100.0, '백만원'), ' · 공시 값과 같음')
        self.assertIn('정수로 반올림', FL.stated_check(1148 * M, 1000 * M, 14.8, 15.0, '백만원'))
        self.assertIn('표의 표시 단위', FL.stated_check(120 * M, 3 * M, 3900.0, 3800.0, '백만원'))
        self.assertIn('원문 표를 직접 확인', FL.stated_check(42421 * M, 23137 * M, 83.35, 770.2, '백만원'))
