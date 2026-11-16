"""v0.38 T2-4e 자동 연결(PM 결정 ①): 자동 확인이 관심회사 1등급 공시(앱이 계산하는 종류)의 원문을 받아 미리 계산해 둔다.
- 목록에서 본 줄로 원문만 받음(목록 재호출 없음) · 사본에 「자동 확인이 받음」 · 다시 돌려도 다시 받지 않음.
- 사용량 상한(원문 70%)에 닿으면 받기만 멈추고 목록 결과는 그대로 · 한 번에 받는 건수 상한 · 끄기(MODU_AUTO_DOCS=0).
- 자회사 공시·계산하지 않는 종류는 받지 않음 · 받기 실패는 그 줄에만 표시.
- 미리 계산(J24)은 결과를 저장하지 않고, 카드는 같은 숫자를 새로 계산한다. 출처에 「자동 확인이 받음」과 처음 본 시각이 보인다."""
import io, json, os, tempfile, urllib.parse, zipfile
from datetime import datetime
from pathlib import Path

from mrn import autocheck as AC, dartdocs as D
from tests.test_easy import EasyBase, CUT
from tests.test_v038_filing import DOCS, CO

COS = {CO: {'ticker': CO, 'corp_code': '00161383', 'name': '한미반도체'}}
WHEN = '2026-07-25T03:00:00+00:00'                     # 한국 날짜 2026-07-25 — 처음 등록이라 최근 7일(07-18~)만 목록을 봄: 07-20 소각·자기주식 취득
IN_WINDOW = ['20260720800001', '20260720000002']          # 07-14 잠정실적은 목록 범위 밖이라 받지 않음
SUB = '20260721800099'


def zipped(no, body):
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        z.writestr(f'{no}.xml', body.encode('utf-8'))
    return b.getvalue()


class Fake:
    def __init__(self):
        self.calls, self.bad = [], set()
        self.rows = [{'rcept_no': no, 'report_nm': nm, 'rcept_dt': no[:8], 'flr_nm': '한미반도체', 'rm': ''} for no, (_, nm, _) in DOCS.items()]
        self.rows.append({'rcept_no': SUB, 'report_nm': '현금ㆍ현물배당결정(자회사의 주요경영사항)', 'rcept_dt': SUB[:8], 'flr_nm': '한미반도체', 'rm': ''})
        self.rows.append({'rcept_no': '20260722000010', 'report_nm': '임원ㆍ주요주주특정증권등소유상황보고서', 'rcept_dt': '20260722', 'flr_nm': '누구', 'rm': ''})

    def __call__(self, url, *a, **k):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)); self.calls.append((url.split('?')[0].rsplit('/', 1)[-1], q))
        if 'document.xml' in url:
            no = q['rcept_no']
            if no in self.bad or no not in DOCS:
                return b'{"status":"014","message":"x"}'
            return zipped(no, DOCS[no][2])
        rs = sorted((r for r in self.rows if q['bgn_de'] <= r['rcept_dt'] <= q['end_de']), key=lambda r: r['rcept_no'])
        return json.dumps({'status': '000', 'list': rs, 'total_page': 1} if rs else {'status': '013'}).encode()

    def docs(self):
        return [q['rcept_no'] for n, q in self.calls if n == 'document.xml']


