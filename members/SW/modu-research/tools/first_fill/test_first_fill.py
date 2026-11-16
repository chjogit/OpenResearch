"""첫 채움 시험 — 가짜 KIS·DART 응답으로 빈 폴더에 사본을 만들고, 엔진 읽기 함수·가격/수급 갱신이 그대로 받는지 본다(네트워크·키 없음)."""
import io, json, os, sys, tempfile, unittest, urllib.parse, zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import first_fill as FF   # noqa: E402

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 16, 17, 0, tzinfo=KST)   # 월요일 장 마감 뒤


def wdays(end, n):
    d, out = date.fromisoformat(end), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return sorted(out)


DAYS = wdays('2026-11-16', 400)


class FakeKis:
    """surge.Kis 와 같은 모양: token · sleep · _count · http · key · secret · calls"""
    key, secret = 'TESTKEY0000', 'TESTSECRET'

    def __init__(self, limited=('017670',)):
        self.calls, self.limited = 0, set(limited)

    def token(self):
        return 'tok'

    def sleep(self, s):
        pass

    def _count(self):
        self.calls += 1

    def http(self, method, url, headers, body):
        u = urllib.parse.urlparse(url); q = dict(urllib.parse.parse_qsl(u.query)); p = u.path
        t = q.get('FID_INPUT_ISCD')
        if p.endswith('inquire-price'):
            lim = t in self.limited   # 외국인 한도 종목: 소진율 ≠ 보유율
            return 200, {'rt_cd': '0', 'output': {'lstn_stcn': '1000000', 'frgn_hldn_qty': '250000', 'hts_frgn_ehrt': '50.00' if lim else '25.00',
                                                  'bstp_kor_isnm': '전기·전자', 'rprs_mrkt_kor_name': 'KOSPI200', 'hts_kor_isnm': 'KIS이름'}}
        if p.endswith('inquire-daily-itemchartprice') or p.endswith('inquire-daily-indexchartprice'):
            lo, hi = FF.iso8(q['FID_INPUT_DATE_1']), FF.iso8(q['FID_INPUT_DATE_2'])
            ds = [d for d in DAYS if lo <= d <= hi][-100:][::-1]
            if p.endswith('itemchartprice'):
                rows = [{'stck_bsop_date': d.replace('-', ''), 'stck_clpr': str(1000 + i), 'stck_oprc': '1000', 'stck_hgpr': '2000',
                         'stck_lwpr': '900', 'acml_vol': '10', 'acml_tr_pbmn': '10000'} for i, d in enumerate(ds)]
            else:
                rows = [{'stck_bsop_date': d.replace('-', ''), 'bstp_nmix_prpr': '2500.10', 'acml_vol': '5'} for d in ds]
            return 200, {'rt_cd': '0', 'output2': rows}
        if p.endswith('inquire-investor'):
            rows = [{'stck_bsop_date': d.replace('-', ''), 'prsn_ntby_qty': '-5', 'frgn_ntby_qty': '3', 'orgn_ntby_qty': '2'} for d in DAYS[-30:]][::-1]
            rows.insert(0, {'stck_bsop_date': '20261117', 'prsn_ntby_qty': '', 'frgn_ntby_qty': '', 'orgn_ntby_qty': ''})   # 장중 빈 줄
            return 200, {'rt_cd': '0', 'output': rows}
        if p.endswith('inquire-daily-price'):
            lim = t in self.limited
            rows = [{'stck_bsop_date': d.replace('-', ''), 'hts_frgn_ehrt': '50.00' if lim else '25.00', 'acml_vol': '10'} for d in DAYS[-30:]][::-1]
            return 200, {'rt_cd': '0', 'output': rows}
        return 404, {'rt_cd': '1', 'msg_cd': 'X'}


def corp_zip():
    xml = '<result>' + ''.join(f'<list><corp_code>00{t}</corp_code><corp_name>회사{t}</corp_name><stock_code>{t}</stock_code></list>'
                               for t in ('005930', '000660', '017670')) + '<list><corp_code>99</corp_code><corp_name>비상장</corp_name><stock_code> </stock_code></list></result>'
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        z.writestr('CORPCODE.xml', xml)
    return b.getvalue()


