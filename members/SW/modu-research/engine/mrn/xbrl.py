"""DART OpenAPI financial statements (XBRL-based) as a second official numeric source.

Endpoint: fnlttSinglAcntAll.json (단일회사 전체 재무제표). Values come with IFRS/DART account ids
(e.g. ifrs-full_Revenue), which are stable across companies -> scalable beyond table parsing.

Security: the API key is read only from the server environment (DART_API_KEY or MODU_NODES_DART_KEY).
It is never stored, logged, returned to the browser or written into cached files; error messages
are scrubbed of the request URL. Raw responses are cached with their sha256 so a re-run does not
call the API again (same call is not repeated) and results stay reproducible.
"""
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation

API = 'https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json'
CORP = {'005930': {'corp_code': '00126380', 'name': '삼성전자'}, '000660': {'corp_code': '00164779', 'name': 'SK하이닉스'}}
REPRT = {'11011': '사업보고서'}
# metric -> (account ids in priority order, statement kinds, unit)
MAP = {
    'revenue': (['ifrs-full_Revenue'], ('IS', 'CIS'), '백만원'),
    'operatingProfit': (['dart_OperatingIncomeLoss'], ('IS', 'CIS'), '백만원'),
    'netIncome': (['ifrs-full_ProfitLoss'], ('IS', 'CIS'), '백만원'),
    'netIncomeOwners': (['ifrs-full_ProfitLossAttributableToOwnersOfParent'], ('IS', 'CIS'), '백만원'),
    'cfo': (['ifrs-full_CashFlowsFromUsedInOperatingActivities'], ('CF',), '백만원'),
    'assets': (['ifrs-full_Assets'], ('BS',), '백만원'),
    'liabilities': (['ifrs-full_Liabilities'], ('BS',), '백만원'),
    'equity': (['ifrs-full_Equity'], ('BS',), '백만원'),
    'currentAssets': (['ifrs-full_CurrentAssets'], ('BS',), '백만원'),
    'currentLiabilities': (['ifrs-full_CurrentLiabilities'], ('BS',), '백만원'),
    'inventory': (['ifrs-full_Inventories'], ('BS',), '백만원'),
    'eps': (['ifrs-full_BasicEarningsLossPerShare'], ('IS', 'CIS'), '원'),
}
LABEL = {'revenue': '매출액', 'operatingProfit': '영업이익', 'netIncome': '당기순이익', 'netIncomeOwners': '지배기업 소유주 귀속 순이익',
         'cfo': '영업활동현금흐름', 'assets': '자산총계', 'liabilities': '부채총계', 'equity': '자본총계', 'currentAssets': '유동자산',
         'currentLiabilities': '유동부채', 'inventory': '재고자산', 'eps': '기본주당이익'}
STATUS = {'000': '정상', '010': '등록되지 않은 키', '011': '사용할 수 없는 키', '012': '접근할 수 없는 IP', '013': '조회된 데이터 없음',
          '014': '파일이 존재하지 않음', '020': '요청 제한 초과', '021': '조회 가능한 회사 개수 초과', '100': '필드의 부적절한 값',
          '101': '부적절한 접근', '800': '시스템 점검', '900': '정의되지 않은 오류', '901': '사용자 계정 개인정보 보유기간 만료'}


class XbrlError(RuntimeError):
    pass


def api_key():
    return os.environ.get('DART_API_KEY') or os.environ.get('MODU_NODES_DART_KEY') or ''


def cache_dir(data_dir):
    d = os.path.join(data_dir, 'xbrl')
    os.makedirs(d, exist_ok=True)
    return d


def _scrub(msg, key):
    msg = str(msg)
    if key:
        msg = msg.replace(key, '***')
    return re.sub(r'crtfc_key=[^&\s]+', 'crtfc_key=***', msg)


