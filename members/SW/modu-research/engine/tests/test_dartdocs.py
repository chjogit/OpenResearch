"""D3: DART 원문 근거층 — 받기(가짜 응답) · 이어 받기 · 해시 대조 · 기준시점 · 키 비노출."""
import io, json, os, tempfile, unittest, zipfile
from urllib.parse import urlparse, parse_qs
from mrn import dartdocs as D

KEY = 'SECRETKEY1234567890'
CO = [{'ticker': '068270', 'corp_code': '00413046', 'name': '셀트리온'}]
LIST = {'B': [{'report_nm': '주요사항보고서(자기주식취득결정)', 'rcept_no': '20260831000538', 'rcept_dt': '20260831', 'flr_nm': '셀트리온', 'rm': ''},
              {'report_nm': '주요사항보고서(자기주식취득신탁계약체결결정)', 'rcept_no': '20260701000001', 'rcept_dt': '20260701', 'flr_nm': '셀트리온', 'rm': ''},
              {'report_nm': '주요사항보고서(회사합병결정)', 'rcept_no': '20260601000009', 'rcept_dt': '20260601', 'flr_nm': '셀트리온', 'rm': ''}],
        'E': [{'report_nm': '자기주식취득결과보고서', 'rcept_no': '20260916000002', 'rcept_dt': '20260916', 'flr_nm': '셀트리온', 'rm': ''}],
        'I': [{'report_nm': '주식소각결정', 'rcept_no': '20260916800015', 'rcept_dt': '20260916', 'flr_nm': '셀트리온', 'rm': '유'}],
        'A': [{'report_nm': '반기보고서 (2026.06)', 'rcept_no': '20260814000111', 'rcept_dt': '20260814', 'flr_nm': '셀트리온', 'rm': ''}]}


def zbytes(no):
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        z.writestr(f'{no}.xml', f'<DOCUMENT><P>접수 {no} 본문 — 취득 총액 1,000억 원</P></DOCUMENT>'.encode('utf-8'))
    return b.getvalue()


EXTRA_ALL = [{'report_nm': '임원ㆍ주요주주특정증권등소유상황보고서', 'rcept_no': '20261106000440', 'rcept_dt': '20261106', 'flr_nm': '김씨', 'rm': ''}]   # 지분공시(D) — 모든 유형 목록에만


class Fake:
    def __init__(self, limit_after=None, missing=()):
        self.calls, self.limit_after, self.missing = [], limit_after, set(missing)

    def __call__(self, url, timeout=60):
        u = urlparse(url); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        assert q['crtfc_key'] == KEY
        self.calls.append((u.path.rsplit('/', 1)[-1], q.get('pblntf_ty') or q.get('rcept_no')))
        if u.path.endswith('list.json'):
            rows = LIST.get(q['pblntf_ty'], []) if 'pblntf_ty' in q else [r for v in LIST.values() for r in v] + EXTRA_ALL
            return json.dumps({'status': '000' if rows else '013', 'total_page': 1, 'list': rows}).encode()
        n_docs = sum(1 for c in self.calls if c[0] == 'document.xml')
        if self.limit_after is not None and n_docs > self.limit_after:
            return b'<?xml version="1.0"?><result><status>020</status><message>limit</message></result>'
        if q['rcept_no'] in self.missing:
            return b'<?xml version="1.0"?><result><status>014</status><message>none</message></result>'
        return zbytes(q['rcept_no'])


