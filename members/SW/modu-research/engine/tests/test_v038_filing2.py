"""v0.38 T2-3 손익구조 변경: 원문 읽기(2025·2026 서식·정정) · 다시 계산해 공시 값과 대조 · 정정 전후 차이 · 정정된 옛 공시 안내 · 카드·확인서 · 실제 원문 전부."""
import io, json, os, tempfile, unittest, zipfile
from pathlib import Path
from mrn import dartdocs as D, filing as FL, filing2 as F2
from tests.test_easy import EasyBase, CUT
from tests.test_v038_filing import html, CO

REAL_DOCS = Path(__file__).resolve().parents[2] / '_sources' / 'dart_docs'


def pl(rows, bs, year26=True, basis='연결', unit='천원', corr=None, decided='2026-01-16', extra_ratio=None):
    r = []
    if corr:
        r += [['정정신고(보고)'], ['정정일자', decided], ['1. 정정관련 공시서류', '매출액 또는 손익구조 30%(대규모법인은15%)이상 변경'], ['2. 정정관련 공시서류제출일', corr[0]],
              ['3. 정정사유', corr[1]], ['4. 정정사항'], ['정정항목', '정정전', '정정후'], ['- 영업이익', 'ㆍ당해사업연도', '1', '2']]
    r += [['매출액 또는 손익구조 30%(대규모법인 15%)이상 변경'], ['1. 재무제표의 종류', basis]]
    if year26:
        r += [['2. 결산기간', '당해사업연도', '직전사업연도'], ['- 시작일', '2025-01-01', '2024-01-01'], ['- 종료일', '2025-12-31', '2024-12-31'],
              [f'3. 매출액 또는 손익구조 변동내용(단위:{unit})', '당해사업연도', '직전사업연도', '증감금액', '증감비율(%)', '흑자적자전환여부']]
    else:
        r += [[f'2. 매출액 또는 손익구조 변동내용(단위:{unit})', '당해사업연도', '직전사업연도', '증감금액', '증감비율(%)']]
    for lab, v in zip(('- 매출액', '- 영업이익', '- 법인세비용차감전계속사업이익', '- 당기순이익'), rows):
        r.append([lab] + list(v[:5 if year26 else 4]))
    r += [['- 대규모법인여부', '해당'], [f'4. 재무현황(단위:{unit})', '당해사업연도', '직전사업연도']]
    for lab, v in zip(('- 자산총계', '- 부채총계', '- 자본총계', '- 자본금'), bs):
        r.append([lab] + list(v))
    r.append(['- 자본총계/자본금 비율(%)'] + list(extra_ratio) if extra_ratio else ['- 자본잠식률(%) =〔(자본금-자본총계)/자본금〕×100', '-', '-'])
    r += [['5. 매출액 또는 손익구조 변동 주요원인', '- 물량 증가'], ['6. 이사회결의일(결정일)', decided], ['- 사외이사 참석여부', '참석(명)', '3', '불참(명)', '-'],
          ['[지배회사의 추가공시사항]'], ['구분', '재무제표', '당해 사업연도', '직전 사업연도'], ['매출액(단위:천원)', '별도', '900,000', '800,000']]
    return html(r, title='한미반도체/매출액또는손익구조30%(대규모법인은15%)이상변경/(2026.01.16)')


ROWS = [('1,200,000', '1,000,000', '200,000', '20.0', '-'), ('150,000', '-50,000', '200,000', '-', '흑자전환'),
        ('140,001', '100,000', '40,000', '40.0', '-'), ('100,000', '80,000', '25,000', '25.0', '-')]      # 세전: 표 단위 1칸 차이 / 순이익: 증감금액 오기
