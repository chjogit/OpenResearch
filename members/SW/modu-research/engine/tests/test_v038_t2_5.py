"""v0.38 T2-5(J27): 자기주식 취득 「하루 평균 매입 필요 금액」을 거래일(휴장일 반영)로 · 2022~2025 휴장일 표(시세 사본에서 거래가 없던 평일)."""
import json, os, unittest
from pathlib import Path
from mrn import filing as FL, tradecal as C

SNAP = Path(__file__).resolve().parents[2] / '_sources' / 'neon'


class TradingDays(unittest.TestCase):
    def test_trading_days_and_note(self):
        self.assertEqual(FL.trading_days('2025-01-20', '2025-02-07'), (11, ''))          # 평일 15 − 설 연휴·임시공휴일 4(1/27~1/30)
        n, note = FL.trading_days('2027-12-27', '2028-01-07')
        self.assertIn('2028년은 휴장일 표가 없어 평일을 거래일로 셈', note)
        self.assertEqual(n, 8)                                                            # 2027: 12/27·12/31 휴장 → 12/28~30(3) + 2028 평일 1/3~7(5)

    def test_past_years_present(self):
        d = json.loads((Path(FL.__file__).with_name('krx_holidays.json')).read_text(encoding='utf-8'))
        self.assertEqual({y: len(v) for y, v in d['years'].items()}, {'2022': 14, '2023': 15, '2024': 18, '2025': 19, '2026': 17, '2027': 16})
        for day in ('2022-03-09', '2023-05-01', '2024-04-10', '2024-10-01', '2025-01-27', '2025-06-03'):     # 대선·근로자의날·총선·국군의날·임시공휴일·대선
            self.assertFalse(C.is_open(day), day)
        for day in ('2022-09-21', '2023-08-17', '2024-07-12'):                             # 사본에 7곳만 기록된 날 = 자료 빠짐 → 거래일
            self.assertTrue(C.is_open(day), day)
        self.assertIn('source_past', d)


@unittest.skipUnless((SNAP / 'LATEST.txt').exists(), '시세 사본 없음')
class AgainstSnapshot(unittest.TestCase):
    def test_2022_2025_match_snapshot(self):
        import collections
        from datetime import date, timedelta
        from mrn import prob as P
        old = os.environ.get('MODU_NODES_NEON_DIR'); os.environ['MODU_NODES_NEON_DIR'] = str(SNAP)
        try:
            S, _ = P.series_from_snapshot('')
        finally:
            if old is None:
                os.environ.pop('MODU_NODES_NEON_DIR', None)
            else:
                os.environ['MODU_NODES_NEON_DIR'] = old
        cnt = collections.Counter(d for s in S.values() for d, _ in s)
        bad = []
        d = date(2022, 1, 1)
        while d.year < 2026:
            k = d.isoformat()
            if d.weekday() < 5 and (cnt.get(k, 0) >= 100) != C.is_open(k) and k not in ('2022-09-21', '2023-08-17', '2024-07-12'):
                bad.append(k)
            d += timedelta(days=1)
        self.assertEqual(bad, [])