class DartDocs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = os.path.join(self.tmp.name, 'dart_docs'); self.env = {'DART_API_KEY': KEY}
        self.logs = []

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, fake, **kw):
        return D.fetch(CO, out_root=self.root, get=fake, env=self.env, sleep=0, log=self.logs.append, **kw)

    def test_fetch_classify_resume_and_no_key_anywhere(self):
        f = Fake(); self.assertEqual(self.fetch(f), 5)                       # 합병은 대상 아님(v0.38 T2-3: 유상증자는 받는 종류가 됨)
        man = D.load_manifest(self.root)
        self.assertEqual({d['kind'] for d in man['docs'].values()}, {'buyback_decision', 'buyback_trust', 'buyback_result', 'retire', 'periodic'})
        self.assertEqual(man['docs']['20260916000002']['rcept_dt'], '2026-09-16')
        f2 = Fake(); self.assertEqual(self.fetch(f2), 0)                      # 이어 받기: 원문은 다시 부르지 않음
        self.assertFalse([c for c in f2.calls if c[0] == 'document.xml'])
        blob = b''.join(open(os.path.join(self.root, n), 'rb').read() for n in os.listdir(self.root)) + '\n'.join(map(str, self.logs)).encode()
        self.assertNotIn(KEY.encode(), blob)
        self.assertEqual(D.status(self.root)['docs'], 5); self.assertEqual(D.verify_all(self.root)['bad'], [])

    def test_open_doc_checks_hash_and_cutoff_filter(self):
        self.fetch(Fake())
        files, meta = D.open_doc('20260916000002', self.root)
        self.assertIn('취득 총액 1,000억 원', files[0][1]); self.assertEqual(len(meta['sha256']), 64)
        self.assertEqual([d['rcept_no'] for d in D.find('068270', 'buyback_result', '2026-09-15T16:00:00+09:00', self.root)], [])   # 기준시점 뒤 공시는 안 씀
        self.assertEqual(len(D.find('068270', None, '2026-09-16T16:00:00+09:00', self.root)), 5)
        with open(os.path.join(self.root, '20260916000002.zip'), 'ab') as fh:
            fh.write(b'x')
        with self.assertRaises(D.DartDocsError) as e:
            D.open_doc('20260916000002', self.root)
        self.assertEqual(e.exception.code, 'doc_mismatch')
        with open(os.path.join(self.root, 'manifest.json'), 'a', encoding='utf-8') as fh:
            fh.write(' ')
        with self.assertRaises(D.DartDocsError) as e:
            D.load_manifest(self.root)
        self.assertEqual(e.exception.code, 'manifest_mismatch')

    def test_daily_limit_stops_but_keeps_progress_and_missing_is_recorded(self):
        with self.assertRaises(D.DartDocsError) as e:
            self.fetch(Fake(limit_after=2))
        self.assertEqual(e.exception.code, 'dart_020'); self.assertNotIn(KEY, str(e.exception))
        self.assertEqual(D.status(self.root)['docs'], 2)                       # 받은 2건은 남음
        self.assertEqual(self.fetch(Fake(missing={'20260916800015'})), 2)     # 나머지 3건 중 1건은 DART에 파일 없음
        man = D.load_manifest(self.root)
        self.assertEqual(list(man['failed']), ['20260916800015']); self.assertEqual(man['failed']['20260916800015']['code'], 'dart_014')

    def test_no_key_and_no_docs_messages(self):
        with self.assertRaises(D.DartDocsError) as e:
            D.fetch(CO, out_root=self.root, get=Fake(), env={}, sleep=0)
        self.assertEqual(e.exception.code, 'no_key')
        with self.assertRaises(D.DartDocsError) as e:
            D.load_manifest(os.path.join(self.tmp.name, 'none'))
        self.assertEqual(e.exception.code, 'no_docs')


if __name__ == '__main__':
    unittest.main()


