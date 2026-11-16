"""v0.27: 관심 체온계 — 누적 → 하루 새 글(장 마감 보간·24시간 환산) · 그날 이전만 평소 · 시장 감안 · 기록 부족 보류 · 금지 표현 · API."""
import json, math, os, random, re, tempfile, unittest
from datetime import date, datetime, timedelta
from fastapi.testclient import TestClient
from mrn import attention as A
from mrn import market
from mrn.market import KST
from tests.test_reaction import make_snapshot, _cut
from tests.test_universe import _h, _w

BANNED_TRADE = re.compile(r'매수|매도|목표\s*주가|사세요|파세요|오를\s*것|내릴\s*것')


def at(d, hh, mm=0):
    y, m, dd = map(int, d.split('-'))
    return datetime(y, m, dd, hh, mm, tzinfo=KST)


def cap(src, when, total):
    return {'source': src, 'query': 'q', 'total': str(total), 'captured_at': when.isoformat(), 'trade_date': when.date().isoformat()}


class Increments(unittest.TestCase):
    def test_interpolate_close(self):
        caps = [(at('2026-11-02', 13), 1000.0), (at('2026-11-02', 17), 1400.0)]
        self.assertAlmostEqual(A.at_close(caps, '2026-11-02'), 1250.0)          # 15:30 = 13:00과 17:00 사이 62.5%
        self.assertIsNone(A.at_close([(at('2026-11-02', 9), 1.0)], '2026-11-02'))   # 마감 전 6시간 반 — 너무 멂
        self.assertEqual(A.at_close([(at('2026-11-02', 15), 7.0)], '2026-11-02'), 7.0)

    def test_weekend_normalized_and_flags(self):
        cal = ['2026-10-29', '2026-10-30', '2026-11-02', '2026-11-03', '2026-11-04', '2026-11-05']
        tot = {'2026-10-29': 1000, '2026-10-30': 1100, '2026-11-02': 1400, '2026-11-03': 1500, '2026-11-04': 1450, '2026-11-05': 1550}
        rows = [cap('naver_blog', at(d, 15, 30), v) for d, v in tot.items()]
        inc = A.increments(rows, cal)['naver_blog']
        self.assertAlmostEqual(inc['2026-10-30']['new'], 100)
        self.assertAlmostEqual(inc['2026-11-02']['new'], 100)                    # 금→월 72시간 300건 = 하루 100건
        self.assertEqual(inc['2026-11-04']['new'], None)                         # 줄어든 값
        self.assertIn('negative_delta', inc['2026-11-04']['flags'])

    def test_jump_and_until(self):
        cal = [d.isoformat() for d in (date(2026, 10, 26) + timedelta(days=i) for i in range(12)) if d.weekday() < 5]
        tot, rows = 0, []
        for i, d in enumerate(cal):
            tot += 5000 if i == 3 else 100
            rows.append(cap('naver_cafe', at(d, 15, 30), tot))
        inc = A.increments(rows, cal)['naver_cafe']
        self.assertIn('jump', inc[cal[3]]['flags'])
        self.assertIsNone(inc[cal[3]]['new'])
        cut = at(cal[5], 12)                                                     # 그 뒤 수집값은 모름
        inc2 = A.increments(rows, cal, until=cut)['naver_cafe']
        self.assertTrue(all(d < cal[5] for d in inc2))

    def test_youtube_daily(self):
        cal = ['2026-11-02', '2026-11-03']
        rows = [{'source': 'youtube_comment', 'published_at': '2026-11-01', 'url': f'https://www.youtube.com/watch?v=AAA&lc={i}'} for i in range(3)]
        rows += [{'source': 'youtube_comment', 'published_at': '2026-11-02', 'url': 'https://www.youtube.com/watch?v=BBB&lc=x'},
                 {'source': 'naver_news', 'published_at': '2026-11-02', 'url': 'x'}]
        y = A.youtube_daily(rows, cal, '2026-11-03')
        self.assertEqual(y['2026-11-02']['comments'], 4)                         # 일요일 댓글은 월요일 몫
        self.assertEqual(y['2026-11-02']['videos'], 2)
        self.assertAlmostEqual(y['2026-11-02']['top_share'], 0.75)

    def test_mention_line_is_daily_not_cumulative(self):
        M = [{'source': 'naver_blog', 'query': 'q', 'trade_date': d, 'total': v} for d, v in
             (('2026-11-02', 1_000_000), ('2026-11-03', 1_000_100), ('2026-11-04', 1_000_250))]
        ln = A.mention_line(M)
        self.assertIn('150건', ln['claim'])
        self.assertNotIn('%', ln['claim'])


