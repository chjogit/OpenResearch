"""v0.18: 증권사 전망 추이·집계(T13·N16), 받은 편지함 등록(T2), 모두의 가정(C). 원칙을 시험으로 고정한다."""
import os as _os, pathlib as _pl
_os.environ.setdefault('MODU_NODES_BROKER_DIR', str(_pl.Path(__file__).resolve().parents[2] / '_sources' / 'broker_reports_fixture'))  # v0.22: 시험은 고정된 원래 보고서 15건으로
import hashlib, json, os, tempfile, unittest
from pathlib import Path
from fastapi.testclient import TestClient
from mrn import forecasts as FC
from mrn import broker as BR
from mrn.easy import plan, CARDS, card_status
from mrn.workflow import WorkflowDoc, validate, blocking
from mrn import nodes as N
from tests.test_kit2_events import Base, nd, ed
from tests.test_universe import CUT


def fc(b, d, v, m='operatingProfit', fy=2026):
    return {'broker': b, 'report_date': d, 'metric': m, 'fiscal_year': fy, 'value': str(v), 'id': f'{b}{d}{m}'}


class Trend(unittest.TestCase):
    def setUp(self):
        self.F = [fc('A', '2026-01-10', 100), fc('B', '2026-03-01', 120), fc('C', '2026-06-01', 110),
                  fc('A', '2026-06-15', 130), fc('B', '2026-06-20', 120.2), fc('D', '2026-07-01', 90, fy=2027)]

    def test_latest_per_broker_and_stale(self):
        tr = FC.trend(self.F, 'operatingProfit', 2026)
        p = FC.as_of(tr, '2026-06-01')
        # A(1/10)는 120일이 넘어 빠지고, B(3/1)·C(6/1)만
        self.assertEqual(p['brokers'], ['B', 'C'])
        self.assertEqual(p['n'], 2)
        self.assertTrue(p['thin'])
        last = tr['latest']
        self.assertEqual(last['brokers'], ['A', 'B', 'C'])
        self.assertEqual(last['median'], '120.2')
        self.assertEqual((last['min'], last['max']), ('110', '130'))
        self.assertFalse(last['thin'])

    def test_point_in_time(self):
        tr = FC.trend(self.F, 'operatingProfit', 2026, until='2026-06-10')
        self.assertEqual(tr['latest']['date'], '2026-06-01')
        self.assertNotIn('2026-06-15', [s['date'] for s in tr['series']])

    def test_revisions_same_broker_only(self):
        rv = FC.trend(self.F, 'operatingProfit', 2026)['revisions']
        self.assertEqual([r['broker'] for r in rv['up']], ['A'])
        self.assertEqual([r['broker'] for r in rv['flat']], ['B'])        # 120 → 120.2 (+0.17%)는 유지
        self.assertEqual(rv['down'], [])

    def test_versus_actual_uses_day_before(self):
        tr = FC.trend(self.F, 'operatingProfit', 2026)
        v = FC.versus_actual(tr, '125', '2026-06-15')                      # 공시 당일 나온 A 보고서는 쓰지 않음
        self.assertEqual(v['aggregate_date'], '2026-06-01')
        self.assertEqual(v['median'], '115')
        self.assertFalse(v['inside_range'])

    def test_never_called_consensus(self):
        self.assertIn('컨센서스(공식 시장 예상치)가 아니며', FC.NOTICE)


class Crowd(unittest.TestCase):
    def test_hidden_under_five(self):
        s = FC.crowd_stats([1, 2, 3, 4])
        self.assertFalse(s['shown'])
        self.assertNotIn('median', s)

    def test_only_median_and_quartiles(self):
        s = FC.crowd_stats([100, 200, 300, 400, 500])
        self.assertTrue(s['shown'])
        self.assertEqual(s['median'], '300')
        self.assertEqual(set(s), {'n', 'shown', 'min_n', 'median', 'q1', 'q3'})     # 최솟값·최댓값·개인 값 없음

    def test_value_guard(self):
        self.assertIsNone(FC.check_value('operatingProfit', '380000000', '369000000'))
        self.assertIn('너무 멀어요', FC.check_value('operatingProfit', '3800000000', '369000000'))
        self.assertIn('0보다', FC.check_value('revenue', '-1'))
        self.assertIn('매출액·영업이익만', FC.check_value('targetPrice', '1'))


