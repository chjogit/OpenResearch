"""v0.38 T2-4d 출처 표시(P04-2) + PM 결정 ③(공시 숫자 화면만 사실 → 계산 → 추정).
- 답마다 공시 원문의 접수번호·받은 시각·받은 방법·앱이 처음 본 시각, 사본의 이용 범위가 보인다. 기록이 없으면 「기록 없음」(지어내지 않음).
- 기존 칸(what·snapshot·sha256·grade·file)은 그대로이고 더하기만.
- 다른 카드의 순서(추정 먼저)는 그대로."""
import json, os, tempfile
from datetime import datetime, timezone
from mrn import dartdocs as D, autocheck as AC
from mrn.easy import _kst, _prov, _seen_line, USE, TRADE_STATUS_NOTE
from tests.test_easy import EasyBase, CUT
from tests.test_v038_filing import make_docs, CO

NO_DIV = '20260806800005'
NO_BUY = '20260720000002'


class Helpers(EasyBase.__mro__[1]):          # unittest.TestCase
    def test_kst(self):
        self.assertEqual(_kst('2026-11-12T05:05:09+00:00'), '2026-11-12 14:05 (한국 시각)')
        self.assertEqual(_kst('2026-11-12T23:30:00Z'), '2026-11-13 08:30 (한국 시각)')            # 날짜가 넘어가는 경우
        self.assertEqual(_kst('2026-10-27T03:37:56.848761+00:00'), '2026-10-27 12:37 (한국 시각)')
        self.assertEqual(_kst('잘못된 값'), '잘못된 값')                                            # 못 읽으면 그대로(지어내지 않음)

    def test_prov_keeps_old_fields_and_adds(self):
        e = {'what': 'x', 'snapshot': 's', 'sha256': 'h', 'grade': 'public:fsc', 'file': 'f'}
        out = _prov(dict(e), {'collected_at_max': '2026-11-06T15:00:00+00:00'})
        self.assertEqual({k: out[k] for k in e}, e)
        self.assertEqual(out['use'], USE['public'])
        self.assertEqual(out['detail'], ['자료를 모은 시각(가장 늦은 줄) 2026-11-07 00:00 (한국 시각)'])
        self.assertEqual(_prov({'grade': '???'}, {})['use'], '이용 범위 확인 전')
        d = _prov({'grade': 'official'}, {'rcept_no': '1', 'url': 'u', 'fetched_at': '2026-11-12T00:00:00+00:00', 'how': 'auto'})
        self.assertEqual(d['detail'], ['DART 접수번호 1', '원문을 받은 시각 2026-11-12 09:00 (한국 시각) · 자동 확인이 받음'])
        self.assertEqual(_prov({'grade': 'official'}, {'rcept_no': '1', 'fetched_at': 'x', 'how': 'odd'})['detail'][1], '원문을 받은 시각 x · 받은 방법 기록 없음')
        self.assertEqual(_seen_line({'first_seen_at': '2026-11-12T01:00:00+00:00', 'prev_checked_at': '2026-11-12T00:00:00+00:00', 'first_check': False}),
                         '앱이 공시 목록에서 처음 본 시각 2026-11-12 10:00 (한국 시각) — 그 직전 확인은 2026-11-12 09:00 (한국 시각), 공시는 그 사이에 목록에 올라왔어요')
        self.assertIn('첫 확인 때 본 것이라', _seen_line({'first_seen_at': '2026-11-12T01:00:00+00:00', 'first_check': True}))
        self.assertEqual(_seen_line({'first_seen_at': '2026-11-12T01:00:00+00:00'}), '앱이 공시 목록에서 처음 본 시각 2026-11-12 10:00 (한국 시각)')
        self.assertIn('기록 없음', _seen_line(None))

    def test_seen_info_without_table_or_store(self):
        self.assertIsNone(AC.seen_info(None, '1'))


