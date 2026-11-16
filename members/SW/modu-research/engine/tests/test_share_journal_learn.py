"""v0.32 T1 공유용 페이지 · T2 가설 일지 · T3 배우는 길."""
import os
import sqlite3
import unittest
from decimal import Decimal
from pathlib import Path

from mrn import share, journal, learn
from tests.test_easy import EasyBase
from tests.test_universe import CUT

WEB = Path(__file__).resolve().parent.parent / 'web'


class ShareUnit(unittest.TestCase):
    def test_escapes_and_embeds(self):
        ans = {'run_id': 'r1', 'name': '<script>x</script>', 'card_title': '실적', 'cutoff': '2026-10-30T16:00:00+09:00', 'headline': 'h',
               'count': {'fact': 1, 'calc': 0, 'estimate': 0}, 'key': [{'label': 'a', 'text': 'b', 'tier': 'fact', 'tier_label': '자료로 확인',
               'kind_label': 'k', 'source': {'url': 'javascript:alert(1)', 'title': 't'}}], 'items': [], 'unknown': [], 'not_this': 'n',
               'process': {'steps': [], 'model_calls': 0, 'ai_note': 'AI 모델 호출 0회'}}
        rc = {'run_id': 'r1', 'receipt_id': 'ab' * 32, 'chain_digest': 'cd' * 32, 'x': '</script><b>'}
        html, meta = share.build(ans, rc)
        self.assertNotIn('<script>x</script>', html)
        self.assertNotIn('javascript:', html)                       # http(s) 아닌 링크는 링크로 만들지 않음
        self.assertEqual(share.extract_receipt(html), rc)           # 스크립트 블록을 깨는 글자도 원래대로 되돌림
        self.assertIn("default-src 'none'", html)                   # 외부 요청 없음
        self.assertIn('보증이 아니에요', html)
        with self.assertRaises(ValueError):
            share.build(ans, {**rc, 'run_id': 'other'})


class JournalScore(unittest.TestCase):
    def test_score_rules(self):
        e = {'value_mn': '550000', 'submitted_at': '2026-01-10T10:00:00+09:00'}
        s = journal.score(e, ('600000', '2026-03-10'), {'median': '620000'})
        self.assertEqual((s['status'], s['mine_err_pct'], s['broker_err_pct'], s['closer']), ('scored', '-8.3', '3.3', 'broker'))
        self.assertEqual(journal.score({**e, 'submitted_at': '2026-03-10T09:00:00+09:00'}, ('600000', '2026-03-10'), None)['status'], 'after')
        self.assertEqual(journal.score(e, None, None)['status'], 'pending')


