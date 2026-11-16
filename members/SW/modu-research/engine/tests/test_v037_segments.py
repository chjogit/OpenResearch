"""v0.37: 사업부별 분기 매출(박상혁 P02 이식) — 표 읽기 기본기 · 자격 관문 · T14/N19 · 실적 카드 연결."""
import json, os, unittest
from pathlib import Path
from mrn import segments as S, dartdocs as D, nodes as N
from mrn.easy import plan
from mrn.specs import SPECS, TYPE_SOURCE
from mrn.util import digest
from mrn.workflow import WorkflowDoc, validate, blocking

CUT = '2026-11-07T00:00:00+09:00'


def pkt(p):
    return {'header': {'type': 'SegmentRevenue', 'payload_digest': digest(p), 'produced_by': {'node_type': 'T14', 'node_id': 't14'}}, 'payload': p}


def q(axis, key, y, qq, v, method='reported_3m', yoy=None, name=None):
    return {'axis': axis, 'key': key, 'name': name or key, 'year': y, 'q': qq, 'value': v, 'method': method, 'formula': '연간 − 9개월 누적' if method != 'reported_3m' else None,
            'sources': [{'report': '반기보고서 (2026.06)', 'url': 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260814000001', 'rcept_no': '20260814000001'}], 'yoy': {'pct': yoy} if yoy is not None else None}


class Basics(unittest.TestCase):
    def test_grid_spans_num_period_growth(self):
        h, b = S.grid('<TABLE><THEAD><TR><TH ROWSPAN="2">구분</TH><TH COLSPAN="2">당분기</TH></TR><TR><TH>3개월</TH><TH>누적</TH></TR></THEAD><TBODY><TR><TD>매출액</TD><TD>1,234</TD><TD>(5,678)</TD></TR></TBODY></TABLE>')
        self.assertEqual(h, [['구분', '당분기', '당분기'], ['구분', '3개월', '누적']]); self.assertEqual(b, [['매출액', '1,234', '(5,678)']])   # 합쳐진 칸을 풀어 같은 값으로 채움
        self.assertEqual((S.num('1,234'), S.num('(5,678)'), S.num('-')), (1234, -5678, None))
        self.assertEqual([S.report_period(x) for x in ('사업보고서 (2025.12)', '반기보고서 (2026.06)', '분기보고서 (2025.09)', '분기보고서 (2025.03)', '사업보고서 (2025.03)')],
                         [(2025, 'FY'), (2026, 'H1'), (2025, 'Q3'), (2025, 'Q1'), None])                     # 12월 결산이 아니면 다루지 않음
        self.assertEqual(S.growth_pct(127516071, 27874977), 357.46)
        self.assertIsNone(S.growth_pct(100, 0)); self.assertIsNone(S.growth_pct(100, -5))                    # 0·음수 기준으로는 증감률을 내지 않음
        self.assertEqual(S.key_of('005930', 'Haman'), S.key_of('005930', 'Harman'))                          # PM이 등록한 오기 연결만 잇는다
        self.assertNotEqual(S.key_of('000660', 'Haman'), S.key_of('000660', 'Harman'))


class Engine(unittest.TestCase):
    def test_registered_and_wired_into_earnings_card(self):
        self.assertEqual((SPECS['T14']['tier'], SPECS['N19']['tier'], TYPE_SOURCE['SegmentRevenue']), ('tool', 'addon', 'T14'))
        for co in ('005930', '042700'):
            d = plan('earnings', co, CUT)
            self.assertIn({'t14', 'n19', 'n01'}.intersection({n['id'] for n in d['nodes']}), [{'t14', 'n19', 'n01'}])
            self.assertEqual(blocking(validate(WorkflowDoc.model_validate(d), N.check_assumptions)), [])
        self.assertNotIn('t14', {n['id'] for n in plan('price', '005930', CUT)['nodes']})

    def test_n19_not_qualified_shows_reason_only(self):
        r = N.n19({'config': {}}, {'segments': [pkt({'company': '000660', 'name': 'SK하이닉스', 'qualified': False, 'reasons': ['설명 안 되는 합계 불일치 표 3개'], 'source': {}})]}, None)
        self.assertEqual((r.status, r.payload['findings'], r.payload['tables']), ('succeeded', [], []))      # 값을 지어내지 않고, 실행 상태도 바꾸지 않음
        self.assertEqual(r.payload['held'], ['사업부별 분기 매출: 설명 안 되는 합계 불일치 표 3개'])

    def test_n19_qualified_lines_kinds_and_no_judgement(self):
        Q = [q('segment', 'ds', 2026, 'Q2', 127516071000000, yoy=357.46, name='DS 부문'), q('segment', 'ds', 2025, 'Q4', 44005283000000, method='fy_minus_9m', yoy=46.2, name='DS 부문'),
             q('segment', 'dx', 2026, 'Q2', 48022400000000, name='DX 부문'), q('region', 'kr', 2026, 'Q2', 12150500000000, yoy=12.5, name='국내'), q('region', 'old', 2023, 'Q1', 5, name='옛 이름')] + \
            [q('region', 'kr', y, k, 10 ** 13, name='국내') for y, k in ((2025, 'Q1'), (2025, 'Q2'), (2025, 'Q3'), (2025, 'Q4'), (2026, 'Q1'))]
        p = {'company': '005930', 'name': '삼성전자', 'qualified': True, 'reasons': [], 'quarters': Q, 'held': ['region 옛 이름 2023Q4: 9개월 누적 값이 없어 계산하지 않음'],
             'tables': {'count': 132, 'A': 18, 'B': 68, 'C': 46, 'X': 0, 'exact': 86}, 'independent': {'compared': 18, 'matched': 18, 'mismatched': []}, 'source': {'dart_docs': {'sha256': 'x'}}}
        r = N.n19({'config': {}}, {'segments': [pkt(p)]}, None)
        by = {f['name']: f for f in r.payload['findings']}
        ds = by['DS 부문 2026년 2분기 매출']
        self.assertEqual((ds['kind'], ds['value'], ds['unit'], ds['claim']), ('fact_official', 127516071000000, '원', '1,275,161억원'))
        self.assertIn('rcpNo=20260814000001', ds['source']['url'])
        self.assertIn('DS 부문 +357.46%', by['사업부(보고부문) 전년 동기 대비 (2026년 2분기)']['claim'])
        self.assertEqual(by['사업부(보고부문) 전년 동기 대비 (2026년 2분기)']['kind'], 'derived')
        self.assertNotIn('국내 2026년 2분기 매출', by)                                                       # 한 줄씩 보이는 것은 사업부 축만, 지역·제품은 표로
        t = {x['title'].split('별')[0]: x for x in r.payload['tables']}
        self.assertEqual(t['사업부(보고부문)']['rows'][0][0], 'DS 부문'); self.assertIn('※', t['사업부(보고부문)']['rows'][0][1])   # 연간−9개월 값은 표시
        self.assertEqual([x[0] for x in t['지역']['rows']], ['국내'])                                         # 보이는 기간에 값이 없는 줄은 뺌
        self.assertTrue(any('비워 둔 칸 1개' in h and '보류' in h for h in r.payload['held']))
        txt = json.dumps(r.payload['findings'], ensure_ascii=False) + r.reason
        for bad in ('호조', '부진', '성장세', '긍정', '부정적', '매수', '매도', '유망'):
            self.assertNotIn(bad, txt)

    def test_n19_rejects_other_source(self):
        bad = pkt({'qualified': False}); bad['header']['produced_by']['node_type'] = 'T11'
        with self.assertRaises(Exception):
            N.n19({'config': {}}, {'segments': [bad]}, None)

    def test_docs_digest_ignores_other_companies(self):
        a = [{'rcept_no': '2', 'sha256': 'b'}, {'rcept_no': '1', 'sha256': 'a'}]
        self.assertEqual(N._docs_digest(a), N._docs_digest(list(reversed(a))))
        self.assertNotEqual(N._docs_digest(a), N._docs_digest(a[:1]))


REAL = D.docs_dir()


def _has_samsung():
    try:
        return '005930' in (D.load_manifest(REAL).get('listed') or {})
    except Exception:
        return False


@unittest.skipUnless(_has_samsung(), '이 PC에 삼성전자 DART 원문 사본이 없으면 건너뜀')
class RealSamsung(unittest.TestCase):
    """실제 사본으로 고정 값 확인(기준 날짜를 고정하므로 뒤에 받은 보고서는 영향이 없다)."""
    def test_gate_and_known_values(self):
        from mrn.market import resolve, load_manifest, read_rows
        root = resolve(''); rows, _ = read_rows(root, load_manifest(root), 'financial_quarter', '005930')
        rev = {r['period_end']: int(float(r['amount'])) for r in rows if r.get('metric') == 'revenue' and r.get('amount') not in (None, '')}
        r = S.qualified('005930', CUT, rev)
        self.assertTrue(r['qualified']); self.assertEqual(r['tables']['X'], 0); self.assertFalse(r['independent']['mismatched'])
        self.assertGreaterEqual(r['independent']['matched'], S.MIN_MATCH)
        cell = {(x['axis'], x['name'], x['year'], x['q']): x for x in r['quarters']}
        ds = cell[('segment', 'DS 부문', 2026, 'Q2')]
        self.assertEqual((ds['value'], ds['yoy']['pct'], ds['method']), (127516071000000, 357.46, 'reported_3m'))
        self.assertEqual(cell[('segment', 'DS 부문', 2025, 'Q4')]['value'], 44005283000000)
        self.assertEqual(S.qualified('005930', '2023-01-01T00:00:00+09:00', rev)['qualified'], False)        # 기준 날짜 전에는 쓸 보고서가 없음


if __name__ == '__main__':
    unittest.main()
