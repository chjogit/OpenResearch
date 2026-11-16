"""v0.35: 증권사 비교 API가 행마다 종목코드를 주고, 회사 이름 표를 준다(화면이 종목별로 나눠 그리기 위함)."""
import os
import pathlib
import tempfile
import unittest
from fastapi.testclient import TestClient

FIX = pathlib.Path(os.environ.get('MODU_NODES_BROKER_DIR') or pathlib.Path(__file__).resolve().parents[2] / '_sources' / 'broker_reports_fixture')  # 모듈을 읽을 때의 값으로 고정
try:
    import pymupdf  # noqa: F401
    HAVE = FIX.exists() and any(FIX.glob('*.pdf'))
except ImportError:
    HAVE = False


@unittest.skipUnless(HAVE, 'broker PDFs or PyMuPDF not available')
class V035TickerSplit(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get('MODU_NODES_BROKER_DIR')
        os.environ['MODU_NODES_BROKER_DIR'] = str(FIX)   # 다른 시험이 바꿔 둔 값에 기대지 않음
        from mrn.server import create_app
        self.tmp = tempfile.TemporaryDirectory()
        self.c = TestClient(create_app(self.tmp.name, port=4395))
        self.c.get('/api/health')
        self.c.headers['X-CSRF-Token'] = self.c.cookies.get('mrn_csrf')
        self.c.post('/api/broker/scan')

    def tearDown(self):
        self.tmp.cleanup()
        if self._old is None:
            os.environ.pop('MODU_NODES_BROKER_DIR', None)
        else:
            os.environ['MODU_NODES_BROKER_DIR'] = self._old

    def test_rows_carry_ticker_and_names(self):
        d = self.c.get('/api/broker/compare').json()
        self.assertTrue(d['rows'])
        self.assertTrue(all('ticker' in r for r in d['rows']))
        self.assertTrue(any(r['ticker'] for r in d['rows']))
        self.assertIsInstance(d['companies'], dict)
        self.assertTrue(set(d['companies']) <= {r['ticker'] for r in d['rows']})
        for k in ('columns', 'rows', 'summary', 'timeline', 'notice'):   # 기존 응답 칸은 그대로
            self.assertIn(k, d)

    def test_static_script_is_linked(self):
        self.assertIn('tp_timeline.js', self.c.get('/expert').text)
        js = self.c.get('/static/tp_timeline.js').text
        self.assertIn('컨센서스가 아닙니다', js)
        self.assertNotIn('매수', js)


if __name__ == '__main__':
    unittest.main()
