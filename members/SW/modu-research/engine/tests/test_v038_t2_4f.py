"""v0.38 T2-4f 손익구조 변경 ↔ 잠정실적 교차 대조(J25).
- 같은 회사·같은 결산기간·같은 재무제표 종류의 앞선 잠정실적과 견줌: 같음 / 표 단위 2칸 안(반올림) / 다름(금액·비율).
- 재무제표 종류가 다르면 견주지 않고 한 줄 알림. 이 공시보다 뒤의 잠정실적·기준 날짜 뒤 공시는 쓰지 않음. 정정된 잠정실적은 최신본.
- 짝이 된 잠정실적 원문은 확인서 사슬에 들어감. 방향 판단 없음. 실제 원문 전부 읽기."""
import io, os, tempfile, unittest, zipfile
from pathlib import Path
from mrn import dartdocs as D, filing as FL
from tests.test_easy import EasyBase
from tests.test_v038_filing import html, CO
from tests.test_v038_filing2 import pl, ROWS, BS, NM, REAL_DOCS


def prelim(cons=True, unit='백만원', ytd=('1,200', '150', '140', '95'), corr=False):
    t = ('연결재무제표기준' if cons else '') + '영업(잠정)실적(공정공시)'
    r = [[t], ['실적기간', '당기실적', '2025-10-01', '~', '2025-12-31'], ['전기실적', '2025-07-01', '~', '2025-09-30'],
         ['전년동기실적', '2024-10-01', '~', '2024-12-31'], ['당기누계실적', '2025-01-01', '~', '2025-12-31'], ['1. 연결실적내용' if cons else '1. 실적내용'], [f'단위 : {unit}, %'],
         ['구분', '당기실적', '전기실적', '전기대비', '전년동기실적', '전년동기대비'], ["('25.4Q)", "('25.3Q)", '증감율(%)', '흑자적자전환여부', "('24.4Q)", '증감율(%)', '흑자적자전환여부']]
    for lab, y in zip(('매출액', '영업이익', '법인세비용차감전계속사업이익', '당기순이익'), ytd):
        r += [[lab, '당해실적', '300', '290', '3.4', '-', '280', '7.1', '-'], ['누계실적', y, '-', '-', '-', '1,000', '-', '-']]
    return html(r, title=f"한미반도체/{'[기재정정]' if corr else ''}{t}/(2026.01.10)")


DOCS = {'20260110800010': ('prelim', '연결재무제표기준영업(잠정)실적(공정공시)', prelim(ytd=('1,190', '150', '140', '95'))),
        '20260112800011': ('prelim', '[기재정정]연결재무제표기준영업(잠정)실적(공정공시)', prelim(corr=True)),       # 정정본이 짝
        '20260111800012': ('prelim', '영업(잠정)실적(공정공시)', prelim(cons=False, ytd=('900', '50', '40', '30'))),    # 별도 — 견주지 않음
        '20260116800001': ('pl_change', NM, pl(ROWS, BS)),
        '20260120800013': ('prelim', '연결재무제표기준영업(잠정)실적(공정공시)', prelim(ytd=('9,999', '1', '1', '1')))}  # 뒤에 나온 것 — 쓰지 않음


