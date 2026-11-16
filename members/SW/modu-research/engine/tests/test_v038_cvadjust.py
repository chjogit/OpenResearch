"""v0.38 T2-4b 리픽싱 대조용 표본: 「전환가액의 조정」 종류 · 시세 사본 회사만 회사별로 받기(표본 폴더, 사용량 계측, 키를 남기지 않음)."""
import io, json, os, tempfile, unittest, urllib.parse, zipfile
from pathlib import Path
from unittest import mock
from mrn import dartdocs as D, dartsamples as DS, filing as FL


class Kind(unittest.TestCase):
    def test_titles(self):
        for t in ('전환가액의조정', '[기재정정]전환가액의조정', '신주인수권행사가액의조정', '교환가액의조정(제2회)', '전환가액의 조정'):
            self.assertEqual(D.classify(t), 'cv_adjust', t)
        self.assertIsNone(D.classify('전환가액의조정(자회사의 주요경영사항)'))
        self.assertEqual(D.classify('주요사항보고서(전환사채권발행결정)'), 'convertible')
        self.assertEqual(D.KINDS['cv_adjust'][0], 'I'); self.assertNotIn('cv_adjust', FL.KINDS)              # 받아서 대조만, 계산하는 종류 아님


class FetchSnapshot(unittest.TestCase):
    def test_cli_fetches_only_snapshot_companies_into_samples(self):
        rows = {'001': [{'rcept_no': '20240301000001', 'report_nm': '전환가액의조정', 'rcept_dt': '20240301', 'flr_nm': '가나'},
                        {'rcept_no': '20240301000002', 'report_nm': '현금ㆍ현물배당결정', 'rcept_dt': '20240301', 'flr_nm': '가나'}],
                '002': [{'rcept_no': '20240401000003', 'report_nm': '전환가액의조정(자회사의 주요경영사항)', 'rcept_dt': '20240401', 'flr_nm': '다라'}]}
        calls = []

        def get(url, *a, **k):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)); calls.append(q)
            if 'document.xml' in url:
                b = io.BytesIO()
                with zipfile.ZipFile(b, 'w') as z:
                    z.writestr('a.xml', '<html><body><table><tr><td>전환가액의 조정</td></tr></table></body></html>')
                return b.getvalue()
            self.assertEqual(q['pblntf_ty'], 'I')
            rs = rows.get(q['corp_code'], [])
            return json.dumps({'status': '000', 'list': rs, 'total_page': 1} if rs else {'status': '013'}).encode()
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as data:
            cos = [{'ticker': '111111', 'corp_code': '001', 'name': '가나'}, {'ticker': '222222', 'corp_code': '002', 'name': '다라'}]
            env = {'MODU_NODES_DART_SAMPLES': d, 'DART_API_KEY': 'SECRETKEY', 'MODU_NODES_DATA_DIR': data}
            out = io.StringIO()
            with mock.patch.dict(os.environ, env), mock.patch.object(D, '_companies', lambda tickers=None: cos), mock.patch.object(D, 'http_get', get), \
                    mock.patch('time.sleep', lambda s: None), mock.patch('sys.stdout', out):
                self.assertEqual(DS.main(['fetch-snapshot', '--kinds', 'cv_adjust', '--from', '2021-10-01', '--to', '2026-11-12']), 0)
            man = D.load_manifest(d)
            self.assertEqual(list(man['docs']), ['20240301000001']); self.assertEqual(man['docs']['20240301000001']['kind'], 'cv_adjust')
            self.assertEqual({q['corp_code'] for q in calls if 'corp_code' in q}, {'001', '002'})          # 회사마다 목록을 훑음
            txt = out.getvalue() + Path(d, 'manifest.json').read_text(encoding='utf-8')
            self.assertNotIn('SECRETKEY', txt); self.assertIn('엔진 시세 사본의 국내 회사 2곳', txt); self.assertIn('해시 대조: 1건 중 다른 것 0건', txt)
            from mrn import autocheck as AC
            from mrn.store import Store
            self.assertEqual(AC.usage(Store(data))['calls'], len(calls))                                  # 사용량 계측에 올라감
            self.assertNotEqual(Path(d), D.docs_dir())

    def test_bad_kind_refused(self):
        out = io.StringIO()
        with mock.patch('sys.stdout', out):
            self.assertEqual(DS.main(['fetch-snapshot', '--kinds', 'nope', '--from', '2021-10-01']), 1)
        self.assertIn('받는 종류 이름이 아닙니다', out.getvalue())