BS = [('3,000,000', '2,500,000'), ('1,000,000', '900,000'), ('2,000,000', '1,600,000'), ('500,000', '500,000')]
ROWS2 = [ROWS[0], ('160,000', '-50,000', '210,000', '-', '흑자전환'), ROWS[2], ('100,000', '80,000', '20,000', '25.0', '-')]
NM = '매출액또는손익구조30%(대규모법인은15%)이상변경'
DOCS = {'20260116800001': ('pl_change', NM, pl(ROWS, BS)),
        '20260205800002': ('pl_change', '[기재정정]' + NM, pl(ROWS2, BS, corr=('2026-01-16', '외부감사 중 수정사항 반영'), decided='2026-02-05')),
        '20250120800003': ('pl_change', NM, pl(ROWS, BS, year26=False, extra_ratio=('400.0', '320.0'), decided='2025-01-20'))}


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
    def test_2026_form(self):
        p = F2.parse_pl_change(DOCS['20260116800001'][2])
        self.assertEqual((p['basis'], p['unit'], p['layout'], p['large'], p['decided']), ('연결', '천원', 5, '해당', '2026-01-16'))
        self.assertEqual(p['period']['end'][0], '2025-12-31')
        self.assertEqual(p['rows']['revenue'], {'cur': 1_200_000_000, 'prev': 1_000_000_000, 'diff_stated': 200_000_000, 'rate_stated': 20.0, 'rate_text': None, 'turn': None})
        self.assertEqual((p['rows']['op']['prev'], p['rows']['op']['turn'], p['rows']['op']['rate_stated']), (-50_000_000, '흑자전환', None))
        self.assertEqual(p['bs']['equity'], {'cur': 2_000_000_000, 'prev': 1_600_000_000})
        self.assertEqual(p['reasons'], ['- 물량 증가']); self.assertEqual(p['separate_revenue']['cur'], 900_000_000)
        self.assertIsNone(p['corrects'])

    def test_2025_form_and_correction_reads_body_not_correction_table(self):
        p = F2.parse_pl_change(DOCS['20250120800003'][2])
        self.assertEqual((p['layout'], p['period'], p['bs']['eq_cap_stated']), (4, {}, {'cur': 400.0, 'prev': 320.0}))
        q = F2.parse_pl_change(DOCS['20260205800002'][2])
        self.assertEqual((q['corrects'], q['correction_reason']), ('2026-01-16', '외부감사 중 수정사항 반영'))
        self.assertEqual(q['rows']['op']['cur'], 160_000_000)              # 정정표의 「1 · 2」가 아니라 본문 값

    def test_triangle_and_paren_negatives(self):
        self.assertEqual((F2._v('△1,234.5'), F2._v('(12)'), F2._v('-'), F2._amt('▲3', 1000)), (-1234.5, -12.0, None, -3000))


class Compute(unittest.TestCase):
    def run_doc(self, no, history=(), newer=()):
        kind, nm, body = DOCS[no]
        f = {'kind': kind, 'parsed': F2.parse_pl_change(body), 'report_nm': nm, 'rcept_dt': f'{no[:4]}-{no[4:6]}-{no[6:8]}', 'url': '', 'rcept_no': no,
             'history': list(history), 'newer': list(newer)}
        F, held, T, notes = FL.compute(json.loads(json.dumps(f)), None)        # 꾸러미를 거쳐도(튜플→목록) 같아야 함
        return {x['name']: x for x in F}, held, T, notes

    def test_recalc_and_stated_checks(self):
        F, held, T, notes = self.run_doc('20260116800001')
        self.assertIn('공시 값과 같음', F['매출액 증감금액']['claim']); self.assertEqual(F['매출액 증감률']['value'], 20.0)
        self.assertIn('표 단위 천원 반올림 차이', F['법인세차감전 계속사업이익 증감금액']['claim'])                 # J3
        c = F['당기순이익 증감금액']['claim']
        self.assertIn('공시에 적힌 증감금액은 25,000천원, 다시 계산하면 20,000천원', c); self.assertIn('반올림으로 설명되지 않음', c)
        self.assertIn('흑자전환 · 공시 표시와 같음', F['영업이익 흑자·적자 전환']['claim'])
        self.assertNotIn('영업이익 증감률', F)                                                                   # J1 직전이 적자면 계산하지 않음
        self.assertTrue(any(h.startswith('영업이익 증감률: 직전 값이 0 이하') for h in held))
        self.assertEqual(F['부채비율(당해 말)']['value'], 50.0); self.assertEqual(F['영업이익률(당해)']['value'], 12.5)
        self.assertEqual([t['title'][:6] for t in T], ['매출액·손익', '재무현황 —'])
        self.assertIn('회사가 적은 변동 주요원인(원문 그대로)', F)

    def test_eq_cap_ratio_checked_in_2025_form(self):
        F, *_ = self.run_doc('20250120800003')
        self.assertIn('400.00% · 공시 값과 같음', F['자본총계 ÷ 자본금(당해 말)']['claim'])

    def test_no_direction_words(self):
        F, held, T, notes = self.run_doc('20260116800001')
        blob = json.dumps([list(F.values()), held, T, notes], ensure_ascii=False)
        for w in ('호재', '악재', '긍정적', '부정적', '매수', '매도', '서프라이즈', '쇼크'):
            self.assertNotIn(w, blob)

    def test_correction_diff_numbers_and_reason(self):
        old = {'rcept_no': '20260116800001', 'rcept_dt': '2026-01-16', 'url': '', 'report_nm': NM, 'parsed': F2.parse_pl_change(DOCS['20260116800001'][2])}
        F, held, T, notes = self.run_doc('20260205800002', history=[old])
        d = next(v for k, v in F.items() if '달라진 숫자' in k)
        self.assertIn('달라진 숫자 1곳', d['name'])
        self.assertIn('영업이익(당해) 2억 원 → 2억 원', d['claim'].replace('150,000,000원 → 160,000,000원', '2억 원 → 2억 원'))   # 억 단위로 같아 보이면 원 단위로
        self.assertIn('150,000,000원 → 160,000,000원', d['claim']); self.assertIn('+6.67%', d['claim'])
        self.assertTrue(any('정정사유(원문 그대로): 「외부감사 중 수정사항 반영」' in n for n in notes))
        self.assertIn('공시 값과 같음', F['당기순이익 증감금액']['claim'])           # 정정본에서는 오기가 고쳐짐

    def test_superseded_filing_is_not_computed(self):
        F, held, T, notes = self.run_doc('20260116800001', newer=[{'rcept_no': '20260205800002', 'rcept_dt': '2026-02-05', 'url': '', 'report_nm': 'x'}])
        self.assertEqual(F, {}); self.assertEqual(T, [])
        self.assertIn('최신본(접수번호 20260205800002)', held[0])


