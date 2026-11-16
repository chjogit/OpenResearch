"""v0.14: 키트 2(T11·N01·N05·N06 회사 확장) · T08/N11/N12 사건 · T12/N13 지분 · N14 수출 조기 확인."""
import json, os, tempfile, unittest
from mrn import market
from mrn import nodes as N
from mrn.engine import Engine
from mrn.store import Store
from mrn.workflow import WorkflowDoc, validate, blocking, topo_order
from tests.test_universe import make_v3, _w, _h, CUT

CO = '042700'


def add_tables(d):
    mp = os.path.join(d, 'manifest.json')
    with open(mp, encoding='utf-8') as f:
        man = json.load(f)
    T = man['tables']

    def part(table, rows_by_ticker):
        parts, total = {}, 0
        for t, rows in rows_by_ticker.items():
            f = f'{table}/{t}.jsonl'
            h, n = _w(os.path.join(d, f), rows)
            parts[t] = {'file': f, 'rows': n, 'sha256': h}
            total += n
        T[table] = {'partitioned': True, 'parts': parts, 'rows': total, 'source_grade': 'test', 'query': 't', 'note': ''}

    def single(table, rows):
        h, n = _w(os.path.join(d, table + '.jsonl'), rows)
        T[table] = {'file': table + '.jsonl', 'rows': n, 'sha256': h, 'source_grade': 'test', 'query': 't', 'note': ''}

    ff = []
    for y, rc, rev, op in ((2024, '20250310000001', 500000000000, 200000000000), (2025, '20260310000001', 600000000000, 250000000000),
                           (2026, '20270310000001', 999000000000, 1)):           # 2026 사업보고서는 기준시점 뒤 → 빠져야 함
        for fs, mult in (('CFS', 1), ('OFS', 0.5)):
            ff += [{'ticker': CO, 'fiscal_year': y, 'report_code': '11011', 'fs_div': fs, 'sj_div': 'IS', 'account_id': 'ifrs-full_Revenue', 'account_nm': '매출액',
                    'amount': str(int(rev * mult)), 'currency': 'KRW', 'rcept_no': rc, 'period_end': f'{y}-12-31'},
                   {'ticker': CO, 'fiscal_year': y, 'report_code': '11011', 'fs_div': fs, 'sj_div': 'IS', 'account_id': 'dart_OperatingIncomeLoss', 'account_nm': '영업이익',
                    'amount': str(int(op * mult)), 'currency': 'KRW', 'rcept_no': rc, 'period_end': f'{y}-12-31'}]
    part('financial_fact', {CO: ff})
    part('report_exposure', {CO: [
        {'ticker': CO, 'fiscal_year': 2025, 'rcept_no': '20260310000001', 'metric': 'fx_sens', 'currency': 'USD', 'value': '10000000000', 'change_pct': '10', 'basis': '세전이익', 'unit_raw': '백만원', 'evidence': '환율 10% 변동 시'},
        {'ticker': CO, 'fiscal_year': 2025, 'rcept_no': '20260310000001', 'metric': 'fx_sens', 'currency': 'EUR', 'value': '100000000', 'change_pct': '10', 'basis': '세전이익', 'unit_raw': '백만원', 'evidence': ''},
        {'ticker': CO, 'fiscal_year': 2025, 'rcept_no': '20260310000001', 'metric': 'ir_sens', 'currency': 'KRW', 'value': '-2000000000', 'change_pct': '100', 'basis': '세전이익', 'unit_raw': '백만원', 'evidence': '100bp'}]})
    dis = [{'ticker': CO, 'rcept_no': f'2026{m:02d}15{i:06d}', 'report_nm': nm, 'rcept_dt': f'2026-{m:02d}-15', 'filer': 'x', 'category': 'I', 'event_type': None, 'url': 'u'}
           for i, (m, nm) in enumerate([(7, '연결재무제표기준영업(잠정)실적(공정공시)'), (8, '임원ㆍ주요주주특정증권등소유상황보고서'), (9, '단일판매ㆍ공급계약체결'),
                                        (10, '현금ㆍ현물배당결정'), (12, '유상증자결정')])]          # 12월은 기준시점 뒤
    part('disclosure', {CO: dis})
    part('news_title', {CO: [{'ticker': CO, 'doc_id': i, 'source': src, 'title': t, 'url': f'n{i}', 'published_at': d, 'score': None}
                             for i, (d, t, src) in enumerate([('2026-10-20', '한미반도체, 신고가 [종합]', 'naver_news'), ('2026-10-20', '한미반도체 신고가', 'naver_news'),
                                                              ('2026-10-27', '다른 기사', 'naver_news'), ('2026-10-28', '댓글 내용', 'youtube_comment'),
                                                              ('2026-12-01', '미래 기사', 'naver_news')])]})
    part('largest_holder', {CO: [
        {'ticker': CO, 'fiscal_year': 2025, 'holder': '곽동신', 'relate': '최대주주', 'stock_kind': '보통주', 'end_qty': '100', 'stake_rt': '30.00', 'begin_rt': '29.0', 'settle_dt': '2025-12-31', 'rcept_no': '20260310000001'},
        {'ticker': CO, 'fiscal_year': 2025, 'holder': '가족', 'relate': '특수관계인', 'stock_kind': '보통주', 'end_qty': '10', 'stake_rt': '5.00', 'begin_rt': '5.0', 'settle_dt': '2025-12-31', 'rcept_no': '20260310000001'},
        {'ticker': CO, 'fiscal_year': 2025, 'holder': '계', 'relate': '', 'stock_kind': '보통주', 'end_qty': '110', 'stake_rt': '35.00', 'begin_rt': '34.0', 'settle_dt': '2025-12-31', 'rcept_no': '20260310000001'}]})
    part('ownership_report', {CO: [{'ticker': CO, 'rcept_no': '20260401000001', 'repror': '운용사', 'rcept_dt': '2026-04-01', 'report_tp': '약식', 'report_resn': '지분율 변동',
                                    'stkqy': '1', 'stkrt': '6.00', 'stkrt_irds': '1.00', 'ctr_stkrt': None}]})
    # 거시: 환율·관세청 수출, 분기 매출
    obs, q = [], []
    import datetime as dt
    for y in range(2023, 2027):
        for m in range(1, 13):
            if (y, m) > (2026, 9):
                break
            obs.append({'series_id': 'KCS_EXP_854232_USD', 'obs_date': f'{y}-{m:02d}-01', 'value': str(1000000000 * (1 + (y - 2023) * 0.2))})
            for dd in (5, 20):
                obs.append({'series_id': 'ECOS_USDKRW', 'obs_date': f'{y}-{m:02d}-{dd:02d}', 'value': '1300'})
        for qq in range(1, 5):
            if (y, qq) > (2026, 2):
                break
            exp = 3 * 1000000000 * (1 + (y - 2023) * 0.2) * 1300
            q.append({'ticker': CO, 'period_end': f'{y}-{qq * 3:02d}-28', 'fiscal_year': y, 'fiscal_q': qq, 'metric': 'revenue', 'amount': str(int(exp * 0.5)), 'currency': 'KRW'})
    obs.append({'series_id': 'ECOS_USDKRW', 'obs_date': '2025-12-31', 'value': '1300'})
    obs.append({'series_id': 'ECOS_USDKRW', 'obs_date': '2026-11-05', 'value': '1430'})
    obs.append({'series_id': 'ECOS_BASE_RATE', 'obs_date': '2025-12-01', 'value': '2.5'})
    obs.append({'series_id': 'ECOS_BASE_RATE', 'obs_date': '2026-08-01', 'value': '3.0'})
    single('macro_series', [{'series_id': 'KCS_EXP_854232_USD', 'name': '메모리 수출', 'source': 'kcs', 'frequency': 'M', 'unit': None},
                            {'series_id': 'ECOS_USDKRW', 'name': '원/달러', 'source': 'ecos', 'frequency': 'D', 'unit': None},
                            {'series_id': 'ECOS_BASE_RATE', 'name': '기준금리', 'source': 'ecos', 'frequency': 'M', 'unit': '%'}])
    single('macro_obs', obs)
    single('financial_quarter', q)
    single('market_index_daily', [])
    with open(mp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(man))
    with open(os.path.join(d, 'manifest.sha256'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(_h(mp) + '  manifest.json\n')


def nd(i, t, **cfg):
    return {'id': i, 'type': t, 'config': cfg}


def ed(a, ap, b, bp):
    return {'from_node': a, 'from_port': ap, 'to_node': b, 'to_port': bp}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ['MODU_NODES_NEON_DIR'] = self.tmp.name
        market._UNI.clear()
        add_tables(make_v3(self.tmp.name, days=370))
        self.store = Store(os.path.join(self.tmp.name, 'db'))

    def tearDown(self):
        os.environ.pop('MODU_NODES_NEON_DIR', None)
        market._UNI.clear()
        self.tmp.cleanup()

    def run_doc(self, nodes, edges):
        w = WorkflowDoc.model_validate({'name': 'x', 'cutoff': CUT, 'nodes': nodes, 'edges': edges})
        self.assertEqual(blocking(validate(w, N.check_assumptions)), [])
        rid = Engine(self.store).start('o', w.model_dump(), topo_order(w), background=False)
        out = {}
        for n in self.store.get_run('o', rid)['nodes']:
            out[n['node_id']] = (n['status'], self.store.get_packet(n['output_packet'])['payload'] if n['output_packet'] else None, n['reason'])
        return out


class Kit2(Base):
    def test_n01_from_filings(self):
        r = self.run_doc([nd('t11', 'T11', company=CO), nd('n01', 'N01', companies=[], years=[2024, 2025, 2026], metrics=['revenue', 'operatingProfit'])],
                         [ed('t11', 'filings', 'n01', 'filings')])
        st, p, why = r['n01']
        self.assertEqual(st, 'partial', why)                      # 2026년 보고서는 기준시점 뒤
        rev = {f['period']: f for f in p['facts'] if f['metric'] == 'revenue'}
        self.assertEqual(rev[2025]['value'], '600000')           # 백만원, 연결 우선
        self.assertEqual(rev[2025]['scope'], '연결')
        self.assertEqual(rev[2025]['status'], 'api_reported')
        self.assertTrue(any(m['period'] == 2026 for m in p['missing']))
        om = next(d for d in p['derived'] if d['id'] == f'{CO}:2025:operatingMargin')
        self.assertEqual(om['value'], '41.67')

    def test_n01_needs_some_input(self):
        w = WorkflowDoc.model_validate({'name': 'x', 'cutoff': CUT, 'nodes': [nd('n01', 'N01')], 'edges': []})
        self.assertIn('missing_input', {i['code'] for i in blocking(validate(w, N.check_assumptions))})

    def test_n05_n06_from_filings(self):
        r = self.run_doc([nd('t11', 'T11', company=CO), nd('n05', 'N05'), nd('t10', 'T10'), nd('n06', 'N06')],
                         [ed('t11', 'filings', 'n05', 'filings'), ed('n05', 'exposure', 'n06', 'exposure'), ed('t10', 'macro', 'n06', 'macro')])
        self.assertEqual(r['n05'][0], 'succeeded', r['n05'][2])
        e = r['n05'][1]['exposures'][0]
        self.assertEqual(e['fx_struct']['currency'], 'USD')     # 가장 큰 USD 행
        self.assertEqual(e['rate_struct']['shock'], 1.0)        # 100bp → 1%p
        F = {f['name']: f for f in r['n06'][1]['findings']}
        fx = F['한미반도체 환율 영향 (이 가정이라면)']
        self.assertEqual(fx['value'], 10000)                     # 10,000백만원 × (+10%) / 10%
        self.assertIn('원문 확인 필요', fx['formula'])
        self.assertEqual(F['한미반도체 금리 영향 (이 가정이라면)']['value'], -1000)


class Events(Base):
    def test_t08_n11_n12(self):
        r = self.run_doc([nd('t08', 'T08', company=CO, lookback_days=365), nd('n11', 'N11'), nd('t06', 'T06', company=CO), nd('n12', 'N12')],
                         [ed('t08', 'events', 'n11', 'events'), ed('t08', 'events', 'n12', 'events'), ed('t06', 'prices', 'n12', 'prices')])
        ev = r['t08'][1]
        self.assertEqual(len(ev['disclosures']), 4)              # 12월 공시는 기준시점 뒤
        self.assertEqual([d['category'] for d in ev['disclosures']], ['earnings', 'insider', 'deal', 'dividend'])
        self.assertEqual(len(ev['news']), 2)                     # 같은 제목 합침, 댓글·미래 기사 제외
        self.assertEqual(ev['news_duplicates_removed'], 1)
        self.assertEqual(ev['comment_count'], 1)
        self.assertNotIn('댓글 내용', json.dumps(ev, ensure_ascii=False))
        self.assertIn(r['n11'][0], ('succeeded', 'partial'))
        self.assertEqual(r['n12'][0], 'succeeded', r['n12'][2])
        tab = r['n12'][1]['tables'][0]
        self.assertEqual(len(tab['rows']), 3)                    # 임원 보고(반복 공시)는 반응 계산 대상 아님
        self.assertTrue(any('5건 미만' in f['claim'] for f in r['n12'][1]['findings']))


class Ownership(Base):
    def test_n13_excludes_total_row(self):
        r = self.run_doc([nd('t12', 'T12', company=CO), nd('n13', 'N13')], [ed('t12', 'ownership', 'n13', 'ownership')])
        F = {f['name']: f for f in r['n13'][1]['findings']}
        top = F['최대주주 (2025년 말, 사업보고서)']['claim']
        self.assertIn('곽동신 30.00%', top)
        self.assertIn('합계 35.00%', top)


class Nowcast(Base):
    def test_n14_exact_when_ratio_stable(self):
        r = self.run_doc([nd('t11', 'T11', company=CO), nd('t10', 'T10'), nd('n14', 'N14')],
                         [ed('t11', 'filings', 'n14', 'filings'), ed('t10', 'macro', 'n14', 'macro')])
        st, p, why = r['n14']
        self.assertEqual(st, 'succeeded', (why, p['held']))
        est = next(f for f in p['findings'] if '조기 확인' in f['name'] and 'value' in f)
        self.assertEqual(est['kind'], 'forecast_model')
        self.assertAlmostEqual(est['value'], 3 * 1000000000 * 1.6 * 1300 * 0.5, delta=2)      # 2026Q3, 비율 0.5

    def test_kcs_available_next_month_first(self):
        m = market.macro_series('2026-10-01T16:00:00+09:00')
        self.assertEqual(m['series']['KCS_EXP_854232_USD']['obs'][-1][0], '2026-09-01')
        m = market.macro_series('2026-10-01T09:00:00+09:00')     # 장 마감 전 → 9월 30일까지 = 9월치 공개 전
        self.assertEqual(m['series']['KCS_EXP_854232_USD']['obs'][-1][0], '2026-08-01')


if __name__ == '__main__':
    unittest.main()