class Parse(unittest.TestCase):
    def test_two_forms(self):
        from mrn import filing3 as F3
        from tests.test_v038_filing import html
        a = F3.parse_adjustment(html([['전환가액의 조정'], ['1. 조정에 관한 사항', '회차', '상장여부', '조정전 전환가액 (원)', '조정후 전환가액 (원)', '7', '비상장', '16,819', '15,066'],
                                       ['2. 전환가능주식수 변동'], ['3. 조정사유', '시가하락에 따른 전환가액 조정'], ['5. 조정가액 적용일', '2022-08-12']]))
        self.assertEqual((a['date'], a['market_drop'], a['rows']), ('2022-08-12', True, [{'series': '7', 'pre': 16819, 'post': 15066}]))
        b = F3.parse_adjustment(html([['1. 구분', '교환가액의 조정'], ['3. 조정에 관한 사항', '회차', '조정전 가액(원)', '조정후 가액(원)', '79', '429,650', '416,462'],
                                       ['4. 전환ㆍ행사ㆍ교환가능 주식수 변동'], ['5. 조정사유', '현금배당에 따른 교환가액 조정'], ['7. 조정가액 적용일', '2026-02-26']]))
        self.assertEqual((b['date'], b['market_drop'], b['rows']), ('2026-02-26', False, [{'series': '79', 'pre': 429650, 'post': 416462}]))


SAMPLES = Path(__file__).resolve().parents[2] / '_sources' / 'dart_docs_samples'


def _cases():
    """표본의 시가하락 조정 공시 + 엔진 시세 사본 → (회사, 적용일, 조정 전, 조정 후, 시세 줄)."""
    from mrn import filing3 as F3, market as M
    if not (SAMPLES / 'manifest.json').is_file():
        return []
    man = D.load_manifest(SAMPLES); out = []
    try:
        mroot = M.resolve(''); mman = M.load_manifest(mroot)
    except Exception:
        return []
    for no, d in sorted(man['docs'].items()):
        if d['kind'] != 'cv_adjust':
            continue
        a = F3.parse_adjustment('\n'.join(t for _, t in D.open_doc(no, SAMPLES, man)[0]))
        if not a['market_drop'] or not a['rows']:
            continue
        try:
            rows, _ = M.read_rows(mroot, mman, 'price_daily', d['ticker'])
        except M.SnapshotError:
            continue
        R = F3._rows(sorted((r for r in rows if r.get('source') == 'fsc'), key=lambda r: str(r['trade_date'])))
        out.append((d['name'], a['date'], a['rows'][0]['pre'], a['rows'][0]['post'], R))
    return out


@unittest.skipUnless(len(_cases()) >= 6, '이 PC에 「전환가액의 조정」 표본(시가하락 6건 이상)과 시세 사본이 있을 때만')
class RealRefix(unittest.TestCase):
    def test_engine_formula_reproduces_company_adjustments(self):
        """회사가 실제로 정한 시가하락 조정 가액을 엔진 식(조정일 전 거래일 기준 시가산정액, 원 단위 올림)으로 다시 계산한다.
        2026-11-12 PC 결과: 6건 중 3건 원 단위까지 같음 · 1건 4원(0.03%) 차이 · 2건은 계산값이 공시 값보다 낮음(최저 조정가액에 걸린 경우)."""
        from mrn import filing3 as F3
        same = near = floored = other = 0
        for name, day, pre, post, R in _cases():
            d = F3._trading_before(R, day, 1)
            m, w, last = F3._vwap(R, F3._back(d, months=1), d), F3._vwap(R, F3._back(d, days=7), d), F3._vwap(R, d, d)
            mine = F3._refix_once(pre, max((m + w + last) / 3, last), 0, pre, False)
            if mine == post:
                same += 1
            elif abs(mine - post) / post <= 0.0005:
                near += 1
            elif mine < post and abs(post / 0.7 - round(post / 0.7)) * 0.7 < 1:   # 공시 값 = (어떤 원 단위 가액 × 70%)를 올림한 값 → 최저 조정가액
                floored += 1
            else:
                other += 1
        self.assertGreaterEqual(same, 3); self.assertEqual(other, 0, (same, near, floored, other))
        self.assertEqual(same + near + floored, len(_cases()))

if __name__ == '__main__':
    unittest.main()
