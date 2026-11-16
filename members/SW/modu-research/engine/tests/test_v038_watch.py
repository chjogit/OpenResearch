"""v0.38 T1 관심 종목: 고르기 목록(정렬·묶음·업종·검색)과 저장(사용자별)."""
import os, unittest
from pathlib import Path
from fastapi.testclient import TestClient
from mrn import watch as W
from mrn.server import create_app
from tests.test_easy import EasyBase, CUT

REAL = Path(__file__).resolve().parents[2] / '_sources' / 'neon'


class Pick(EasyBase):
    def test_groups_sort_search(self):
        g = {k: self.c.get('/api/watch/pick', params={'group': k, 'cutoff': CUT}).json() for k in W.GROUPS}
        self.assertEqual(g['all']['count'], 7)
        self.assertEqual(g['us']['count'], 1)
        self.assertEqual(g['kr_other']['count'], 6)                  # 시험 자료엔 코스피200 표시가 없음
        self.assertEqual(g['kospi200']['count'], 0)
        self.assertEqual(g['top100']['count'] + g['smallmid']['count'], 6)   # 국내는 둘 중 하나에만
        names = [r['name'] for r in g['all']['rows']]
        self.assertTrue(all('가' <= n[0] <= '힣' for n in names[:3]) and names[3] == 'LG')   # 한글 이름 3곳 먼저, 영문은 뒤
        self.assertEqual(names[:3], sorted(n for n in names if '가' <= n[0] <= '힣')[:3])
        codes = [r['ticker'] for r in self.c.get('/api/watch/pick', params={'sort': 'code', 'cutoff': CUT}).json()['rows']]
        self.assertEqual(codes, sorted(codes))
        q = self.c.get('/api/watch/pick', params={'q': 'lg 전자', 'cutoff': CUT}).json()
        self.assertEqual([r['ticker'] for r in q['rows']], ['066570'])        # 띄어쓰기·대소문자 무시
        self.assertEqual(self.c.get('/api/watch/pick', params={'sector': '반도체', 'cutoff': CUT}).json()['count'], 1)
        self.assertEqual(self.c.get('/api/watch/pick?sort=x').status_code, 422)
        self.assertEqual(self.c.get('/api/watch/pick?group=x').status_code, 422)
        self.assertIn('시장 전체의 중소형주 목록이 아닙니다', g['smallmid']['smallmid_note'])
        self.assertEqual(self.c.get('/api/watch/pick', params={'cutoff': 'x'}).status_code, 422)   # 잘못된 날짜는 엔진 오류(500)가 아니라 422

    def test_cap_uses_only_confirmed_trade_days(self):
        early = W.caps('2026-01-15T09:00:00+09:00')
        self.assertTrue(all(v['date'] <= '2026-01-14' for v in early.values()))   # 장 마감 전이면 전날까지


class Save(EasyBase):
    def test_add_list_remove_and_owner_isolation(self):
        self.assertEqual(self.c.get('/api/watch').json()['rows'], [])
        r = self.c.post('/api/watch', json={'ticker': '042700'}).json()
        self.assertEqual([x['ticker'] for x in r['rows']], ['042700'])
        self.assertEqual(r['rows'][0]['name'], '한미반도체')
        self.c.post('/api/watch', json={'ticker': '042700'})                  # 두 번 넣어도 하나
        self.assertEqual(len(self.c.get('/api/watch').json()['rows']), 1)
        self.assertEqual(self.c.post('/api/watch', json={'ticker': '999999'}).status_code, 404)
        other = TestClient(self.c.app); other.get('/api/health'); other.headers['X-CSRF-Token'] = other.cookies.get('mrn_csrf')
        self.assertEqual(other.get('/api/watch').json()['rows'], [])            # 다른 사용자에게는 안 보임
        self.assertEqual(self.c.post('/api/watch/remove', json={'ticker': '042700'}).json()['rows'], [])

    def test_limit_and_csrf(self):
        old = W.LIMIT; W.LIMIT = 2
        try:
            for t in ('005930', '042700'):
                self.assertEqual(self.c.post('/api/watch', json={'ticker': t}).status_code, 200)
            r = self.c.post('/api/watch', json={'ticker': '000660'})
            self.assertEqual(r.status_code, 422); self.assertIn('2곳까지', r.json()['detail'])   # v0.38 이름 바꿈: 「관심회사는 n곳까지」
            self.assertEqual(self.c.post('/api/watch', json={'ticker': '042700'}).status_code, 200)   # 이미 있는 것은 그대로
        finally:
            W.LIMIT = old
        bare = TestClient(self.c.app); bare.get('/api/health')
        self.assertEqual(bare.post('/api/watch', json={'ticker': '005930'}).status_code, 403)


@unittest.skipUnless((REAL / '20261107T005213+0900').is_dir(), '실제 Neon 사본이 있을 때만')
class RealSnapshot(unittest.TestCase):
    def setUp(self):
        from mrn import market
        self.old = os.environ.get('MODU_NODES_NEON_DIR'); os.environ['MODU_NODES_NEON_DIR'] = str(REAL); market._UNI.clear()

    def tearDown(self):
        from mrn import market
        if self.old is None:
            os.environ.pop('MODU_NODES_NEON_DIR', None)
        else:
            os.environ['MODU_NODES_NEON_DIR'] = self.old
        market._UNI.clear()

    def test_counts_on_real_copy(self):
        n = {k: W.pick_list(CUT, 'cap', k)['count'] for k in W.GROUPS}
        self.assertEqual(n, {'all': 230, 'kospi200': 201, 'top100': 100, 'smallmid': 110, 'kr_other': 9, 'us': 20})
        top = W.pick_list(CUT, 'cap', 'top100')['rows']
        self.assertEqual(top[0]['ticker'], '005930'); self.assertEqual([r['cap_rank'] for r in top], list(range(1, 101)))


class ScreenWords(unittest.TestCase):
    def test_watch_screen_has_no_jargon_or_trading_words(self):
        import re
        from tests.test_easy import BANNED, WEB
        js = (WEB / 'watch.js').read_text(encoding='utf-8')
        lits = ' '.join(a or b for a, b in re.findall(r"'([^'\n]*)'|`([^`]*)`", js))
        lits = re.sub(r'\$\{[^}]*\}', ' ', lits)
        lits = re.sub(r'/api/[^\s\'"`]*|#[a-zA-Z]+|\.[a-z][a-zA-Z]+|data-[a-z]+|[a-z]+\[[^\]]*\]', ' ', lits)
        html = (WEB / 'easy.html').read_text(encoding='utf-8')
        sec = html[html.index('<section id="watch"'):html.index('</section>', html.index('<section id="watch"'))]
        for w in BANNED + ['매수', '매도', '목표주가', '추천', '호재', '악재']:
            self.assertNotIn(w, lits, w); self.assertNotIn(w, re.sub(r'<[^>]+>', ' ', sec), w)
        self.assertIn('<script src="/static/watch.js"></script>', html)
