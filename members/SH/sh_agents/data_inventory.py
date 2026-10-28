"""Bounded read-only inventory for two Agents. No raw documents or secrets in outputs."""
import os
from datetime import date

SPECS = {
    'core.price_daily': ('trade_date', ['open', 'high', 'low', 'close', 'volume']),
    'core.financial_fact': ('period_end', ['amount']),
    'core.financial_quarter': ('period_end', ['metric', 'amount']),
    'core.disclosure': ('rcept_dt', ['report_nm', 'url']),
    'rag.document': ('published_at', ['title', 'url']),
}
REQUIRED_MATERIALS = [
    ('산업·사업모델', '사업보고서 사업의 내용·제품/지역별 매출', '공시 원문·절·표 위치를 수동 검수'),
    ('산업·사업모델', '경쟁사 생산능력·증설·고객/공급자·대체재', '비교기업 공시·IR을 같은 기간으로 확보'),
    ('공통', '문서 버전·해시·원문 위치·사용 권한', 'URL/문서 건수만으로 확보·검증 완료 판단 불가'),
    ('기술적 분석', '수정주가 기준·분할/병합·권리락', '가격 수치만으로 조정 여부 확인 불가'),
    ('기술적 분석', '공식 거래일 달력', '정확한 누락 거래일 판정에 별도 필요'),
]


def open_connection(expected_role='agent_reader'):
    import psycopg
    from dotenv import load_dotenv
    from psycopg.rows import dict_row

    load_dotenv(override=False)
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise RuntimeError('DATABASE_URL 미설정: .env 또는 현재 환경에 읽기 전용 주소를 설정하세요.')
    conn = None
    try:
        conn = psycopg.connect(url, row_factory=dict_row, autocommit=True, connect_timeout=10,
                               options='-c default_transaction_read_only=on -c statement_timeout=15000')
        if conn.execute('SELECT current_user AS role').fetchone()['role'] != expected_role:
            conn.close()
            raise RuntimeError('지정한 읽기 전용 역할과 접속 역할이 다릅니다. 계정 설정을 확인하세요.')
        return conn
    except RuntimeError:
        raise
    except Exception:  # noqa: BLE001 - redact all driver/connection errors
        if conn is not None:
            conn.close()
        raise RuntimeError('DB 연결 실패: 주소·SSL·네트워크·읽기 계정 설정을 확인하세요. 접속정보는 출력하지 않습니다.') from None


def _ident(value):
    # Only schema metadata/fixed names reach this function; always quote identifiers.
    return '"' + value.replace('"', '""') + '"'


def _table(name):
    return '.'.join(_ident(x) for x in name.split('.'))


def _date_expr(column, dtype):
    col = _ident(column)
    if dtype in {'date', 'timestamp without time zone', 'timestamp with time zone'}:
        return col + '::date'
    # DART rcept_dt is sometimes stored as YYYYMMDD text. Invalid strings are excluded.
    return (f"CASE WHEN {col}::text ~ '^[0-9]{{8}}$' THEN to_date({col}::text,'YYYYMMDD') "
            f"WHEN {col}::text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}' "
            f"THEN substring({col}::text,1,10)::date ELSE NULL END")