class FetchOne(unittest.TestCase):
    """v0.38 T1: 사용자가 넣은 접수번호 하나 받기."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = os.path.join(self.tmp.name, 'dart_docs'); self.env = {'DART_API_KEY': KEY}

    def tearDown(self):
        self.tmp.cleanup()

    def one(self, no, fake=None, ticker='068270', **kw):
        return D.fetch_one(ticker, no, out_root=self.root, get=fake or Fake(), env=self.env, company=CO[0], **kw)

    def test_fetch_one_checks_list_then_stores_like_bulk(self):
        f = Fake()
        d, new = self.one('20260916800015', f)
        self.assertTrue(new); self.assertEqual(d['kind'], 'retire'); self.assertEqual(d['added_by'], 'manual'); self.assertEqual(d['rcept_dt'], '2026-09-16')
        self.assertEqual([c[0] for c in f.calls][-1], 'document.xml')
        files, meta = D.open_doc('20260916800015', self.root)                 # 대량 받기와 같은 해시 대조로 열린다
        self.assertIn('20260916800015', files[0][1])
        d2, new2 = self.one('20260916800015', Fake())                         # 이미 있으면 다시 받지 않음(호출 0회)
        self.assertFalse(new2)
        self.assertEqual(D.find('068270', 'retire', root=self.root)[0]['rcept_no'], '20260916800015')

    def test_refusals(self):
        for no, code in (('2026', 'bad_rcept_no'), ('20260601000009', 'unsupported_kind'), ('20261106000440', 'unsupported_kind'), ('20260101000000', 'not_listed')):
            with self.assertRaises(D.DartDocsError) as e:
                self.one(no)
            self.assertEqual(e.exception.code, code, no)
            self.assertNotIn(KEY, str(e.exception))
        with self.assertRaises(D.DartDocsError) as e:
            D.fetch_one('068270', '20260916800015', out_root=self.root, get=Fake(), env={}, company=CO[0])
        self.assertEqual(e.exception.code, 'no_key')
        self.one('20260916800015')
        with self.assertRaises(D.DartDocsError) as e:
            self.one('20260916800015', ticker='005930')                       # 다른 회사 공시를 이 회사로 넣지 못함
        self.assertEqual(e.exception.code, 'other_company')

    def test_subsidiary_filing_refused(self):
        old = LIST['I']
        LIST['I'] = old + [{'report_nm': '주식소각결정(자회사의 주요경영사항)', 'rcept_no': '20260917800001', 'rcept_dt': '20260917', 'flr_nm': '셀트리온', 'rm': ''}]
        try:
            with self.assertRaises(D.DartDocsError) as e:
                self.one('20260917800001')
            self.assertEqual(e.exception.code, 'subsidiary')
            self.assertFalse(os.path.exists(os.path.join(self.root, '20260917800001.zip')))
        finally:
            LIST['I'] = old

    def test_new_kinds_and_listed_kept(self):
        self.assertEqual(D.classify('[기재정정]현금ㆍ현물배당결정'), 'dividend')
        self.assertEqual(D.classify('연결재무제표기준영업(잠정)실적(공정공시)'), 'prelim')
        self.assertIsNone(D.classify('주식배당결정'))
        D.fetch(CO, ['retire'], out_root=self.root, get=Fake(), env=self.env, sleep=0, log=lambda *_: None)
        D.fetch(CO, ['dividend', 'prelim'], out_root=self.root, get=Fake(), env=self.env, sleep=0, log=lambda *_: None)
        self.assertEqual(D.load_manifest(self.root)['listed']['068270']['kinds'], ['dividend', 'prelim', 'retire'])   # 앞서 받은 종류를 지우지 않음


class ReadWhileFetching(unittest.TestCase):
    """v0.38: 받는 중(목록·해시 파일을 다시 쓰는 중)에 읽어도 오류로 멈추지 않는다."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = os.path.join(self.tmp.name, 'dart_docs')
        D.fetch(CO, ['retire'], out_root=self.root, get=Fake(), env={'DART_API_KEY': KEY}, sleep=0, log=lambda *_: None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_hash_file_is_mismatch_not_crash(self):
        from pathlib import Path
        Path(self.root, 'manifest.sha256').write_text('', encoding='utf-8')
        with self.assertRaises(D.DartDocsError) as e:
            D.load_manifest(self.root)
        self.assertEqual(e.exception.code, 'manifest_mismatch')

    def test_hash_file_fixed_during_retry_is_read(self):
        import threading, time
        from pathlib import Path
        good = Path(self.root, 'manifest.sha256').read_text(encoding='utf-8')
        Path(self.root, 'manifest.sha256').write_text('', encoding='utf-8')
        threading.Timer(0.5, lambda: Path(self.root, 'manifest.sha256').write_text(good, encoding='utf-8')).start()
        self.assertIn('20260916800015', D.load_manifest(self.root)['docs'])
        self.assertFalse(Path(self.root, 'manifest.sha256.tmp').exists())