class Adjust(unittest.TestCase):
    def test_odd_market_day_is_held(self):
        self.assertAlmostEqual(A.adjust(2.0, 2.0), 1.0)
        self.assertIsNone(A.adjust(0.75, 0.1))          # 시장 0.1배로 나누면 7.5배 — 과장, 보류
        self.assertIsNone(A.adjust(2.0, 4.0))
        self.assertIsNone(A.adjust(None, 1.0))


class Relation(unittest.TestCase):
    def obs(self, n_dates, link):
        rnd = random.Random(7)
        out = []
        for t in range(30):
            for d in range(n_dates):
                a = rnd.gauss(0, 1)
                out.append({'t': t, 'd': d, 'a': a, 'v0': rnd.gauss(0, 1), 'r0': abs(rnd.gauss(0, 1)),
                            'v1': (0.6 * a if link else 0) + rnd.gauss(0, 1), 'r1': abs(rnd.gauss(0, 1))})
        return out

    def test_short_record_is_held(self):
        r = A.relation(self.obs(8, True))
        self.assertEqual(r['verdict'], 'held')
        self.assertIn('기록', r['line'])

    def test_link_found_and_none(self):
        self.assertEqual(A.relation(self.obs(25, True))['verdict'], 'link')
        self.assertEqual(A.relation(self.obs(25, False))['verdict'], 'none')

    def test_date_effect_removed(self):
        """시장 전체가 시끄러운 날 = 다음 날 조용한 날 이 되도록 만들어도, 날짜 효과를 빼면 관계가 사라져야 한다(v0.26 조사의 착시)."""
        rnd = random.Random(3)
        o = []
        for d in range(25):
            loud = 3.0 if d % 2 else 0.0
            for t in range(30):
                o.append({'t': t, 'd': d, 'a': loud + rnd.gauss(0, 1), 'v0': rnd.gauss(0, 1), 'r0': abs(rnd.gauss(0, 1)),
                          'v1': -loud + rnd.gauss(0, 1), 'r1': abs(rnd.gauss(0, 1))})
        self.assertEqual(A.relation(o)['verdict'], 'none')


def add_mentions(root, days, cos, spike=None, loud_day=None):
    """마지막 12거래일 동안 하루 세 번(06·14·22시) 수집. 기본 하루 100건(회사 크기 배수), loud_day 는 모든 회사 2배, spike=(회사, 날) 는 5배."""
    d = os.path.join(root, '20261107T000000+0900')
    mp = os.path.join(d, 'manifest.json')
    with open(mp, encoding='utf-8') as f:
        man = json.load(f)
    tail = days[-12:]
    parts, total = {}, 0
    for k, t in enumerate(cos):
        rows, tot = [], 1_000_000
        rate = 100 * (1 + k % 5)
        for day in tail:
            x = rate * (2 if day == loud_day else 1) * (5 if spike and (t, day) == spike else 1)
            for hh in (6, 14, 22):
                tot += x / 3
                rows.append(cap('naver_blog', at(day, hh), round(tot)))
                rows.append(cap('naver_cafe', at(day, hh), round(tot / 2)))
        f = f'mention_count/{t}.jsonl'
        h, n = _w(os.path.join(d, f), rows)
        parts[t] = {'file': f, 'rows': n, 'sha256': h}
        total += n
    man['tables']['mention_count'] = {'partitioned': True, 'parts': parts, 'rows': total, 'source_grade': 'test', 'query': 't', 'note': ''}
    with open(mp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(man))
    with open(os.path.join(d, 'manifest.sha256'), 'w', encoding='utf-8', newline='\r\n') as f:
        f.write(_h(mp) + '  manifest.json\n')