class Auto(EasyBase):
    def setUp(self):
        super().setUp()
        self.dd = tempfile.TemporaryDirectory(); os.environ['MODU_NODES_DART_DOCS'] = self.dd.name
        self.st = self.c.app.state.store; AC.ensure(self.st); self.fake = Fake()
        with self.st.lock, self.st.connect() as c:
            c.execute('INSERT INTO watchlist(owner_id,ticker,added_at) VALUES(?,?,?)', ('o1', CO, '2026-07-01T00:00:00+00:00'))

    def tearDown(self):
        os.environ.pop('MODU_NODES_DART_DOCS', None); self.dd.cleanup()
        super().tearDown()

    def check(self, when=WHEN, **env):
        return AC.check_once(self.st, 'manual', clock=lambda: datetime.fromisoformat(when), get=self.fake, env={'DART_API_KEY': 'k', **env}, companies=COS)

    def seen(self):
        with self.st.lock, self.st.connect() as c:
            return {r['rcept_no']: dict(r) for r in c.execute('SELECT * FROM filing_seen')}

    def test_fetches_window_grade1_and_prepares(self):
        r = self.check()
        self.assertEqual(r['status'], 'ok', r)
        self.assertEqual(sorted(self.fake.docs()), sorted(IN_WINDOW))                 # 14일 안 계산 종류만, 자회사·지분 공시는 받지 않음
        self.assertEqual((r['docs'], r['prepared']), (2, 2))
        self.assertIn('원문 자동 받기 2건', r['message'])
        man = D.load_manifest(self.dd.name)
        self.assertEqual({no: man['docs'][no]['added_by'] for no in IN_WINDOW}, {no: 'auto' for no in IN_WINDOW})
        s = self.seen()
        for no in IN_WINDOW:
            self.assertEqual((s[no]['doc_state'], s[no]['prep_state']), ('got', 'ready'), s[no])
        self.assertEqual(s[SUB]['doc_state'], 'skipped')
        self.assertIsNone(s['20260722000010']['doc_state'])                             # 계산하지 않는 종류는 손대지 않음
        n = len(self.fake.calls)
        r2 = self.check('2026-07-25T05:00:00+00:00')
        self.assertEqual(r2['docs'], 0)                                                  # 다시 받지 않음
        self.assertEqual([c for c in self.fake.calls[n:] if c[0] == 'document.xml'], [])

    def test_usage_cap_stops_docs_only(self):
        with self.st.lock, self.st.connect() as c:                                   # 오늘 이미 5회 씀 — 원문 상한 5회(100회의 5%), 목록 상한 95회
            c.execute("INSERT INTO dart_usage(day,calls) VALUES('2026-07-25',5)")
        r = self.check(MODU_DART_DAILY_LIMIT='100', MODU_DART_DOC_STOP='0.05')
        self.assertEqual(r['status'], 'ok')
        self.assertIn('원문 자동 받기를 멈춤', r['notes']); self.assertEqual((r['docs'], self.fake.docs()), (0, []))
        self.assertEqual(r['done'], 1)                                                   # 목록 확인은 끝까지
        r3 = self.check('2026-07-25T05:00:00+00:00')                                    # 상한이 풀리면 이어서 받음
        self.assertEqual(sorted(set(self.fake.docs())), sorted(IN_WINDOW))
        self.assertTrue(all(self.seen()[no]['doc_state'] == 'got' for no in IN_WINDOW))

    def test_budget_and_switch(self):
        r = self.check(MODU_AUTO_DOCS_MAX='1')
        self.assertEqual(r['docs'], 1); self.assertIn('한 번에 1건까지', r['notes'])
        self.assertEqual(self.fake.docs(), ['20260720800001'])                         # 최근 것(접수번호 큰 것)부터
        self.assertEqual(len(self.fake.docs()), 1)
        r = self.check('2026-07-25T04:00:00+00:00', MODU_AUTO_DOCS='0')
        self.assertEqual((r['docs'], len(self.fake.docs())), (0, 1))

    def test_failed_doc_marks_row_only(self):
        self.fake.bad.add('20260720000002')
        r = self.check()
        self.assertEqual(r['status'], 'ok'); self.assertEqual(r['docs'], 1)
        s = self.seen()['20260720000002']
        self.assertEqual(s['doc_state'], 'failed'); self.assertTrue(s['doc_note'])
        for h in ('04', '05', '06', '07'):
            self.check(f'2026-07-25T{h}:00:00+00:00')
        self.assertEqual(self.fake.docs().count('20260720000002'), 3)                   # 원문이 늦게 열리는 경우를 위해 3번까지만 다시(그 뒤는 카드 단추로)
        self.assertEqual(self.seen()['20260720000002']['doc_tries'], 3)

    def test_card_after_auto_fetch_same_numbers_and_provenance(self):
        no = '20260720000002'
        self.check()
        n = len(self.fake.calls)
        r = self.c.post('/api/watch/fetch', json={'ticker': CO, 'rcept_no': no})          # 「숫자로 보기」 — 이미 받았으니 DART를 부르지 않음
        self.assertEqual(r.status_code, 200, r.text); self.assertFalse(r.json()['new'])
        rid = self.c.post('/api/easy/run', json={'card': 'filing', 'company': CO, 'cutoff': CUT, 'rcept_no': no}).json()['id']
        self.wait(rid)
        a = self.c.get(f'/api/easy/answer/{rid}').json()
        s = next(x for x in a['sources'] if x.get('rcept_no') == no)
        self.assertTrue(any(x.endswith('· 자동 확인이 받음') for x in s['detail']), s['detail'])
        self.assertTrue(s['detail'][-1].startswith('앱이 공시 목록에서 처음 본 시각 2026-07-25 12:00 (한국 시각)'), s['detail'][-1])
        st, note = AC.prepare(CO, no)
        self.assertEqual(st, 'ready'); self.assertIn(f"숫자 {sum(1 for i in a['items'] if i['node_type'] == 'N20')}줄", note)   # 미리 계산과 카드의 줄 수가 같음
        board = AC.status(self.st, [CO], env={'DART_API_KEY': 'k'})                   # 화면이 받는 것과 같은 상태 묶음
        row = next(x for x in board['recent'] if x['rcept_no'] == no)
        self.assertEqual((row['doc_state'], row['prep_state']), ('got', 'ready'))
        self.assertIn('원문까지 받아 미리 계산', board['note'])

    def test_web_shows_doc_state(self):
        with open(os.path.join(os.path.dirname(__file__), '..', 'web', 'watch.js'), encoding='utf-8') as f:
            js = f.read()
        for t in ('function wDoc', '원문 받음 · 미리 계산함', '원문 자동 받기 실패', '${wDoc(x)}'):
            self.assertIn(t, js)