class Card(EasyBase):
    def setUp(self):
        super().setUp()
        self.docs = tempfile.TemporaryDirectory(); os.environ['MODU_NODES_DART_DOCS'] = os.path.join(self.docs.name, 'dart_docs')
        make_docs(os.environ['MODU_NODES_DART_DOCS'])

    def tearDown(self):
        os.environ.pop('MODU_NODES_DART_DOCS', None); self.docs.cleanup()
        super().tearDown()

    def run_filing(self, no):
        r = self.c.post('/api/easy/run', json={'card': 'filing', 'company': CO, 'cutoff': CUT, 'rcept_no': no})
        self.assertEqual(r.status_code, 201, r.text)
        self.wait(r.json()['id'])
        return r.json()['id'], self.c.get(f"/api/easy/answer/{r.json()['id']}").json()

    def dart(self, a):
        s = [x for x in a['sources'] if x.get('rcept_no')]
        self.assertEqual(len(s), 1, a['sources'])
        return s[0]

    def test_no_record_says_so(self):
        _, a = self.run_filing(NO_DIV)
        s = self.dart(a)
        self.assertEqual(s['rcept_no'], NO_DIV); self.assertTrue(s['url'].endswith(NO_DIV)); self.assertEqual(s['grade'], 'official')
        self.assertIn('앱이 공시 목록에서 처음 본 시각: 기록 없음(자동 확인 기록이 없는 공시)', s['detail'])
        self.assertFalse(any('원문을 받은 시각' in x for x in s['detail']))                    # 사본에 받은 시각이 없으면 줄을 만들지 않음
        self.assertEqual(a['source_notes'], [TRADE_STATUS_NOTE])
        price = [x for x in a['sources'] if x['grade'] == 'public:fsc']
        self.assertTrue(price and all(x['use'] == USE['public'] for x in price))

    def test_manual_fetch_and_first_seen(self):
        from pathlib import Path
        root = Path(os.environ['MODU_NODES_DART_DOCS'])
        man = D.load_manifest(root); man['docs'][NO_BUY].update(fetched_at='2026-07-20T07:01:00+00:00', added_by='manual')
        D._save_manifest(root, man)
        st = self.c.app.state.store
        AC.ensure(st)
        with st.lock, st.connect() as c:
            c.execute('INSERT INTO filing_seen(rcept_no,ticker,report_nm,rcept_dt,kind,first_seen_at,first_check,prev_checked_at) VALUES (?,?,?,?,?,?,?,?)',
                      (NO_BUY, CO, '주요사항보고서(자기주식취득결정)', '2026-07-20', 'buyback_decision', '2026-07-20T06:40:00+00:00', 0, '2026-07-20T05:40:00+00:00'))
        rid, a = self.run_filing(NO_BUY)
        s = self.dart(a)
        self.assertEqual(s['detail'][0], f'DART 접수번호 {NO_BUY}')
        self.assertEqual(s['detail'][1], '원문을 받은 시각 2026-07-20 16:01 (한국 시각) · 접수번호로 직접 받음')
        self.assertEqual(s['detail'][2], '앱이 공시 목록에서 처음 본 시각 2026-07-20 15:40 (한국 시각) — 그 직전 확인은 2026-07-20 14:40 (한국 시각), 공시는 그 사이에 목록에 올라왔어요')
        # 공유 페이지에도 같은 줄이 보인다
        page = self.c.get(f'/api/share/{rid}').text
        self.assertIn('원문을 받은 시각 2026-07-20 16:01 (한국 시각) · 접수번호로 직접 받음', page)
        self.assertIn(TRADE_STATUS_NOTE, page)
        # 확인서는 그대로 만들어진다
        self.assertEqual(self.c.get(f'/api/easy/receipt/{rid}').status_code, 200)

    def test_first_seen_is_not_in_step_results(self):
        """J23: 자동 확인 기록이 나중에 생겨도 단계 결과(지문)는 같다 — 다시 계산 확인이 깨지지 않음. 답에는 새 기록이 보인다."""
        rid1, a1 = self.run_filing(NO_BUY)
        self.assertIn('기록 없음', self.dart(a1)['detail'][-1])
        st = self.c.app.state.store
        AC.ensure(st)
        with st.lock, st.connect() as c:
            c.execute('INSERT INTO filing_seen(rcept_no,ticker,report_nm,rcept_dt,kind,first_seen_at,first_check) VALUES (?,?,?,?,?,?,?)',
                      (NO_BUY, CO, 'x', '2026-07-20', 'buyback_decision', '2026-07-20T06:40:00+00:00', 1))
        rid2, a2 = self.run_filing(NO_BUY)
        d = lambda rid: {r['type']: r['payload_digest'] for r in self.c.get(f'/api/easy/receipt/{rid}').json()['results']}
        self.assertEqual(d(rid1), d(rid2)); self.assertTrue(d(rid1).get('T15') and d(rid1).get('N20'))
        self.assertIn('첫 확인 때 본 것이라', self.dart(a2)['detail'][-1])
        self.assertIn('첫 확인 때 본 것이라', self.dart(self.c.get(f'/api/easy/answer/{rid1}').json())['detail'][-1])   # 예전 답도 지금 기록으로 보임

    def test_filing_card_order_fact_calc_estimate(self):
        for no in (NO_DIV, NO_BUY):
            _, a = self.run_filing(no)
            rank = {'fact': 0, 'calc': 1, 'estimate': 2}
            tiers = [rank[i['tier']] for i in a['items']]
            self.assertEqual(tiers, sorted(tiers), no)
            kt = [rank[i['tier']] for i in a['key']]
            self.assertEqual(kt, sorted(kt), no)

    def test_other_cards_keep_estimate_first(self):
        from mrn import easy as E
        with open(E.__file__, encoding='utf-8') as f:
            src = f.read()
        self.assertIn("    order = {'estimate': 0, 'fact': 1, 'calc': 2}\n    if easy.get('card') == 'filing':", src)

    def test_web_shows_detail_and_link(self):
        with open(os.path.join(os.path.dirname(__file__), '..', 'web', 'easy.js'), encoding='utf-8') as f:
            js = f.read()
        for t in ('s.detail', 'DART 원문 열기', '이용 범위: ', 'a.source_notes'):
            self.assertIn(t, js)
