"""v0.38 T2-4c 거래일 달력: 한국거래소 휴장일 표 · 실제 시세의 거래일과 대조 · 표가 없는 해."""
import unittest
from datetime import date, timedelta
from mrn import tradecal as C, prob as PB


class Calendar(unittest.TestCase):
    def test_table_and_shift(self):
        self.assertFalse(C.is_open('2026-12-31')); self.assertEqual(C.holiday('2026-12-31'), '연말 휴장일')
        self.assertFalse(C.is_open('2027-05-03')); self.assertFalse(C.is_open('2027-07-19')); self.assertTrue(C.is_open('2027-07-16'))
        self.assertFalse(C.is_open('2026-11-14'))                                                      # 토요일
        self.assertEqual(C.shift('2026-12-30', 1), '2027-01-04'); self.assertEqual(C.shift('2027-02-10', -1), '2027-02-05')
        self.assertEqual(C.shift('2026-03-04', -3), '2026-02-26')
        self.assertEqual(C.count('2026-12-28', '2027-01-08'), 8)
        self.assertTrue(C.covered('2027-06-01')); self.assertFalse(C.covered('2028-01-03'))
        self.assertIn('2028년은 휴장일 표가 없어', C.note('2027-11-01', '2028-02-01')); self.assertEqual(C.note('2026-11-01', '2027-02-01'), '')
        self.assertEqual(len([d for d in C.table()[0] if d.startswith('2026')]), 17); self.assertEqual(len([d for d in C.table()[0] if d.startswith('2027')]), 16)


def _snap():
    try:
        return PB.series_from_snapshot()[0]
    except Exception:
        return None


@unittest.skipUnless(_snap() and len(_snap()) >= 150, '이 PC에 시세 사본(150개사 이상)이 있을 때만')
class AgainstPrices(unittest.TestCase):
    def test_2026_table_matches_actual_trading_days(self):
        """휴장일 표(2026)가 시세 사본의 실제 거래일(100개사 이상 거래된 날)과 하루도 어긋나지 않아야 한다."""
        cnt = {}
        for s in _snap().values():
            for d, _ in s:
                cnt[d] = cnt.get(d, 0) + 1
        trade = {d for d, n in cnt.items() if n >= 100}; last = max(trade)
        d = date(2026, 1, 1); bad = []
        while d.isoformat() <= last:
            x = d.isoformat()
            if C.is_open(x) != (x in trade):
                bad.append(x)
            d += timedelta(days=1)
        self.assertEqual(bad, []); self.assertGreaterEqual(last, '2026-06-30')


if __name__ == '__main__':
    unittest.main()