class Inventory:
    def __init__(self, conn):
        self.conn = conn
        rows = conn.execute("""SELECT table_schema,table_name,column_name,data_type
            FROM information_schema.columns WHERE table_schema IN ('core','rag')""").fetchall()
        self.columns = {}
        for r in rows:
            self.columns.setdefault(r['table_schema'] + '.' + r['table_name'], {})[r['column_name']] = r['data_type']

    def companies(self, tickers, market='KR'):
        if not tickers or len(tickers) > 20:
            raise ValueError('종목은 1~20개로 제한합니다.')
        if not {'company_id', 'ticker', 'name', 'market'} <= self.columns.get('core.company', {}).keys():
            raise RuntimeError('core.company 필드 또는 조회 권한을 확인하세요.')
        return self.conn.execute('SELECT company_id,ticker,name,market FROM core.company '
                                 'WHERE ticker = ANY(%s) AND market = %s ORDER BY ticker',
                                 (list(tickers), market)).fetchall()

    def coverage(self, companies, start, end):
        start, end = date.fromisoformat(str(start)), date.fromisoformat(str(end))
        if start > end:
            raise ValueError('시작일은 종료일 이전이어야 합니다.')
        rows = []
        for company in companies:
            for table, (date_col, fields) in SPECS.items():
                cols = self.columns.get(table, {})
                row = {'종목': company['ticker'], '기업': company['name'], '테이블': table,
                       '요청 시작': start, '요청 종료': end, '기간 기준': date_col,
                       '상태': '확인 전', '건수': None, '최초': None, '최종': None,
                       '날짜 수': None, '날짜 결측': None, '필드 결측 건수 합': None, 'nullCounts': {}, '필드 결측': '', '추가 확보': ''}
                if not cols or 'company_id' not in cols or date_col not in cols:
                    row['상태'] = '스키마/권한 확인 필요'
                    row['추가 확보'] = '필수 연결/날짜 필드 부재 또는 조회 권한 제한; 0건으로 판단하지 않음'
                    rows.append(row)
                    continue
                expr = _date_expr(date_col, cols[date_col])
                missing = [f for f in fields if f not in cols]
                present = [f for f in fields if f in cols]
                nulls = ','.join(f'count(*) FILTER (WHERE {_ident(f)} IS NULL) AS {_ident("null_"+f)}'
                                 for f in present)
                sql = (f'SELECT count(*) AS n,min({expr}) AS first,max({expr}) AS last,'
                       f'count(DISTINCT {expr}) AS days'
                       + (',' + nulls if nulls else '')
                       + f' FROM {_table(table)} WHERE company_id=%s AND {expr} BETWEEN %s AND %s')
                try:
                    stats = self.conn.execute(sql, (company['company_id'], start, end)).fetchone()
                    undated = self.conn.execute(f'SELECT count(*) AS n FROM {_table(table)} '
                                               f'WHERE company_id=%s AND ({expr}) IS NULL',
                                               (company['company_id'],)).fetchone()['n']
                    row.update({'건수': stats['n'], '최초': stats['first'], '최종': stats['last'],
                                '날짜 수': stats['days'], '날짜 결측': undated,
                                '필드 결측 건수 합': sum(stats['null_'+f] for f in present),
                                'nullCounts': {f: stats['null_'+f] for f in present},
                                '상태': '기간 내 보유' if stats['n'] else '기간 내 0건',
                                '필드 결측': '; '.join(f'{f}: {stats["null_"+f]}건' for f in present),
                                '추가 확보': '스키마 필드 없음: ' + ', '.join(missing) if missing else ''})
                    if not stats['n']:
                        row['추가 확보'] += ' / 해당 기간 수집·적재 여부 확인'
                except Exception as exc:  # noqa: BLE001 - per-table failure with SQLSTATE only
                    row['상태'] = '조회 실패'
                    row['추가 확보'] = '권한·날짜 형식·시간 제한 확인 (SQLSTATE ' + str(
                        getattr(exc, 'sqlstate', None) or 'unknown') + ')'
                rows.append(row)
        return rows

    def price_gaps(self, company, start, end, trading_dates):
        """Calendar must match market/source scope; no weekday-as-trading-day assumption."""
        cols = self.columns.get('core.price_daily', {})
        if 'trade_date' not in cols:
            raise ValueError('시세 날짜 필드 또는 권한 없음')
        expr = _date_expr('trade_date', cols['trade_date'])
        rows = self.conn.execute(f'SELECT {expr} AS d, count(*) AS n FROM core.price_daily '
                                 f'WHERE company_id=%s AND {expr} BETWEEN %s AND %s '
                                 f'GROUP BY {expr}', (company['company_id'], start, end)).fetchall()
        observed = {str(r['d']): r['n'] for r in rows}
        expected = {str(d) for d in trading_dates if str(start) <= str(d) <= str(end)}
        if not expected:
            raise ValueError('지정 기간에 유효한 공식 거래일이 없습니다.')
        return {'종목': company['ticker'], '기대 거래일': len(expected),
                '누락 거래일': sorted(expected - observed.keys()),
                '달력 밖 날짜': sorted(observed.keys() - expected),
                '중복 날짜': sorted(d for d, n in observed.items() if n > 1)}


def acquisition_plan(coverage):
    plans = []
    for row in coverage:
        if row['상태'] != '기간 내 보유' or row['추가 확보'] or row['날짜 결측'] or row['필드 결측 건수 합']:
            plans.append({'종목': row['종목'], '대상': row['테이블'], '우선순위': '먼저 확인',
                          '할 일': row['추가 확보'] or '날짜/값 결측 및 기간 범위 확인'})
    for ticker in dict.fromkeys(row['종목'] for row in coverage):
        for domain, item, task in REQUIRED_MATERIALS:
            plans.append({'종목': ticker, '대상': domain, '우선순위': '내용 수동 검수',
                          '할 일': item + ' — ' + task})
    return plans