def _write_pdf(path, text):
    import pymupdf
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text, fontname='korea')
    doc.save(path)


class Ledger(Base):
    def setUp(self):
        super().setUp()
        self.bdir = Path(self.tmp.name) / 'broker'
        (self.bdir / 'inbox').mkdir(parents=True)
        os.environ['MODU_NODES_BROKER_DIR'] = str(self.bdir)
        files = []
        for i, (d, b, v) in enumerate([('2026-09-01', 'A증권', 360000000), ('2026-09-20', 'B증권', 370000000),
                                       ('2026-10-05', 'C증권', 380000000), ('2026-11-20', 'D증권', 999000000)]):
            f = f'r{i}.pdf'
            _write_pdf(str(self.bdir / f), f'report {i}')
            sha = hashlib.sha256((self.bdir / f).read_bytes()).hexdigest()
            files.append({'파일명': f, 'sha256': sha, '증권사': b, '보고서일': d, '종목': '테스트(042700)'})
            with self.store.connect() as c:
                c.execute('INSERT INTO broker_reports VALUES(?,?,?,?)', (f, sha, json.dumps({'file': f, 'sha256': sha, 'broker': b, 'report_date': d, 'title': 't', 'target_price': '99999'}), 'x'))
                c.execute('INSERT INTO broker_candidates(id,file,sha256,data,state,extracted_at) VALUES(?,?,?,?,?,?)',
                          (f'{i}', f, sha, json.dumps({'id': f'{i}', 'file': f, 'sha256': sha, 'broker': b, 'report_date': d, 'metric': 'operatingProfit',
                                                       'metric_label': '영업이익', 'fiscal_year': 2026, 'value_mn': str(v), 'page': 1, 'quote': 'q'}),
                           'approved' if i != 2 else 'proposed', 'x'))
        (self.bdir / 'manifest.json').write_text(json.dumps({'files': files}, ensure_ascii=False), encoding='utf-8')

    def tearDown(self):
        os.environ.pop('MODU_NODES_BROKER_DIR', None)
        super().tearDown()

    def chain(self):
        return self.run_doc([nd('t13', 'T13', company='042700'), nd('n16', 'N16')], [ed('t13', 'ledger', 'n16', 'ledger')])

    def test_only_approved_and_before_cutoff(self):
        r = self.chain()
        st, p, why = r['t13']
        self.assertEqual(st, 'partial', why)                     # 미승인 1건 있음
        self.assertEqual({f['broker'] for f in p['forecasts']}, {'A증권', 'B증권'})     # C 미승인, D 기준 날짜 뒤
        self.assertEqual(p['excluded_after_cutoff'], 1)
        self.assertNotIn('99999', json.dumps(p, ensure_ascii=False))   # 목표주가는 담지 않음
        st, p, why = r['n16']
        self.assertEqual(st, 'succeeded', why)
        self.assertIn('컨센서스 아님', p['findings'][0]['claim'])
        self.assertIn('추이로 보지 마세요', p['findings'][0]['claim'])   # 2곳뿐

    def test_changed_pdf_excluded(self):
        (self.bdir / 'r0.pdf').write_bytes(b'changed')
        st, p, why = self.chain()['t13']
        self.assertEqual({f['broker'] for f in p['forecasts']}, {'B증권'})
        self.assertTrue(p['held'])

    def test_no_reports_held(self):
        r = self.run_doc([nd('t13', 'T13', company='005930')], [])
        self.assertEqual(r['t13'][0], 'held')

    def test_inbox_register(self):
        _write_pdf(str(self.bdir / 'inbox' / 'new.pdf'), 'KB증권 2026.10.12 (042700) 목표주가 200,000원 매수')
        items = BR.inbox_items()
        it = next(i for i in items if i['file'] == 'new.pdf')
        self.assertFalse(it['registered'])
        self.assertEqual(it['guess'].get('broker'), 'KB증권')
        self.assertEqual(it['guess'].get('ticker'), '042700')
        with self.assertRaises(ValueError):
            BR.register({'file': 'new.pdf', 'ticker': '42700', 'broker': 'KB증권', 'report_date': '2026-10-12'})
        rec = BR.register({'file': 'new.pdf', 'ticker': '042700', 'broker': 'KB증권', 'report_date': '2026-10-12', 'title': 'x'})
        self.assertTrue((self.bdir / rec['파일명']).exists())
        self.assertTrue((self.bdir / 'inbox' / 'new.pdf').exists())             # 원본은 그대로
        self.assertTrue(list(self.bdir.glob('manifest.json.bak-before-inbox*')))  # 처음 쓰기 전에 백업
        man = json.loads((self.bdir / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(man['files']), 5)
        self.assertEqual(BR.report_ticker(man['files'][-1]), '042700')
        with self.assertRaises(ValueError):
            BR.register({'file': 'new.pdf', 'ticker': '042700', 'broker': 'KB증권', 'report_date': '2026-10-12'})    # 같은 해시
        self.assertTrue(next(i for i in BR.inbox_items() if i['file'] == 'new.pdf')['registered'])

    def test_crowd_api_blind_first(self):
        from mrn.server import create_app
        app = create_app(os.path.join(self.tmp.name, 'db'))
        cl = TestClient(app)
        cl.get('/')
        tok = cl.cookies.get('mrn_csrf')
        r = cl.get('/api/crowd/042700/2026/operatingProfit').json()
        self.assertFalse(r['unlocked'])
        self.assertNotIn('stats', r)
        bad = cl.post('/api/crowd/submit', json={'ticker': '042700', 'fiscal_year': 2026, 'metric': 'targetPrice', 'value_jo': 1}, headers={'X-CSRF-Token': tok})
        self.assertEqual(bad.status_code, 422)
        ok = cl.post('/api/crowd/submit', json={'ticker': '042700', 'fiscal_year': 2026, 'metric': 'operatingProfit', 'value_jo': 365}, headers={'X-CSRF-Token': tok})
        self.assertEqual(ok.status_code, 200, ok.text)
        far = cl.post('/api/crowd/submit', json={'ticker': '042700', 'fiscal_year': 2026, 'metric': 'operatingProfit', 'value_jo': 9000}, headers={'X-CSRF-Token': tok})
        self.assertEqual(far.status_code, 422)                    # 승인 집계(365조 안팎)의 5배 밖
        r = cl.get('/api/crowd/042700/2026/operatingProfit').json()
        self.assertTrue(r['unlocked'])
        self.assertFalse(r['stats']['shown'])                     # 아직 1명
        self.assertEqual(r['mine']['value_mn'], '365000000')


class StoreCrowd(Base):
    def test_one_per_person_per_month_latest_counts(self):
        s = self.store
        s.crowd_submit('a', '005930', 2026, 'operatingProfit', '100', at='2026-10-01T00:00:00+00:00')
        s.crowd_submit('a', '005930', 2026, 'operatingProfit', '110', at='2026-10-20T00:00:00+00:00')   # 같은 달 → 바뀜
        s.crowd_submit('a', '005930', 2026, 'operatingProfit', '150', at='2026-11-02T00:00:00+00:00')   # 다음 달 → 새 기록
        s.crowd_submit('b', '005930', 2026, 'operatingProfit', '200', at='2026-10-05T00:00:00+00:00')
        self.assertEqual(sorted(s.crowd_values('005930', 2026, 'operatingProfit')), ['150', '200'])
        self.assertEqual(sorted(s.crowd_values('005930', 2026, 'operatingProfit', until='2026-10-31')), ['110', '200'])
        m = s.crowd_monthly('005930', 2026, 'operatingProfit')
        self.assertEqual(sorted(m['2026-10']), ['110', '200'])
        with s.connect() as c:
            det = [r['detail'] for r in c.execute("SELECT detail FROM audit WHERE action='crowd.submit'")]
        self.assertTrue(det and all('150' not in d and '110' not in d for d in det))   # 감사 기록에 값 없음


class Card(unittest.TestCase):
    def test_card(self):
        c = next(c for c in CARDS if c['id'] == 'forecasts')
        self.assertFalse(card_status(c, '042700', {}, set())[0])
        self.assertTrue(card_status(c, '005930', {}, {'005930'})[0])
        d = WorkflowDoc.model_validate(plan('forecasts', '005930', CUT))
        self.assertEqual(blocking(validate(d, N.check_assumptions)), [])
        self.assertEqual({n.type for n in d.nodes}, {'T13', 'T11', 'N16', 'T05'})
