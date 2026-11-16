"""T1: whole-report retrieval index + DART OpenAPI (XBRL) numbers with cross-check."""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

SRC = os.environ.get('MODU_NODES_DART_FULL') or str(Path(__file__).resolve().parents[2] / '_sources' / 'dart_full')
HAVE_SRC = os.path.isdir(SRC) and any(p.endswith('.html') for p in os.listdir(SRC))


class Base(unittest.TestCase):
    def setUp(self):
        from mrn.server import create_app
        self.tmp = tempfile.TemporaryDirectory()
        os.environ['MODU_NODES_DART_FULL'] = SRC
        self.c = TestClient(create_app(self.tmp.name, port=4395))
        self.c.get('/api/health')
        self.c.headers['X-CSRF-Token'] = self.c.cookies.get('mrn_csrf')

    def tearDown(self):
        self.tmp.cleanup()


@unittest.skipUnless(HAVE_SRC, 'dart_full sources not available')
class Rag(Base):
    def test_index_and_search_are_source_pinned(self):
        st = self.c.get('/api/rag/status').json()
        self.assertTrue(st['ready'])
        self.assertEqual(st['rejected'], [])
        self.assertEqual(set(st['companies']), {'삼성전자', 'SK하이닉스'})
        r = self.c.post('/api/rag/search', json={'query': '직원 수와 평균 근속연수', 'company': '005930', 'k': 5}).json()
        self.assertEqual(r['mode'], 'bm25')                      # no vectors in tests -> honestly reported
        self.assertIn('BM25', r['note'])
        top = r['hits'][0]
        self.assertEqual(top['company'], '삼성전자')
        self.assertTrue(top['source']['file'] and top['source']['url'].startswith('https://dart.fss.or.kr/'))
        self.assertTrue(any('128,881' in h['text'] for h in r['hits']))
        self.assertEqual(top['path'][-1], '바. 직원 등의 현황')          # sibling headings do not pile up

    def test_company_filter(self):
        r = self.c.post('/api/rag/search', json={'query': '연결 매출액 영업이익', 'company': '000660', 'k': 10}).json()
        self.assertTrue(r['hits'])
        self.assertTrue(all(h['company'] == 'SK하이닉스' for h in r['hits']))

    def test_eval_recall(self):
        e = self.c.get('/api/rag/eval').json()
        self.assertEqual(e['with_synonyms']['summary']['all']['@10'], '16/16')
        self.assertEqual(e['with_synonyms']['summary']['all']['@5'], '16/16')
        self.assertIn('답변 정확도가 아님', e['with_synonyms']['definition'])


def fixture(code='005930', year=2025):
    rows = [
        ('IS', 'ifrs-full_Revenue', '매출액', '333,605,938,000,000', '300,870,903,000,000'),
        ('IS', 'dart_OperatingIncomeLoss', '영업이익', '43,601,051,000,000', '32,725,961,000,000'),
        ('CF', 'ifrs-full_CashFlowsFromUsedInOperatingActivities', '영업활동현금흐름', '1', '2'),
        ('IS', 'ifrs-full_BasicEarningsLossPerShare', '기본주당이익', '6,605', '4,950'),
    ]
    return {'status': '000', 'message': '정상', 'list': [{'rcept_no': '20260310002820', 'sj_div': s, 'account_id': a, 'account_nm': n,
            'thstrm_amount': t, 'frmtrm_amount': f, 'currency': 'KRW'} for s, a, n, t, f in rows]}


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Xbrl(Base):
    def test_parse_units_and_crosscheck(self):
        from mrn.xbrl import parse
        f = {x['fact_id']: x for x in parse(fixture(), '005930', 2025)}
        self.assertEqual(f['xbrl:005930:2025:revenue']['value'], '333605938')
        self.assertEqual(f['xbrl:005930:2024:revenue']['value'], '300870903')
        self.assertEqual(f['xbrl:005930:2025:eps']['unit'], '원')
        self.assertEqual(f['xbrl:005930:2025:eps']['value'], '6605')

    def test_fetch_caches_and_never_leaks_key(self):
        import mrn.xbrl as X
        os.environ['DART_API_KEY'] = 'SECRET-KEY-123'
        calls = []

        def opener(url, timeout=30):
            calls.append(url)
            return FakeResp(json.dumps(fixture()).encode())
        try:
            d1, i1 = X.fetch(self.tmp.name, '005930', 2025, opener=opener)
            d2, i2 = X.fetch(self.tmp.name, '005930', 2025, opener=opener)
            self.assertEqual(len(calls), 1)                        # second call served from cache
            self.assertTrue(i2['cached'])
            cached = Path(self.tmp.name, 'xbrl', i1['file']).read_text(encoding='utf-8')
            self.assertNotIn('SECRET-KEY-123', cached)

            def bad(url, timeout=30):
                raise OSError(f'connection refused for {url}')
            with self.assertRaises(X.XbrlError) as cm:
                X.fetch(self.tmp.name, '000660', 2025, opener=bad)
            self.assertNotIn('SECRET-KEY-123', str(cm.exception))
            self.assertIn('***', str(cm.exception))
        finally:
            del os.environ['DART_API_KEY']

    def test_endpoint_without_key_and_crosscheck_with_cache(self):
        os.environ.pop('DART_API_KEY', None)
        r = self.c.post('/api/xbrl/fetch', json={'company': '005930', 'year': 2025})
        self.assertEqual(r.status_code, 502)
        self.assertIn('DART_API_KEY', r.json()['detail'])
        os.makedirs(os.path.join(self.tmp.name, 'xbrl'), exist_ok=True)
        with open(os.path.join(self.tmp.name, 'xbrl', '005930_2025_11011_CFS.json'), 'w', encoding='utf-8') as f:
            json.dump(fixture(), f)
        r = self.c.post('/api/xbrl/fetch', json={'company': '005930', 'year': 2025}).json()
        cc = {(x['metric'], x['year']): x for x in r['crosscheck']}
        self.assertTrue(cc[('revenue', 2025)]['match'])
        self.assertTrue(cc[('operatingProfit', 2025)]['match'])
        self.assertFalse(cc[('cfo', 2025)]['match'])             # fixture value deliberately wrong -> mismatch surfaced
        self.assertFalse(self.c.get('/api/xbrl/status').json()['key_configured'])


if __name__ == '__main__':
    unittest.main()
