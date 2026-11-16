"""v0.25: 공시 반응 사전 (감성-주가 프레임워크 T1) — 분류 규칙 · 그때 알 수 있던 것만 · 기록 분류 규칙 · 금지 표현 · API."""
import json, os, re, tempfile, unittest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from mrn import market
from mrn import reaction as R
from tests.test_universe import _w, _h

N_CO = 25
BANNED_TRADE = re.compile(r'매수|매도|목표\s*주가|사세요|파세요|오를\s*것|내릴\s*것')


def _days(n, start=date(2025, 6, 2)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def make_snapshot(root, jump=0.04, n_buyback=24):
    """국내 25곳 · 360거래일. 자사주 취득 공시 다음 거래일(0일)에 +jump 를 넣고, 정기 공시에는 아무것도 넣지 않는다."""
    name = '20261107T000000+0900'
    d = os.path.join(root, name)
    os.makedirs(d)
    days = _days(360)
    T = {}
    cos = [f'9{i:05d}' for i in range(N_CO)]
    h, n = _w(os.path.join(d, 'company.jsonl'), [{'ticker': t, 'name': f'회사{i}', 'market': 'KR'} for i, t in enumerate(cos)]
              + [{'ticker': 'ZZZ', 'name': '해외', 'market': 'US'}])
    T['company'] = {'file': 'company.jsonl', 'rows': n, 'sha256': h, 'source_grade': 'test', 'query': 't', 'note': ''}
    seed = [12345]

    def rnd():
        seed[0] = (seed[0] * 1103515245 + 12345) % (2 ** 31)
        return seed[0] / 2 ** 31 - 0.5

    mkt = [rnd() * 0.02 for _ in days]
    idx, lv = [], 2500.0
    for i, dd in enumerate(days):
        lv *= 1 + mkt[i]
        idx.append({'symbol': '^KS11', 'trade_date': dd, 'close': str(lv), 'name': 'KOSPI', 'source': 'test'})
    h, n = _w(os.path.join(d, 'market_index_daily.jsonl'), idx)
    T['market_index_daily'] = {'file': 'market_index_daily.jsonl', 'rows': n, 'sha256': h, 'source_grade': 'test', 'query': 't', 'note': ''}
    # 사건 날짜: 회사마다 서로 다른 날 (300~340번째 거래일), 정기 공시는 그 20일 전
    ev = {t: days[300 + i] for i, t in enumerate(cos[:n_buyback])}
    px, dis = {}, {}
    for i, t in enumerate(cos):
        rows, c = [], 10000.0
        for j, dd in enumerate(days):
            r = mkt[j] + rnd() * 0.01
            if t in ev and dd == ev[t]:
                r += jump
            c *= 1 + r
            rows.append({'ticker': t, 'trade_date': dd, 'close': str(round(c, 4)), 'open': '1', 'high': '1', 'low': '1', 'volume': '1', 'source': 'fsc'})
        px[t] = rows
        dl = [{'ticker': t, 'rcept_dt': days[280 + i], 'rcept_no': f'2026{i:04d}000001', 'report_nm': '분기보고서 (2026.03)', 'filer': f'회사{i}'}]
        if t in ev:
            dl.append({'ticker': t, 'rcept_dt': ev[t], 'rcept_no': f'2026{i:04d}000002', 'report_nm': '주요사항보고서(자기주식취득결정)', 'filer': f'회사{i}'})
            dl.append({'ticker': t, 'rcept_dt': ev[t], 'rcept_no': f'2026{i:04d}000003', 'report_nm': '[기재정정]주요사항보고서(자기주식취득결정)', 'filer': f'회사{i}'})
        dis[t] = dl
    dis[cos[0]].append({'ticker': cos[0], 'rcept_dt': days[-1], 'rcept_no': '20269999000009', 'report_nm': '단일판매ㆍ공급계약체결', 'filer': '회사0'})
    for table, data in (('price_daily', px), ('disclosure', dis)):
        parts, total = {}, 0
        for t, rows in data.items():
            f = f'{table}/{t}.jsonl'
            h, n = _w(os.path.join(d, f), rows)
            parts[t] = {'file': f, 'rows': n, 'sha256': h}
            total += n
        T[table] = {'partitioned': True, 'parts': parts, 'rows': total, 'source_grade': 'test', 'query': 't', 'note': ''}
    mp = os.path.join(d, 'manifest.json')
    with open(mp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps({'tool_version': 3, 'tables': T}))
    with open(os.path.join(d, 'manifest.sha256'), 'w', encoding='utf-8', newline='\r\n') as f:
        f.write(_h(mp) + '  manifest.json\n')
    with open(os.path.join(root, 'LATEST.txt'), 'w', encoding='utf-8', newline='\r\n') as f:
        f.write(name + '\n')
    return days, ev, cos


def _cut(day):
    return f'{day}T16:00:00+09:00'


def _all_text(x):
    return json.dumps(x, ensure_ascii=False)


class Classify(unittest.TestCase):
    def test_parentheses_correction_subsidiary(self):
        c = R.classify('주요사항보고서 (자기주식취득결정)')
        self.assertEqual((c['key'], c['correction'], c['subsidiary']), ('buyback', False, False))
        c = R.classify('[기재정정]주요사항보고서(자기주식취득결정)')
        self.assertTrue(c['correction'])
        c = R.classify('단일판매ㆍ공급계약체결(자회사의주요경영사항)')
        self.assertEqual((c['key'], c['group']), ('supply_contract', 'supply_contract:sub'))
        self.assertEqual(R.classify('주요사항보고서(자기주식취득신탁계약해지결정)')['key'], 'buyback_trust_end')
        self.assertEqual(R.classify('주요사항보고서(자기주식처분결정)')['key'], 'treasury_sale')

    def test_traps(self):
        self.assertEqual(R.classify('현금ㆍ현물배당을위한주주명부폐쇄(기준일)결정')['key'], 'routine')
        self.assertEqual(R.classify('현금ㆍ현물배당결정')['key'], 'dividend')
        self.assertEqual(R.classify('연결재무제표기준영업실적등에대한전망(공정공시)')['key'], 'earnings_guidance')
        self.assertEqual(R.classify('연결재무제표기준영업(잠정)실적(공정공시)')['key'], 'earnings_prelim')
        self.assertEqual(R.classify('유상증자또는주식관련사채등의발행결과(자율공시)')['key'], 'other')
        self.assertEqual(R.classify('최대주주등소유주식변동신고서')['key'], 'routine')
        self.assertEqual(R.classify('최대주주변경')['key'], 'control_change')
        self.assertEqual(R.classify('8-K (2.02,9.01)')['key'], 'other')
        self.assertTrue(R.classify('임원ㆍ주요주주특정증권등소유상황보고서')['routine'])


class Rules(unittest.TestCase):
    def ev(self, vals, dates=None):
        return [{'t0': (dates[i] if dates else f'2026-01-{i % 28 + 1:02d}-{i}'), 'first': v} for i, v in enumerate(vals)]

    def test_held_below_min(self):
        s = R.summarize(self.ev([3.0] * (R.MIN_EVENTS - 1)), 'first')
        self.assertEqual(R.verdict(s), 'held')

    def test_strong_needs_both_halves_and_effect(self):
        up = [1.0 + (i % 5) * 0.1 for i in range(30)]
        self.assertEqual(R.verdict(R.summarize(self.ev(up), 'first')), 'up')
        self.assertEqual(R.verdict(R.summarize(self.ev([-x for x in up]), 'first')), 'down')
        tiny = [0.1 + (i % 3) * 0.01 for i in range(40)]           # t는 크지만 효과가 MIN_EFFECT 미만
        self.assertNotIn(R.verdict(R.summarize(self.ev(tiny), 'first')), ('up', 'down'))
        flip = [-2.0 - (i % 3) * 0.1 for i in range(20)] + [3.0 + (i % 3) * 0.1 for i in range(20)]   # 앞 절반과 뒤 절반이 반대
        self.assertNotIn(R.verdict(R.summarize(self.ev(flip), 'first')), ('up', 'down'))

    def test_noise_is_flat(self):
        noise = [((i * 37) % 11 - 5) * 0.4 for i in range(60)]
        self.assertIn(R.verdict(R.summarize(self.ev(noise), 'first')), ('flat', 'lean_up', 'lean_down'))

    def test_same_day_events_count_once_for_t(self):
        s = R.summarize(self.ev([2.0] * 25, ['2026-03-03'] * 25), 'first')
        self.assertEqual((s['n'], s['n_dates']), (25, 1))
        self.assertEqual(R.verdict(s), 'held')                       # 날짜가 하나면 t를 못 구함 → 보류

    def test_window_after_last_is_none(self):
        days = _days(400)
        st = {d: 0.0 for d in days[1:]}
        mk = {d: 0.0 for d in days[1:]}
        car = R.event_car(days, st, mk, days[300], days[305])
        self.assertIsNotNone(car['first'])
        self.assertIsNotNone(car['drift5'])
        self.assertIsNone(car['drift20'])                             # 20일 창이 기준일 뒤로 넘어감
        self.assertIsNone(R.event_car(days, st, mk, days[306], days[305]))

    def test_weekend_filing_starts_next_trading_day(self):
        days = _days(300)
        st = {d: 0.0 for d in days[1:]}
        sat = (date.fromisoformat(days[280]) + timedelta(days=(5 - date.fromisoformat(days[280]).weekday()) % 7)).isoformat()
        car = R.event_car(days, st, st, sat, days[-1])
        self.assertGreater(car['t0'], sat)


class Snapshot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ['MODU_NODES_NEON_DIR'] = self.tmp.name
        market._UNI.clear()
        R._CACHE.clear()
        self.days, self.ev, self.cos = make_snapshot(self.tmp.name)

    def tearDown(self):
        os.environ.pop('MODU_NODES_NEON_DIR', None)
        market._UNI.clear()
        R._CACHE.clear()
        self.tmp.cleanup()

    def test_planted_jump_found_control_flat(self):
        res = R.build(_cut(self.days[-1]))
        row = {r['group']: r for r in res['table']}
        b = row['buyback']
        self.assertEqual(b['stats']['first']['n'], 24)               # 정정 공시는 빠지고 원 공시만
        self.assertEqual(b['verdict'], 'up')
        self.assertAlmostEqual(b['stats']['first']['mean'], 4.0, delta=1.0)
        self.assertEqual(row['routine']['verdict'], 'flat')
        self.assertLess(abs(R.control(res)['mean']), 0.5)
        self.assertEqual(res['rules']['benchmark'], 'equal_weight_ex_self')
        self.assertNotIn('ZZZ', res['_events'])                      # 해외 회사 제외

    def test_kospi_benchmark_also_runs(self):
        res = R.build(_cut(self.days[-1]), bench='kospi')
        self.assertEqual(res['rules']['benchmark'], 'kospi')
        self.assertEqual({r['group']: r for r in res['table']}['buyback']['verdict'], 'up')

    def test_cutoff_only_what_was_known(self):
        mid = self.days[305]                                         # 사건 일부만 일어난 시점
        res = R.build(_cut(mid))
        b = next(r for r in res['table'] if r['group'] == 'buyback')
        self.assertLess(b['stats']['first']['n'], 24)
        self.assertTrue(all(e['t0'] <= mid for es in res['_events'].values() for e in es))
        self.assertGreater(res['excluded_after_cutoff'], 0)
        early = R.build(_cut(self.days[290]))
        self.assertFalse(any(r['group'] == 'buyback' for r in early['table']))
        j = R.judge('주요사항보고서(자기주식취득결정)', cutoff=_cut(self.days[290]))
        self.assertEqual(j['verdict'], 'held')

    def test_judge_and_company_history(self):
        cut = _cut(self.days[-1])
        j = R.judge('주요사항보고서 (자기주식취득결정)', company=self.cos[3], cutoff=cut)
        self.assertEqual((j['group'], j['verdict'], j['model_calls']), ('buyback', 'up', 0))
        self.assertIn('호재형', j['plain'])
        self.assertEqual(len(j['company_history']), 1)
        o = R.judge('8-K (2.02)', cutoff=cut)
        self.assertEqual(o['verdict'], 'held')
        e = R.judge('연결재무제표기준영업(잠정)실적(공정공시)', cutoff=cut)
        self.assertTrue(any('숫자' in c for c in e['cautions']))
        rc = R.recent(self.cos[0], cut, days=400)
        self.assertTrue(rc['rows'] and all(not r['title'].startswith('분기') for r in rc['rows']))
        self.assertTrue(all(r['url'].startswith('https://dart.fss.or.kr/') for r in rc['rows']))

    def test_no_trade_words_anywhere(self):
        cut = _cut(self.days[-1])
        res = R.public(R.build(cut))
        outs = [res, R.recent('', cut, days=400), R.judge('유상증자결정', cutoff=cut), R.judge('주요사항보고서(자기주식취득결정)', self.cos[1], cut)]
        for o in outs:
            self.assertIsNone(BANNED_TRADE.search(_all_text(o).replace('매수·매도 추천이나', '').replace('매수·매도·목표주가', '')), _all_text(o)[:200])
        for k, (a, b) in R.VERDICT.items():
            self.assertIsNone(BANNED_TRADE.search(a + b))
        self.assertIn('예측이 아닙니다', R.NOTICE)

    def test_tamper_is_refused(self):
        root = os.path.join(self.tmp.name, '20261107T000000+0900')
        p = os.path.join(root, 'disclosure', f'{self.cos[0]}.jsonl')
        with open(p, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'ticker': self.cos[0], 'rcept_dt': self.days[10], 'rcept_no': 'x', 'report_nm': '주식소각결정'}) + '\n')
        with self.assertRaises(market.SnapshotError):
            R.build(_cut(self.days[-1]))

    def test_api_and_easy_card(self):
        from mrn.server import create_app
        with tempfile.TemporaryDirectory() as dd:
            c = TestClient(create_app(dd, port=4395))
            c.get('/api/health')
            c.headers['X-CSRF-Token'] = c.cookies.get('mrn_csrf')
            cut = _cut(self.days[-1])
            d = c.get('/api/reaction/dictionary', params={'cutoff': cut}).json()
            self.assertEqual(d['model_calls'], 0)
            self.assertNotIn('_events', d)
            j = c.post('/api/reaction/judge', json={'title': '주요사항보고서(자기주식취득결정)', 'company': self.cos[2], 'cutoff': cut}).json()
            self.assertEqual(j['verdict'], 'up')
            self.assertEqual(c.post('/api/reaction/judge', json={'title': '  '}).status_code, 422)
            self.assertEqual(c.get('/api/reaction/dictionary', params={'bench': 'nasdaq'}).status_code, 422)
            self.assertEqual(c.get('/api/reaction/recent', params={'company': self.cos[0], 'days': 999}).status_code, 422)
            r = c.get('/api/reaction/recent', params={'company': self.cos[0], 'days': 365, 'cutoff': cut}).json()
            self.assertTrue(r['rows'])
            cards = c.get('/api/easy/cards', params={'company': self.cos[0]}).json()['cards']
            rx = [x for x in cards if x['id'] == 'reaction']
            self.assertEqual(len(rx), 1)
            self.assertEqual((rx[0]['group'], rx[0]['kind'], rx[0]['view']), ('market', '관계', 'reaction'))


class CardShape(unittest.TestCase):
    def test_card_meta_valid(self):
        from mrn.easy import CARD, GROUPS, DOORS
        self.assertIn(R.CARD['group'], {g['id'] for g in GROUPS})
        self.assertTrue(set(R.CARD['doors']) <= {d['id'] for d in DOORS})
        self.assertTrue(all(x in CARD for x in R.CARD['next']))
        self.assertNotIn('reaction', CARD)                           # 엔진 근거 사슬 카드와 섞지 않음 (이 모듈이 직접 답함)

    def test_web_has_reaction_view(self):
        from pathlib import Path
        js = (Path(__file__).resolve().parents[1] / 'web' / 'easy.js').read_text(encoding='utf-8')
        self.assertIn("if (card === 'reaction') return openReaction();", js)
        self.assertIn('AI 모델 0회', js)
        self.assertIsNone(re.search(r'매수|매도|목표\s*주가', js[js.index('v0.25 공시 반응 사전:'):]))


if __name__ == '__main__':
    unittest.main()