class Snapshot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ['MODU_NODES_NEON_DIR'] = self.tmp.name
        market._UNI.clear()
        A._CACHE.clear()
        self.days, _, self.cos = make_snapshot(self.tmp.name)
        self.loud = self.days[-4]
        self.spike = (self.cos[3], self.days[-2])
        add_mentions(self.tmp.name, self.days, self.cos, self.spike, self.loud)

    def tearDown(self):
        os.environ.pop('MODU_NODES_NEON_DIR', None)
        market._UNI.clear()
        A._CACHE.clear()
        self.tmp.cleanup()

    def row(self, T, d):
        return next(r for r in T['series'] if r['date'] == d)

    def test_market_day_is_not_company_signal(self):
        T = A.thermo(self.cos[1], _cut(self.days[-1]))
        r = self.row(T, self.loud)
        self.assertGreater(r['own_multiple'], 1.5)                              # 이 회사만 보면 크게 늘어난 날 (장 마감~장 마감 창이라 2배보다 조금 작음)
        self.assertAlmostEqual(r['market_multiple'], r['own_multiple'], delta=0.1)   # 시장 전체도 똑같이 늘었다
        self.assertAlmostEqual(r['adj_multiple'], 1.0, delta=0.1)               # 시장을 감안하면 평소
        s = self.row(A.thermo(self.cos[3], _cut(self.days[-1])), self.spike[1])
        self.assertGreater(s['adj_multiple'], 2.5)                              # 혼자 5배 → 시장 감안 뒤에도 큼
        self.assertEqual(T['model_calls'], 0)

    def test_baseline_uses_only_prior_days(self):
        before = A.thermo(self.cos[3], _cut(self.days[-3]))
        A._CACHE.clear()
        after = A.thermo(self.cos[3], _cut(self.days[-1]))
        d = self.days[-5]
        self.assertEqual(round(self.row(before, d)['own_multiple'], 6), round(self.row(after, d)['own_multiple'], 6))   # 뒤에 생긴 급증이 과거 배수를 바꾸지 않음
        self.assertTrue(all(r['date'] <= before['last_usable_date'] for r in before['series']))
        first = A.thermo(self.cos[0], _cut(self.days[-10]))
        self.assertTrue(all(r['own_multiple'] is None for r in first['series']))      # 이전 기록 3일 미만 → 평소를 말하지 않음

    def test_relation_held_and_texts_clean(self):
        T = A.thermo(self.cos[2], _cut(self.days[-1]))
        self.assertEqual(T['relation']['verdict'], 'held')
        txt = json.dumps(T, ensure_ascii=False).replace('매수·매도 추천이나', '')
        self.assertIsNone(BANNED_TRADE.search(txt))
        self.assertIn('인과', T['notice'])

    def test_api_card_and_n11(self):
        from mrn.server import create_app
        with tempfile.TemporaryDirectory() as dd:
            c = TestClient(create_app(dd, port=4395))
            j = c.get('/api/attention/thermo', params={'company': self.cos[1], 'cutoff': _cut(self.days[-1])}).json()
            self.assertEqual(j['company'], self.cos[1])
            self.assertEqual(c.get('/api/attention/thermo', params={'company': self.cos[1], 'days': 999}).status_code, 422)
            p = c.get('/api/attention/panel', params={'cutoff': _cut(self.days[-1])}).json()
            self.assertNotIn('_posts', p)
            cards = c.get('/api/easy/cards', params={'company': self.cos[0]}).json()['cards']
            ids = [x['id'] for x in cards]
            self.assertIn('attention', ids)
            self.assertIn('reaction', ids)
        from pathlib import Path
        src = (Path(__file__).resolve().parents[1] / 'mrn' / 'nodes.py').read_text(encoding='utf-8')
        self.assertIn('mention_line(M)', src)
        js = (Path(__file__).resolve().parents[1] / 'web' / 'easy.js').read_text(encoding='utf-8')
        self.assertIn("if (card === 'attention') return openAttention();", js)
        self.assertIsNone(re.search(r'매수|매도|목표\s*주가', js[js.index('v0.27 관심 체온계:'):]))


if __name__ == '__main__':
    unittest.main()
