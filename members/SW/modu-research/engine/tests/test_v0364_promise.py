"""v0.36.4: 약속–실행(자기주식 취득 결정 ↔ 결과보고서 ↔ 소각 결정) — 원문 읽기 · 짝짓기 · 이행률 · N13."""
import io, json, os, tempfile, unittest, zipfile, hashlib
from mrn import promise as P, dartdocs as D


def cells(*xs):
    return '<TABLE>' + ''.join(f'<TD>{x}</TD>' for x in xs) + '</TABLE>'


def decision(qty, amount, start, end, purpose='주주가치 제고', corrects=None):
    head = cells('정 정 신 고 (보고)', '2. 정정대상 공시서류의 최초제출일 :', corrects, '1. 취득예정주식(주)', '단순 계산 오류', '1', '2') if corrects else ''
    return '<DOCUMENT>' + head + cells('1. 취득예정주식(주)', '보통주식', f'{qty:,}', '기타주식', '-', '2. 취득예정금액(원)', '보통주식', f'{amount:,}', '기타주식', '-',
                                       '3. 취득예상기간', '시작일', start, '종료일', end, '5. 취득목적', purpose, '9. 취득결정일', start) + '</DOCUMENT>'


def result(filed, start, end, qty, total, planned=None, unit='원'):
    four = cells('4. 취득 예정 내용과 실제 취득 내용의 일치 여부', '취득예정금액(원)', '취득가액총액(원)', '취득예정금액미달여부', '미달발생시 사유', '보통주식', '기타주식', '보통주식', '기타주식',
                 f'{planned:,}', '-', f'{total:,}', '-') if planned else \
        cells('4. 취득 예정 내용과 실제 취득 내용의 일치 여부', '취득예정주식(주)', '취득주식총수(주)', '일치여부', '차이발생시 사유', '보통주식', '기타주식', '보통주식', '기타주식', f'{qty:,}', '-', f'{qty:,}', '-')
    return '<DOCUMENT>' + cells('가. 주요사항보고서 제출일 :', filed, '나. 취득기간 :', start, '부터', end, '까지', '3. 취득내용', f'(단위 : {unit}, 주)',
                                '계', '-', f'{qty + 10:,}', f'{qty:,}', '100', f'{total:,}', '-', '-') + four + cells('5. 취득후 자기주식등의 보유상황') + '</DOCUMENT>'


def retire(qty, total_shares, amount, date):
    return '<html><style>.x td { a: 1 }</style>' + cells('1. 소각할 주식의 종류와 수', '보통주식 (주)', f'{qty:,}', '종류주식 (주)', '-', '2. 발행주식 총수', '보통주식 (주)', f'{total_shares:,}', '종류주식 (주)', '-',
                                                          '4. 소각예정금액(원)', f'{amount:,}', '6. 소각할 주식의 취득방법', '기취득 자기주식', '7. 소각 예정일', date, '9. 이사회결의일(결정일)', date) + '</html>'