class Card(EasyBase):
    def setUp(self):
        super().setUp()
        self.docs = tempfile.TemporaryDirectory(); os.environ['MODU_NODES_DART_DOCS'] = os.path.join(self.docs.name, 'dart_docs')
        make_docs(os.environ['MODU_NODES_DART_DOCS'])

    def tearDown(self):
        os.environ.pop('MODU_NODES_DART_DOCS', None); self.docs.cleanup()
        super().tearDown()

    def run_filing(self, no, cut):
        r = self.c.post('/api/easy/run', json={'card': 'filing', 'company': CO, 'cutoff': cut, 'rcept_no': no})
        self.assertEqual(r.status_code, 201, r.text); self.wait(r.json()['id'])
        return r.json()['id'], self.c.get(f"/api/easy/answer/{r.json()['id']}").json()

    def test_end_to_end_latest_with_history_and_receipt(self):
        rid, a = self.run_filing('20260205800002', '2026-03-01T16:00:00+09:00')
        txt = {i['label']: i['text'] for i in a['items']}
        self.assertIn('20.00%', txt['매출액 증감률'])
        self.assertTrue(any('달라진 숫자 1곳' in k for k in txt))
        rc = self.c.get(f'/api/easy/receipt/{rid}').json()
        v = self.c.post('/api/easy/verify', json={'receipt': rc}).json()
        self.assertTrue(v['ok'], v); self.assertEqual(v['matched'], v['total'])

    def test_point_in_time_old_filing_before_and_after_correction(self):
        _, a = self.run_filing('20260116800001', '2026-01-20T16:00:00+09:00')          # 정정 전 날짜로 보면: 그때는 최신본 → 계산됨
        self.assertTrue(any(i['label'] == '매출액 증감률' for i in a['items']))
        _, b = self.run_filing('20260116800001', '2026-03-01T16:00:00+09:00')          # 정정 뒤 날짜로 보면: 최신본 안내
        self.assertFalse(any(i['label'] == '매출액 증감률' for i in b['items']))
        self.assertIn('최신본(접수번호 20260205800002)', json.dumps(b, ensure_ascii=False))

    def test_filings_list_shows_new_kind(self):
        r = self.c.get(f'/api/watch/filings/{CO}').json()
        self.assertEqual({x['kind'] for x in r['rows']}, {'pl_change'})
        self.assertIn('매출액·손익구조 변경', [k['label'] for k in r['kinds']])


@unittest.skipUnless(REAL_DOCS.is_dir() and any(d['kind'] == 'pl_change' for d in D.load_manifest(REAL_DOCS)['docs'].values()), '이 PC에 손익구조 변경 원문 사본이 있을 때만')
class RealDocs(unittest.TestCase):
    def test_all_read_and_stated_values_recomputed(self):
        import collections
        man = D.load_manifest(REAL_DOCS); c = collections.Counter(); big = []
        for no, d in sorted(man['docs'].items()):
            if d['kind'] != 'pl_change':
                continue
            p = F2.parse_pl_change('\n'.join(t for _, t in D.open_doc(no, REAL_DOCS, man)[0])); u = FL.MONEY_UNIT.get(p['unit'], 1); c['docs'] += 1
            self.assertEqual(len(p['rows']), 4, no)
            self.assertTrue(all(r['cur'] is not None and r['prev'] is not None for r in p['rows'].values()), no)
            self.assertEqual(len([k for k in ('assets', 'liab', 'equity', 'capital') if p['bs'].get(k, {}).get('cur') is not None]), 4, no)
            for k, r in p['rows'].items():
                dd = r['cur'] - r['prev']
                if r['diff_stated'] is not None:
                    g = abs(dd - r['diff_stated']); c['same' if g == 0 else 'round' if g <= 2 * u else 'big'] += 1
                    if g > 2 * u:
                        big.append((no, k))
                if r['prev'] > 0 and r['rate_stated'] is not None:
                    c['rate_ok' if abs(dd / r['prev'] * 100 - r['rate_stated']) <= 0.56 else 'rate_bad'] += 1
        self.assertGreaterEqual(c['docs'], 400)
        self.assertEqual(c['rate_bad'], 0)                                       # 증감률은 전부 같거나 반올림 차이
        self.assertLessEqual(c['big'], max(4, c['docs'] // 100), big)            # 회사 쪽 오기 몇 건만(2025~2026 사본: 4칸) — 화면에 「원문 확인」
        for known in (('20250115800126', 'op'), ('20250204800542', 'net'), ('20250205800619', 'op'), ('20250228801652', 'revenue')):
            if known[0] in man['docs']:
                self.assertIn(known, big)


if __name__ == '__main__':
    unittest.main()