def fake_dart_fetch(url):
    u = urllib.parse.urlparse(url); q = dict(urllib.parse.parse_qsl(u.query)); name = u.path.rsplit('/', 1)[-1]
    if name == 'corpCode.xml':
        return corp_zip()
    if name == 'list.json':
        if q['pblntf_ty'] == 'D' and q['corp_code'].endswith('005930'):   # 지분공시가 많은 회사: 매일 3건, 한 번 조회 최대 1,000건(10쪽)
            lo, hi = date.fromisoformat(FF.iso8(q['bgn_de'])), date.fromisoformat(FF.iso8(q['end_de']))
            allr = [{'rcept_no': f"{(lo + timedelta(days=i)).strftime('%Y%m%d')}00000{j}", 'rcept_dt': (lo + timedelta(days=i)).strftime('%Y%m%d'),
                     'report_nm': '임원ㆍ주요주주특정증권등소유상황보고서', 'flr_nm': '임원'} for i in range((hi - lo).days + 1) for j in range(3)]
            pg = int(q['page_no'])
            if pg > 10:
                return json.dumps({'status': '013'}).encode()
            return json.dumps({'status': '000', 'total_count': len(allr), 'list': allr[(pg - 1) * 100: pg * 100]}).encode()
        if q['pblntf_ty'] != 'B':
            return json.dumps({'status': '013'}).encode()
        lst = [{'rcept_no': '20260301900001', 'rcept_dt': '20260301', 'report_nm': '주요사항보고서(자기주식취득결정)', 'flr_nm': '회사'}]
        return json.dumps({'status': '000', 'total_count': 1, 'list': lst}).encode()
    if name == 'fnlttSinglAcntAll.json':
        y, code = int(q['bsns_year']), q['reprt_code']
        if q['fs_div'] == 'CFS' and q['corp_code'].endswith('017670'):
            return json.dumps({'status': '013'}).encode()   # 연결 없음 → 별도로
        if y not in (2025, 2026) or (y == 2026 and code == '11011'):
            return json.dumps({'status': '013'}).encode()
        ytd = {'11013': 100, '11012': 250, '11014': 400, '11011': 600}[code]
        rno = (f'{y + 1}0310' if code == '11011' else f'{y}0814') + '0' + code   # 접수번호 앞 8자리 = 접수일(엔진이 기준시점 거름에 씀)
        lst = [{'sj_div': 'IS', 'account_id': 'ifrs-full_Revenue', 'account_nm': '매출액', 'thstrm_amount': '1' if code != '11011' else str(ytd),
                'thstrm_add_amount': str(ytd), 'currency': 'KRW', 'rcept_no': rno},
               {'sj_div': 'BS', 'account_id': 'ifrs-full_Assets', 'account_nm': '자산총계', 'thstrm_amount': '9,000', 'rcept_no': rno},
               {'sj_div': 'SCE', 'account_id': 'ifrs-full_Equity', 'account_nm': '자본', 'thstrm_amount': '1'},
               {'sj_div': 'IS', 'account_id': 'ifrs-full_Other', 'account_nm': '기타', 'thstrm_amount': '1'}]
        return json.dumps({'status': '000', 'list': lst}).encode()
    if name == 'hyslrSttus.json':
        return json.dumps({'status': '000', 'list': [{'nm': '최대주주', 'relate': '본인', 'stock_knd': '보통주', 'trmend_posesn_stock_co': '1,000',
                                                      'trmend_posesn_stock_qota_rt': '20.10', 'bsis_posesn_stock_qota_rt': '20.00',
                                                      'stlm_dt': '2025.12.31', 'rcept_no': 'H1'}]}).encode()
    if name == 'majorstock.json':
        return json.dumps({'status': '000', 'list': [{'rcept_no': 'O1', 'rcept_dt': '2025-05-01', 'repror': '국민연금', 'report_tp': '일반',
                                                      'stkqy': '5,000', 'stkrt': '5.01', 'stkrt_irds': '0.01', 'ctr_stkrt': '0'}]}).encode()
    raise AssertionError(url)


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.nd = Path(self.tmp.name) / '_sources' / 'neon'
        os.environ['MODU_NODES_NEON_DIR'] = str(self.nd)
        FF.LOG.clear()

    def tearDown(self):
        os.environ.pop('MODU_NODES_NEON_DIR', None)
        self.tmp.cleanup()

    def run_ff(self, *extra):
        return FF.main(['--tickers', '005930,000660,017670', '--days', '120', *extra], kis=FakeKis(), dart=FF.Dart('DARTTESTKEY', fetch=fake_dart_fetch, sleep=lambda s: None), now=NOW)

    def test_build_and_engine_reads(self):
        self.assertEqual(self.run_ff(), 0)
        M = FF.M
        root = M.resolve(''); man = M.load_manifest(root)
        self.assertEqual(len(man['tables']), 22)
        self.assertTrue(all(m.get('query') for m in man['tables'].values()))        # 엔진 출처 설명에 쓰는 칸
        ps = M.price_series('005930', '2026-11-16T09:00:00+00:00')                  # 엔진 T06 이 쓰는 함수 그대로
        self.assertEqual(ps['rows'][-1]['trade_date'], '2026-11-16')
        rows, _ = M.read_rows(root, man, 'price_daily', '005930')
        self.assertEqual(rows[-1]['trade_date'], '2026-11-16')                    # 16시 뒤 → 오늘까지
        self.assertEqual(rows[-1]['market_cap'], str(1000000 * int(rows[-1]['close'])))
        self.assertTrue(rows[0]['trade_date'] >= '2026-07-19')                     # --days 120
        self.assertEqual(len({r['trade_date'] for r in rows}), len(rows))          # 날짜 겹침 없음(100건 나눠 받기)
        fl, _ = M.read_rows(root, man, 'investor_flow_daily', '005930')
        self.assertEqual(len(fl), 30); self.assertEqual(fl[-1]['foreign_hold_pct'], '25.0000')
        lim, _ = M.read_rows(root, man, 'investor_flow_daily', '017670')
        self.assertTrue(all(r['foreign_hold_pct'] is None for r in lim))          # 한도 종목 보유율은 비움
        self.assertIn('017670', man['first_fill']['hold_blank'])
        dd, _ = M.read_rows(root, man, 'disclosure', '005930')                       # 1,000건 상한 → 기간 나눠 모두 받음
        nd = [r for r in dd if r['category'] == 'D']
        days_ = (date(2026, 11, 16) - date.fromisoformat(min(r['rcept_dt'] for r in nd))).days + 1
        self.assertEqual(len(nd), days_ * 3); self.assertGreater(len(nd), 1000)
        ds, _ = M.read_rows(root, man, 'disclosure', '000660')
        self.assertEqual((ds[0]['category'], ds[0]['event_type']), ('B', 'buyback'))
        ff, _ = M.read_rows(root, man, 'financial_fact', '017670')
        self.assertTrue(ff and all(r['fs_div'] == 'OFS' for r in ff))              # 연결 없으면 별도
        self.assertFalse(any(r['sj_div'] == 'SCE' or r['account_id'] == 'ifrs-full_Other' for r in ff))
        self.assertEqual(next(r for r in ff if r['account_id'] == 'ifrs-full_Assets')['amount'], '9000')
        fq, _ = M.read_table(root, man, 'financial_quarter')
        rev = {(r['ticker'], r['period_end']): r['amount'] for r in fq if r['metric'] == 'revenue'}
        self.assertEqual(rev[('005930', '2025-03-31')], '100')
        self.assertEqual(rev[('005930', '2025-06-30')], '150')
        self.assertEqual(rev[('005930', '2025-12-31')], '200')
        cf = M.company_filings('017670', '2026-11-16T09:00:00+00:00')               # 엔진 T11 이 쓰는 함수 그대로(별도 재무)
        self.assertTrue(cf['facts'] and cf['quarters'])
        hd, _ = M.read_rows(root, man, 'largest_holder', '005930')
        self.assertEqual((hd[0]['end_qty'], hd[0]['settle_dt']), ('1000', '2025-12-31'))
        uni = M.universe('')
        self.assertEqual(uni['count'], 3)
        self.assertTrue(uni['summary']['price_fsc'] == 3 and uni['summary']['flow'] == 3)
        self.assertEqual(M.name_index('')['회사005930'], '005930')
        idx, _ = M.read_table(root, man, 'market_index_daily')
        self.assertEqual({r['symbol'] for r in idx}, {'^KS11', '^KQ11'})
        for name in ('news_title', 'stock_lending_daily'):
            self.assertEqual(M.read_rows(root, man, name, '005930')[0], [])
        txt = json.dumps(man, ensure_ascii=False) + ''.join(p.read_text(encoding='utf-8') for p in root.rglob('*.jsonl'))
        for secret in ('TESTKEY0000', 'TESTSECRET', 'DARTTESTKEY'):
            self.assertNotIn(secret, txt)                                           # 키는 어디에도 안 남음
        self.assertNotIn('DARTTESTKEY', '\n'.join(FF.LOG))

    def test_refuses_existing(self):
        self.assertEqual(self.run_ff(), 0)
        first = (self.nd / 'LATEST.txt').read_text(encoding='utf-8')
        self.assertEqual(self.run_ff(), 3)                                          # 이미 있으면 멈춤
        self.assertEqual((self.nd / 'LATEST.txt').read_text(encoding='utf-8'), first)

    def test_dry_writes_nothing(self):
        self.assertEqual(self.run_ff('--dry'), 0)
        self.assertFalse(self.nd.exists())

    def test_missing_keys(self):
        for k in ('KIS_APP_KEY', 'KIS_APP_SECRET', 'DART_API_KEY'):
            os.environ.pop(k, None)
        self.assertEqual(FF.main(['--check'], now=NOW), 2)
        self.assertIn('키가 없어요', FF.LOG[-1])

    def test_bad_ticker(self):
        self.assertEqual(FF.main(['--tickers', '5930'], now=NOW), 2)

    def test_refresh_tools_accept_snapshot(self):
        """첫 채움 사본 위에서 가격 갱신의 대조 규칙(최근 5거래일 종가 일치)이 그대로 통과하는지"""
        self.assertEqual(self.run_ff(), 0)
        sys.path.insert(0, str(HERE.parent / 'price_refresh'))
        import price_refresh as PR
        M = FF.M; root = M.resolve(''); man = M.load_manifest(root)
        rows, _ = M.read_rows(root, man, 'price_daily', '005930')
        k = {r['trade_date']: {'stck_clpr': r['close'], 'acml_vol': '10'} for r in rows[-5:]}
        k['2026-11-17'] = {'stck_clpr': '5000', 'acml_vol': '10'}
        new, why = PR.plan_stock('005930', rows, k, 'now')
        self.assertIsNone(why); self.assertEqual([r['trade_date'] for r in new], ['2026-11-17'])


if __name__ == '__main__':
    unittest.main()