def fetch(data_dir, code, year, reprt='11011', fs_div='CFS', refresh=False, opener=None):
    """Return (raw_dict, cache_info). Uses cache unless refresh=True."""
    if code not in CORP:
        raise XbrlError(f'지원하지 않는 기업 코드: {code} (현재 {", ".join(CORP)})')
    name = f'{code}_{year}_{reprt}_{fs_div}.json'
    path = os.path.join(cache_dir(data_dir), name)
    if os.path.exists(path) and not refresh:
        with open(path, 'rb') as fh:
            raw = fh.read()
        return json.loads(raw), {'cached': True, 'file': name, 'sha256': hashlib.sha256(raw).hexdigest()}
    key = api_key()
    if not key:
        raise XbrlError('DART_API_KEY가 설정되지 않았습니다. local-env.cmd에 set DART_API_KEY=... 를 넣고 서버를 다시 시작하세요.')
    q = urllib.parse.urlencode({'crtfc_key': key, 'corp_code': CORP[code]['corp_code'], 'bsns_year': str(year), 'reprt_code': reprt, 'fs_div': fs_div})
    try:
        op = opener or urllib.request.urlopen
        with op(API + '?' + q, timeout=30) as r:
            body = r.read()
    except Exception as e:
        raise XbrlError('OpenDART 호출 실패: ' + _scrub(f'{type(e).__name__}: {e}', key))
    try:
        data = json.loads(body.decode('utf-8'))
    except Exception:
        raise XbrlError('OpenDART 응답을 해석할 수 없습니다.')
    st = data.get('status')
    if st != '000':
        raise XbrlError(f"OpenDART 상태 {st}: {STATUS.get(st, data.get('message', ''))}")
    data['_fetched_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    data['_request'] = {'corp_code': CORP[code]['corp_code'], 'bsns_year': str(year), 'reprt_code': reprt, 'fs_div': fs_div}  # no key
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True).encode('utf-8')
    with open(path, 'wb') as fh:
        fh.write(raw)
    return data, {'cached': False, 'file': name, 'sha256': hashlib.sha256(raw).hexdigest()}


def _num(s):
    s = (s or '').replace(',', '').strip()
    if s in ('', '-'):
        return None
    neg = s.startswith('(') and s.endswith(')')
    try:
        v = Decimal(s.strip('()'))
    except InvalidOperation:
        return None
    return -v if neg else v


def parse(data, code, year):
    """-> facts list: one per (metric, year) for current and prior period."""
    rows = data.get('list') or []
    out = []
    for metric, (ids, kinds, unit) in MAP.items():
        row = None
        for aid in ids:
            cand = [r for r in rows if r.get('account_id') == aid and r.get('sj_div') in kinds]
            cand.sort(key=lambda r: kinds.index(r['sj_div']))
            if cand:
                row = cand[0]
                break
        if not row:
            continue
        for col, y in (('thstrm_amount', year), ('frmtrm_amount', year - 1)):
            v = _num(row.get(col))
            if v is None:
                continue
            val = v if unit == '원' else v / Decimal(1000000)
            out.append({'fact_id': f'xbrl:{code}:{y}:{metric}', 'company': code, 'company_name': CORP[code]['name'], 'year': y,
                        'metric': metric, 'label': LABEL[metric], 'value': format(val.normalize(), 'f') if val == val.to_integral() else str(val),
                        'unit': unit, 'raw_value': row.get(col), 'raw_unit': row.get('currency') or 'KRW',
                        'account_id': row.get('account_id'), 'account_nm': row.get('account_nm'), 'sj_div': row.get('sj_div'),
                        'rcept_no': row.get('rcept_no'), 'kind': 'fact_official', 'source': 'DART OpenAPI fnlttSinglAcntAll (XBRL 기반)'})
    return out


def crosscheck(xfacts, cell_facts):
    """Compare XBRL values with the table-cell facts (N01). Exact match expected (both 백만원)."""
    by = {}
    for f in cell_facts.values():
        by[(f.get('company'), int(f.get('period') or f.get('year') or 0), f.get('metric'))] = f
    alias = {'cfo': ('cfo', 'operatingCashFlow')}
    rows = []
    for x in xfacts:
        keys = alias.get(x['metric'], (x['metric'],))
        cf = next((by[(x['company'], x['year'], k)] for k in keys if (x['company'], x['year'], k) in by), None)
        if not cf:
            continue
        a, b = Decimal(str(x['value'])), Decimal(str(cf['value']))
        rows.append({'company': x['company'], 'year': x['year'], 'metric': x['metric'], 'label': x['label'], 'xbrl': x['value'],
                     'cell': str(cf['value']), 'match': a == b, 'diff': str(a - b), 'cell_fact': cf.get('fact_id')})
    return rows