def make(root, docs):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    man = {'tool': 'mrn.dartdocs', 'tool_version': 1, 'origin': '시험', 'docs': {}, 'listed': {}, 'failed': {}}
    for no, (kind, nm, body) in docs.items():
        b = io.BytesIO()
        with zipfile.ZipFile(b, 'w') as z:
            z.writestr(f'{no}.xml', body.encode('utf-8'))
        b = b.getvalue(); (root / f'{no}.zip').write_bytes(b)
        man['docs'][no] = {'ticker': CO, 'corp_code': '00000001', 'name': '한미반도체', 'report_nm': nm, 'rcept_dt': f'{no[:4]}-{no[4:6]}-{no[6:8]}', 'kind': kind,
                           'file': f'{no}.zip', 'bytes': len(b), 'sha256': D._sha(b), 'members': [], 'url': f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={no}'}
    D._save_manifest(root, man)


class Cross(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); make(self.tmp.name, DOCS)

    def tearDown(self):
        self.tmp.cleanup()

    def calc(self, docs=None, cut=None):
        if docs is not None:
            make(self.tmp.name, docs)
        f = FL.load(CO, '20260116800001', cut, root=self.tmp.name)
        F, held, T, notes = FL.compute(f, None)
        return f, {x['name']: x['claim'] for x in F}, T, notes

    def test_prelim_parses_full_year(self):
        p = FL.parse('prelim', DOCS['20260112800011'][2])
        self.assertEqual(tuple(p['period']['ytd']), ('2025-01-01', '2025-12-31'))
        self.assertEqual(p['rows']['op']['ytd'], 150 * 10**6)

    def test_compare_latest_correction_same_basis(self):
        f, c, T, notes = self.calc()
        self.assertEqual(f['prelim']['rcept_no'], '20260112800011')                    # 정정본, 뒤에 나온 것·별도는 아님
        self.assertIn({'rcept_no': '20260112800011', 'sha256': f['prelim'] and D.load_manifest(self.tmp.name)['docs']['20260112800011']['sha256']}, f['docs'])
        self.assertEqual(c['매출액 — 앞서 낸 잠정실적과 대조'], '잠정 12억 원 → 이 공시 12억 원 · 같음')
        self.assertTrue(c['법인세차감전 계속사업이익 — 앞서 낸 잠정실적과 대조'].endswith('같음(잠정실적 표 단위 백만원 반올림 안)'))   # 140,001천원 vs 140백만원
        self.assertIn('5,000,000원 다름 (+5.26%)', c['당기순이익 — 앞서 낸 잠정실적과 대조'])                                           # 100백만원 vs 95백만원
        t = next(x for x in T if x['title'].startswith('앞서 낸 잠정실적과 대조'))
        self.assertEqual([r[0] for r in t['rows']], ['매출액', '영업이익', '법인세차감전 계속사업이익', '당기순이익'])
        for w in ('호재', '악재', '좋', '나쁘'):
            self.assertFalse(any(w in v for k, v in c.items() if '잠정실적' in k))

    def test_other_basis_only_is_not_compared(self):
        d = {k: v for k, v in DOCS.items() if k in ('20260111800012', '20260116800001')}
        f, c, T, notes = self.calc(d)
        self.assertIsNone(f['prelim'])
        self.assertFalse(any('잠정실적과 대조' in k for k in c))
        self.assertIn('앞서 낸 잠정실적(2026-01-11, 별도 기준)은 이 공시와 재무제표 종류가 달라 견주지 않았습니다.', notes)

    def test_point_in_time(self):
        f, c, T, notes = self.calc(cut='2026-01-16T16:00:00+09:00')
        self.assertEqual(f['prelim']['rcept_no'], '20260112800011')
        d = {k: v for k, v in DOCS.items() if k in ('20260116800001', '20260120800013')}
        f, c, T, notes = self.calc(d)
        self.assertIsNone(f['prelim'])                                                  # 이 공시 뒤의 잠정실적은 짝이 아님


@unittest.skipUnless((REAL_DOCS / 'manifest.json').exists(), '실제 원문 사본 없음')
class RealDocs(unittest.TestCase):
    def test_real_pairs(self):
        man = D.load_manifest(REAL_DOCS); paired = same = diff = 0
        for n, d in sorted(man['docs'].items()):
            if d['kind'] != 'pl_change':
                continue
            try:
                f = FL.load(d['ticker'], n, None, root=REAL_DOCS)
            except D.DartDocsError:
                continue
            F, *_ = FL.compute(f, None)
            if f.get('prelim'):
                paired += 1
                self.assertEqual(f['prelim']['basis'], '연결' if '연결' in f['parsed'].get('basis', '') else '별도', n)
            for x in F:
                if x['name'].endswith('앞서 낸 잠정실적과 대조'):
                    v = x['claim'].split(' · ', 1)[1]
                    same += v.startswith('같음'); diff += not v.startswith('같음')
        self.assertGreaterEqual(paired, 80)                                             # 2026-11 사본: 손익구조 변경 422건 중 80건 짝
        self.assertGreater(same, diff * 5)                                              # 대부분 반올림 안에서 같음(249 : 33)
