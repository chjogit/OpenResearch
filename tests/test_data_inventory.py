from datetime import date

import pytest

from agent.data_inventory import Inventory, acquisition_plan


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0]


class Connection:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if 'information_schema' in sql:
            return Cursor([{'table_schema': 'core', 'table_name': 'price_daily',
                            'column_name': c, 'data_type': 'date' if c == 'trade_date' else 'numeric'}
                           for c in ['company_id', 'trade_date', 'open', 'high', 'low', 'close', 'volume']])
        if 'GROUP BY' in sql:
            return Cursor([{'d': date(2026, 10, 26), 'n': 2}])
        if 'AS first' in sql:
            return Cursor([{'n': 2, 'first': date(2026, 10, 26), 'last': date(2026, 10, 26), 'days': 1,
                            'null_open': 1, 'null_high': 0, 'null_low': 0, 'null_close': 0, 'null_volume': 0}])
        return Cursor([{'n': 0}])


COMPANIES = [{'company_id': 1, 'ticker': '005930', 'name': '테스트기업', 'market': 'KR'}]


def test_coverage_unknown_schema_and_null_plan():
    conn = Connection()
    inv = Inventory(conn)
    rows = inv.coverage(COMPANIES, '2026-10-01', '2026-10-27')
    assert rows[0]['건수'] == 2
    assert rows[0]['필드 결측 건수 합'] == 1
    assert rows[1]['상태'] == '스키마/권한 확인 필요'
    assert rows[1]['건수'] is None
    assert acquisition_plan(rows)[0]['대상'] == 'core.price_daily'
    assert all('UPDATE' not in sql and 'INSERT' not in sql for sql, _ in conn.calls)
    assert conn.calls[1][1] == (1, date(2026, 10, 1), date(2026, 10, 27))


def test_official_calendar_gaps_and_duplicate():
    inv = Inventory(Connection())
    result = inv.price_gaps(COMPANIES[0], '2026-10-26', '2026-10-27',
                            ['2026-10-26', '2026-10-27'])
    assert result['누락 거래일'] == ['2026-10-27']
    assert result['중복 날짜'] == ['2026-10-26']
    with pytest.raises(ValueError):
        inv.price_gaps(COMPANIES[0], '2026-10-26', '2026-10-27', [])


def test_query_failure_not_leak_credentials():
    class Broken(Connection):
        def execute(self, sql, params=None):
            if 'information_schema' in sql:
                return super().execute(sql, params)
            raise RuntimeError('postgresql://username:secret@private-host/db')
    rows = Inventory(Broken()).coverage(COMPANIES, '2026-10-01', '2026-10-27')
    assert rows[0]['상태'] == '조회 실패'
    assert 'secret' not in str(rows) and 'private-host' not in str(rows)


def test_invalid_scope():
    inv = Inventory(Connection())
    with pytest.raises(ValueError):
        inv.companies([])
    with pytest.raises(ValueError):
        inv.coverage(COMPANIES, '2026-10-27', '2026-10-01')