class Api(EasyBase):
    def db(self):
        return sqlite3.connect(os.path.join(self.tmp.name, 'data', 'nodes.sqlite'))

    def run_card(self, card='earnings'):
        rid = self.c.post('/api/easy/run', json={'card': card, 'company': '042700', 'cutoff': CUT}).json()['id']
        self.wait(rid)
        return rid

    def test_share_page_roundtrip(self):
        rid = self.run_card()
        r = self.c.get(f'/api/share/{rid}')
        self.assertEqual(r.status_code, 200)
        self.assertIn('attachment', r.headers['content-disposition'])
        self.assertIn('한미반도체', r.text)
        self.assertIn('6,000억 원', r.text)
        rc = share.extract_receipt(r.text)
        self.assertEqual(rc['receipt_id'], self.c.get(f'/api/easy/receipt/{rid}').json()['receipt_id'])
        self.assertTrue(self.c.post('/api/easy/verify', json={'receipt': rc}).json()['ok'])
        self.assertEqual(self.c.get('/api/share/nope').status_code, 404)

    def test_journal_scoring_and_notes(self):
        self.assertEqual(self.c.get('/api/journal').json()['summary']['entries'], 0)
        self.assertEqual(self.c.post('/api/crowd/submit', json={'ticker': '042700', 'fiscal_year': 2025, 'metric': 'revenue', 'value_jo': 0.55}).status_code, 200)
        with self.db() as c:                         # 실적 공시(2026-03) 전에 적은 것으로 옮겨 채점 확인
            c.execute("UPDATE crowd_assumptions SET submitted_at='2026-01-10T10:00:00+09:00', period='2026-01'")
        J = self.c.get('/api/journal').json()
        g = J['groups'][0]
        self.assertEqual((g['name'], g['fiscal_year'], g['metric']), ('한미반도체', 2025, 'revenue'))
        self.assertEqual(Decimal(g['actual']['value_mn']), Decimal('600000'))
        e = g['entries'][0]
        self.assertEqual((e['status'], e['mine_err_pct']), ('scored', '-8.3'))
        self.assertEqual(J['summary']['scored'], 1)
        ok = self.c.post('/api/journal/note', json={'ticker': '042700', 'fiscal_year': 2025, 'metric': 'revenue', 'period': '2026-01', 'note': '증설 지연을 반영'})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.c.get('/api/journal').json()['groups'][0]['entries'][0]['note'], '증설 지연을 반영')
        self.assertEqual(self.c.post('/api/journal/note', json={'ticker': '042700', 'fiscal_year': 2025, 'metric': 'revenue', 'period': '2026-01', 'note': 'x' * 301}).status_code, 422)
        self.assertEqual(self.c.post('/api/journal/note', json={'ticker': '042700', 'fiscal_year': 2024, 'metric': 'revenue', 'period': '2026-01', 'note': 'a'}).status_code, 404)
        with self.db() as c:                         # 감사 기록에 메모 글은 남기지 않음
            self.assertFalse(any('증설' in r[0] for r in c.execute("SELECT detail FROM audit WHERE action='journal.note'")))
        with self.db() as c:                         # 공시 뒤에 적은 가정은 채점하지 않음
            c.execute("UPDATE crowd_assumptions SET submitted_at='2026-05-01T10:00:00+09:00'")
        self.assertEqual(self.c.get('/api/journal').json()['groups'][0]['entries'][0]['status'], 'after')

    def test_learn_progress(self):
        p = self.c.get('/api/learn').json()
        self.assertEqual((p['done'], p['total'], p['next']), (0, 9, 'ask'))
        rid = self.run_card()
        self.assertTrue(next(t for s in self.c.get('/api/learn').json()['stages'] for t in s['tasks'] if t['id'] == 'ask')['done'])
        self.assertEqual(self.c.post('/api/learn/mark', json={'task': 'share'}).status_code, 422)    # 서버 기록으로만 알아내는 과제
        self.assertEqual(self.c.post('/api/learn/mark', json={'task': 'evidence'}).json()['done'], 2)
        self.c.get(f'/api/share/{rid}')
        self.c.post('/api/crowd/submit', json={'ticker': '042700', 'fiscal_year': 2026, 'metric': 'revenue', 'value_jo': 0.7})
        done = {t['id'] for s in self.c.get('/api/learn').json()['stages'] for t in s['tasks'] if t['done']}
        self.assertEqual(done, {'ask', 'evidence', 'share', 'crowd'})


class Screen(unittest.TestCase):
    def test_screen_parts(self):
        h = (WEB / 'easy.html').read_text(encoding='utf-8')
        js = (WEB / 'easy.js').read_text(encoding='utf-8')
        for s in ('id="nJournal"', 'id="nLearn"', 'id="journal"', 'id="learn"', '.html,application/json'):
            self.assertIn(s, h)
        for s in ('downloadShare', 'openJournal', 'openLearn', 'modu-receipt', '공유용 페이지 내려받기'):
            self.assertIn(s, js)
        self.assertEqual(len(learn.TASKS), 9)
        self.assertEqual(set(learn.CLIENT_MARKS), {'evidence', 'strip', 'then'})


if __name__ == '__main__':
    unittest.main()