def store(root, docs):
    """docs: [(rcept_no, kind, report_nm, 'YYYY-MM-DD', xml)] → dartdocs 사본."""
    os.makedirs(root, exist_ok=True); man = {'tool': 'mrn.dartdocs', 'tool_version': 1, 'docs': {}, 'listed': {'000001': {}}, 'failed': {}}
    for no, kind, nm, dt, xml in docs:
        b = io.BytesIO()
        with zipfile.ZipFile(b, 'w') as z:
            z.writestr(no + '.xml', xml.encode('utf-8'))
        open(os.path.join(root, no + '.zip'), 'wb').write(b.getvalue())
        man['docs'][no] = {'ticker': '000001', 'name': '시험', 'report_nm': nm, 'rcept_dt': dt, 'kind': kind, 'file': no + '.zip', 'bytes': len(b.getvalue()),
                           'sha256': hashlib.sha256(b.getvalue()).hexdigest(), 'members': [], 'url': 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' + no}
    D._save_manifest(__import__('pathlib').Path(root), man)


class Parse(unittest.TestCase):
    def test_decision_result_retire_and_correction(self):
        d = P.parse_decision(decision(524384, 100000028800, '2026년 09월 01일', '2026년 11월 30일'))
        self.assertEqual((d['qty'], d['amount'], d['start'], d['end'], d['corrects']), (524384, 100000028800, '2026-09-01', '2026-11-30', None))
        c = P.parse_decision(decision(3486055, 350000000000, '2025년 3월 17일', '2025년 6월 11일', corrects='2025년 3월 14일'))
        self.assertEqual((c['qty'], c['corrects']), (3486055, '2025-03-14'))                      # 앞쪽 정정표가 아니라 본문 서식의 값
        r = P.parse_result(result('2026년 08월 31일', '2026년 09월 01일', '2026년 09월 14일', 544299, 99999898950, planned=100000028800))
        self.assertEqual((r['decision_filed'], r['qty'], r['total'], r['table_total'], r['stated_basis']), ('2026-08-31', 544299, 99999898950, 99999898950, 'amount'))
        old = P.parse_result(result('2023년 02월 01일', '2023.02.02', '2023.02.28', 309406, 48541, unit='백만원'))
        self.assertEqual((old['stated_basis'], old['total']), ('qty', 48541000000))               # 옛 서식: 「계」 줄 총액 × 단위
        t = P.parse_retire(retire(544299, 232617176, 96235873293, '2026-09-30'))
        self.assertEqual((t['qty'], t['shares_total'], t['amount'], t['retire_date'], t['method']), (544299, 232617176, 96235873293, '2026-09-30', '기취득 자기주식'))
        self.assertEqual(P.parse_decision('<DOCUMENT><TD>아무 내용 없음</TD></DOCUMENT>')['amount'], None)   # 못 읽으면 지어내지 않음


class Build(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = os.path.join(self.tmp.name, 'dart_docs')
        store(self.root, [
            ('20260101000001', 'buyback_decision', '주요사항보고서(자기주식취득결정)', '2026-01-01', decision(1000, 100_000_000, '2026-01-02', '2026-03-31')),
            ('20260201000001', 'buyback_result', '자기주식취득결과보고서', '2026-02-01', result('2026년 01월 01일', '2026-01-02', '2026-01-30', 990, 99_000_000, planned=100_000_000)),
            ('20260210800001', 'retire', '주식소각결정', '2026-02-10', retire(990, 100000, 99_000_000, '2026-02-20')),
            ('20260301000001', 'buyback_decision', '주요사항보고서(자기주식취득결정)', '2026-03-01', decision(1000, 100_000_000, '2026-03-02', '2026-05-31')),
            ('20260401000001', 'buyback_result', '자기주식취득결과보고서', '2026-04-01', result('2026년 03월 01일', '2026-03-02', '2026-03-30', 600, 60_000_000, planned=100_000_000)),
            ('20260501000001', 'buyback_decision', '주요사항보고서(자기주식취득결정)', '2026-05-01', decision(1000, 100_000_000, '2026-05-02', '2026-07-31')),
            ('20260601000001', 'buyback_decision', '주요사항보고서(자기주식취득결정)', '2026-06-01', decision(1000, 100_000_000, '2026-06-02', '2026-08-31')),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_pairing_rates_and_states(self):
        b = P.build('000001', '2026-08-01T16:00:00+09:00', self.root)
        got = [(r['filed'], r['rate'], r['verdict'], bool(r['retire'])) for r in b['rows']]
        self.assertEqual(got, [('2026-01-01', 99.0, '이행', True), ('2026-03-01', 60.0, '부분 이행', False), ('2026-05-01', None, '결과 미확인', False), ('2026-06-01', None, '진행 중', False)])
        self.assertEqual(b['unlinked_retires'], []); self.assertEqual(len(b['docs']), 7)

    def test_cutoff_hides_later_filings(self):
        b = P.build('000001', '2026-01-15T16:00:00+09:00', self.root)
        self.assertEqual([(r['filed'], r['verdict']) for r in b['rows']], [('2026-01-01', '진행 중')])   # 결과보고서·소각은 기준 날짜 뒤라 쓰지 않음
        self.assertEqual(b['retires'], [])

    def test_judge_thresholds(self):
        self.assertEqual([P.judge(x) for x in (95.0, 94.9, 50.0, 49.9)], ['이행', '부분 이행', '부분 이행', '미달'])


class Node(unittest.TestCase):
    def test_n13_lines_kinds_and_held_when_no_docs(self):
        from mrn import nodes as N
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, 'dart_docs')
            store(root, [('20260101000001', 'buyback_decision', '주요사항보고서(자기주식취득결정)', '2026-01-01', decision(1000, 100_000_000, '2026-01-02', '2026-03-31')),
                         ('20260201000001', 'buyback_result', '자기주식취득결과보고서', '2026-02-01', result('2026년 01월 01일', '2026-01-02', '2026-01-30', 990, 99_000_000, planned=100_000_000))])
            F, held, T = [], [], []
            N._promise_findings({'promise': P.build('000001', '2026-08-01T16:00:00+09:00', root)}, F, held, T)
        by = {f['name']: f for f in F}
        self.assertEqual(by['이행률 (2026-01-01 결정)']['kind'], 'rule_derived'); self.assertIn('95%', by['이행률 (2026-01-01 결정)']['claim']); self.assertIn('「이행」', by['이행률 (2026-01-01 결정)']['claim'])
        self.assertEqual(by['자기주식 취득 결정 (2026-01-01)']['kind'], 'fact_official'); self.assertIn('rcpNo=20260101000001', by['자기주식 취득 결정 (2026-01-01)']['source']['url'])
        self.assertEqual(len(T), 1)
        txt = json.dumps(F, ensure_ascii=False)
        for bad in ('약속을 지켰', '신뢰할 수', '주주친화적', '호재'):
            self.assertNotIn(bad, txt)
        F, held, T = [], [], []
        N._promise_findings({'promise': None, 'promise_held': '약속–실행(자사주 취득 이행률·소각 연결): DART 원문 사본이 이 PC에 없음'}, F, held, T)
        self.assertEqual((F, T), ([], [])); self.assertIn('DART 원문 사본이 이 PC에 없음', held[0])


if __name__ == '__main__':
    unittest.main()
