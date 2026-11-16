"""Neon 공용 DB 사본(_sources/neon/<asof>/) 읽기 — T06 가격·거래량.

앱은 실행 중 DB에 접속하지 않는다. PC에서 _tools/neon_snapshot 으로 만든 사본만 읽고,
매 실행마다 manifest 해시와 표 파일 해시를 다시 대조한다. 어긋나면 사용하지 않는다(보류).
"""
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import price_src as _PS   # v0.39.3 가격 출처(금융위 + KIS 보충, 연구용 스위치)

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))
MARKET_CLOSE_KST = (15, 30)


class SnapshotError(RuntimeError):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def neon_dir():
    return Path(os.environ.get('MODU_NODES_NEON_DIR') or ROOT.parent / '_sources' / 'neon')


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def list_snapshots():
    d = neon_dir()
    if not d.exists():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_dir() and (p / 'manifest.json').exists())


def resolve(snapshot=''):
    d = neon_dir()
    name = (snapshot or '').strip()
    if not name or name == 'latest':
        latest = d / 'LATEST.txt'
        if not latest.exists():
            raise SnapshotError('no_snapshot', 'Neon 사본이 없습니다. PC에서 _tools\\neon_snapshot\\run-neon-snapshot.cmd 를 실행하세요.')
        name = latest.read_text(encoding='utf-8').strip()
    root = d / name
    if not (root / 'manifest.json').exists():
        raise SnapshotError('snapshot_missing', f'사본 {name} 이 없습니다.')
    return root


def load_manifest(root):
    mp = root / 'manifest.json'
    want = (root / 'manifest.sha256').read_text(encoding='utf-8').replace('\r', '').split()[0]
    got = _sha(mp)
    if got != want:
        raise SnapshotError('manifest_changed', '사본 목록(manifest.json)의 해시가 기록과 다릅니다. 변조 또는 손상 가능성이 있어 사용하지 않습니다.')
    man = json.loads(mp.read_text(encoding='utf-8'))
    man['_manifest_sha256'] = got
    return man


def read_table(root, man, table):
    meta = man['tables'].get(table)
    if not meta:
        raise SnapshotError('table_missing', f'사본에 {table} 표가 없습니다.')
    p = root / meta['file']
    if _sha(p) != meta['sha256']:
        raise SnapshotError('table_changed', f'{table} 사본 파일의 해시가 목록과 다릅니다. 사용하지 않습니다.')
    rows = [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]
    if len(rows) != meta['rows']:
        raise SnapshotError('table_rows', f'{table} 행 수가 목록과 다릅니다.')
    return rows, meta


def read_rows(root, man, table, company=None):
    """기업별로 나뉜 표(v3)는 그 기업 파일 하나만 읽는다. 나뉘지 않은 표(v2)는 전체를 읽고 기업으로 거른다."""
    meta = man['tables'].get(table)
    if not meta:
        raise SnapshotError('table_missing', f'사본에 {table} 표가 없습니다.')
    if not meta.get('partitioned'):
        rows, meta = read_table(root, man, table)
        if company is not None:
            rows = [r for r in rows if r.get('ticker') == company]
        return rows, meta
    if company is None:
        raise SnapshotError('need_company', f'{table} 표는 기업별로 나뉘어 있어 기업을 지정해야 합니다.')
    part = meta['parts'].get(company)
    info = {k: v for k, v in meta.items() if k != 'parts'}
    if not part:
        info.update(file=f'{table}/(없음:{company})', sha256='', rows=0)
        return [], info
    p = root / part['file']
    if _sha(p) != part['sha256']:
        raise SnapshotError('table_changed', f'{table}/{company} 사본 파일의 해시가 목록과 다릅니다. 사용하지 않습니다.')
    rows = [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]
    if len(rows) != part['rows']:
        raise SnapshotError('table_rows', f'{table}/{company} 행 수가 목록과 다릅니다.')
    info.update(file=part['file'], sha256=part['sha256'], rows=part['rows'])
    return rows, info


_UNI = {}


def companies(root, man):
    """사본의 기업 목록(이름·시장·업종). manifest 해시로 캐시한다."""
    key = ('co', man['_manifest_sha256'])
    if key not in _UNI:
        try:
            rows, _ = read_table(root, man, 'company')
        except SnapshotError:
            rows = []
        _UNI.clear() if len(_UNI) > 8 else None
        _UNI[key] = {r['ticker']: r for r in rows}
    return _UNI[key]


COVER_LABEL = {
    'price_fsc': '시세(금융위)', 'flow': '투자자별 매매', 'lending': '대차잔고', 'fin_annual': '연간 재무',
    'fin_quarter': '분기 재무', 'exposure': '공시 민감도', 'peer_manual': '비교기업(팀 선정)', 'peer_auto': '비교기업(자동)',
    'disclosure': '공시 목록', 'news': '뉴스', 'sentiment': '뉴스 분위기', 'holder': '최대주주', 'ownership': '지분 공시',
    'dart_archive': 'DART 원문', 'price_other': '시세(기타)'}
# 근거 지도 열 → 앱 노드. 이 자료가 있으면 그 노드를 그 기업에 쓸 수 있다(키트별).
COVER_NODES = {'price_fsc': ['T06', 'N09', 'N10', 'N12', 'N17', 'N18'], 'flow': ['T07', 'N07', 'N08'], 'lending': ['T07'],
               'fin_quarter': ['N03', 'N14'], 'fin_annual': ['T11', 'N01', 'N17', 'N18'], 'exposure': ['T11', 'N05', 'N06'],
               'peer_manual': ['T09', 'N03', 'N04'], 'disclosure': ['T08', 'N11', 'N12'], 'news': ['T08', 'N11'], 'sentiment': ['N11'],
               'holder': ['T12', 'N13'], 'ownership': ['T12', 'N13'], 'dart_archive': ['T02']}
READY_NOW = {'price_fsc', 'flow', 'lending', 'fin_annual', 'exposure', 'disclosure', 'news', 'sentiment', 'holder', 'ownership'}   # 지금 모든 회사에 바로 쓰는 자료


def universe(snapshot=''):
    root = resolve(snapshot)
    man = load_manifest(root)
    key = ('uni', man['_manifest_sha256'])
    if key in _UNI:
        return _UNI[key]
    cos = companies(root, man)
    cov = {}
    if 'coverage' in man['tables']:
        rows, _ = read_table(root, man, 'coverage')
        cov = {r['ticker']: {k: v for k, v in r.items() if k != 'ticker'} for r in rows}
    cols = [k for k in COVER_LABEL if any(k in c for c in cov.values())] if cov else []
    out = []
    for t, c in cos.items():
        cv = cov.get(t, {})
        out.append({'ticker': t, 'name': c.get('name'), 'market': c.get('market'), 'sector': c.get('sector'),
                    'sector_desc': c.get('sector_desc'), 'krx_sector': c.get('krx_sector'), 'index_tags': c.get('index_tags'),
                    'cover': {k: {'n': (cv.get(k) or {}).get('n') or 0, 'last': (cv.get(k) or {}).get('x')} for k in cols}})
    summary = {k: sum(1 for r in out if r['cover'][k]['n']) for k in cols}
    res = {'snapshot': root.name, 'manifest_sha256': man['_manifest_sha256'], 'tool_version': man.get('tool_version'),
           'asof': man.get('asof') or root.name, 'count': len(out), 'columns': [{'key': k, 'label': COVER_LABEL[k], 'nodes': COVER_NODES.get(k, []),
           'ready_now': k in READY_NOW} for k in cols], 'summary': summary, 'companies': out, 'has_coverage': bool(cov),
           'failed': man.get('failed') or {}}
    _UNI[key] = res
    return res


def company_name(company, snapshot=''):
    try:
        root = resolve(snapshot); man = load_manifest(root)
        c = companies(root, man).get(company)
        return c.get('name') if c else None
    except SnapshotError:
        return None


def name_index(snapshot=''):
    """질문 속 기업 이름 찾기용: {이름: 종목코드} (국내만). 사본이 없으면 빈 사전."""
    try:
        root = resolve(snapshot); man = load_manifest(root)
    except SnapshotError:
        return {}
    key = ('names', man['_manifest_sha256'])
    if key not in _UNI:
        _UNI[key] = {c['name']: t for t, c in companies(root, man).items() if c.get('market') == 'KR' and c.get('name')}
    return _UNI[key]


def last_usable_date(cutoff):
    """기준시점에 이미 확정된 마지막 거래일: 장 마감(15:30 KST) 전이면 전날까지."""
    at = datetime.fromisoformat(cutoff).astimezone(KST)
    d = at.date()
    if (at.hour, at.minute) < MARKET_CLOSE_KST:
        d = d - timedelta(days=1)
    return d.isoformat()


def price_quality(rows):
    """v0.36.1 (P04 이식, 규칙 price-quality-1): 시세 품질 검사. 걸린 날을 표시만 하고 채우거나 지우지 않는다."""
    def f(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    seen, dup, bad, ohlc, zero = set(), [], [], [], []
    for r in rows:
        d = r['trade_date']
        if d in seen:
            dup.append(d)
        seen.add(d)
        o, h, l, c, v = (f(r.get(k)) for k in ('open', 'high', 'low', 'close', 'volume'))
        if c is None or c <= 0:
            bad.append(d); continue
        if None in (o, h, l) or min(o, h, l) <= 0 or h < max(o, c, l) or l > min(o, c, h):
            ohlc.append(d)
        if v is not None and v == 0:
            zero.append(d)
    return {'rule': 'price-quality-1', 'checked': len(rows), 'duplicate_dates': dup, 'bad_close': bad, 'ohlc_errors': ohlc, 'zero_volume': zero}


def price_series(company, cutoff, snapshot='', lookback=260):
    root = resolve(snapshot)
    man = load_manifest(root)
    cos = companies(root, man)
    if cos and company not in cos:
        raise SnapshotError('company_unknown', f'사본 기업 목록에 {company} 가 없습니다. 근거 지도에서 종목코드를 확인하세요.')
    rows, meta = read_rows(root, man, 'price_daily', company)
    last = last_usable_date(cutoff)
    mine = _PS.pick(r for r in rows if r['trade_date'] <= last)   # v0.39.3: 금융위 + KIS 보충, 같은 날은 금융위 우선
    if not mine:
        raise SnapshotError('no_rows', f'{company} 의 금융위 시세가 사본에 없습니다(해외 기업이거나 수집 전).')
    later = sum(1 for r in rows if r['trade_date'] > last)
    if lookback:
        mine = mine[-int(lookback):]
    gaps = []
    for a, b in zip(mine, mine[1:]):
        da, db = datetime.fromisoformat(a['trade_date']), datetime.fromisoformat(b['trade_date'])
        if (db - da).days > 6:
            gaps.append({'from': a['trade_date'], 'to': b['trade_date'], 'calendar_days': (db - da).days})
    jumps = []
    for a, b in zip(mine, mine[1:]):
        try:
            ch = float(b['close']) / float(a['close']) - 1
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if abs(ch) > 0.3001:
            jumps.append({'date': b['trade_date'], 'change_pct': round(ch * 100, 2), 'prev_close': a['close'], 'close': b['close']})
    names = {t: c.get('name') for t, c in cos.items()}
    collected = max((r['collected_at'] for r in mine), default=None)
    nk = _PS.kis_count(mine)   # v0.39.3
    return {
        'company': company, 'name': names.get(company, company), 'cutoff': cutoff, 'last_usable_date': last,
        'rows': [{k: r[k] for k in ('trade_date', 'open', 'high', 'low', 'close', 'volume', 'trade_value', 'market_cap')} for r in mine],
        'excluded_after_cutoff': later, 'gaps': gaps, 'limit_breaks': jumps, 'adjusted': False, 'quality': price_quality(mine),
        'source': {'snapshot': root.name, 'table': 'core.price_daily', 'file': meta['file'], 'sha256': meta['sha256'],
                   'manifest_sha256': man['_manifest_sha256'], 'source_grade': meta['source_grade'], 'query': meta['query'],
                   'origin': '금융위원회 주식시세정보(fsc) — Neon 공용 DB 경유' + (f' + 한국투자증권 일별 시세(kis) {nk}거래일 보충(연구용·재배포 계약 전)' if nk else ''),
                   'collected_at_max': collected, 'kis_rows': nk},
        'notes': ['금융위원회 시세 원값(수정주가 아님). 액면분할·배당 조정을 하지 않았습니다.',
                  f'기준시점에 확정된 거래일({last})까지만 사용했습니다.',
                  '자료 수집 시각은 기준시점보다 늦을 수 있습니다(과거 거래일 값은 수집 후 바뀌지 않는다는 전제).'],
    }


def _ticker_rows(root, man, table, company, last, datecol='trade_date'):
    rows, meta = read_rows(root, man, table, company)
    mine = sorted((r for r in rows if str(r[datecol])[:10] <= last), key=lambda r: r[datecol])
    later = sum(1 for r in rows if str(r[datecol])[:10] > last)
    return mine, meta, later


def _src(root, man, meta, table, origin):
    return {'snapshot': root.name, 'table': table, 'file': meta['file'], 'sha256': meta['sha256'],
            'manifest_sha256': man['_manifest_sha256'], 'source_grade': meta['source_grade'], 'origin': origin}


def flow_series(company, cutoff, snapshot='', lookback=260):
    """T07: 투자자별 순매수(포털 수집) + 대차잔고(금융위). 둘 다 사본 해시 재대조."""
    root = resolve(snapshot)
    man = load_manifest(root)
    last = last_usable_date(cutoff)
    cos = companies(root, man)
    if cos and company not in cos:
        raise SnapshotError('company_unknown', f'사본 기업 목록에 {company} 가 없습니다. 근거 지도에서 종목코드를 확인하세요.')
    flows, fmeta, later = _ticker_rows(root, man, 'investor_flow_daily', company, last)
    if not _PS.ok('kis'):   # v0.39.5 연구용 스위치(MODU_PRICE_KIS=0)면 KIS 수급 보충 행도 쓰지 않음
        flows = [r for r in flows if r.get('source') != 'kis_investor']
    if not flows:
        raise SnapshotError('no_rows', f'{company} 의 투자자별 매매 자료가 사본에 없습니다.')
    if lookback:
        flows = flows[-int(lookback):]
    lend, lmeta, _ = [], None, 0
    try:
        lend, lmeta, _ = _ticker_rows(root, man, 'stock_lending_daily', company, last)
    except SnapshotError as e:
        if e.code != 'table_missing':
            raise
    names = {t: c.get('name') for t, c in cos.items()}
    shares = {t: c.get('shares_outstanding') for t, c in cos.items()}
    nkf = sum(1 for r in flows if r.get('source') == 'kis_investor')   # v0.39.5
    src = {'flows': _src(root, man, fmeta, 'core.investor_flow_daily', '네이버 금융 투자자별 매매(포털 수집) — Neon 공용 DB 경유'
                         + (f' + 한국투자증권 투자자별 매매(kis) {nkf}거래일 보충(연구용·재배포 계약 전)' if nkf else ''))}
    src['flows']['kis_rows'] = nkf
    if lmeta:
        src['lending'] = _src(root, man, lmeta, 'core.stock_lending_daily', '금융위원회 대차거래 정보(fsc) — Neon 공용 DB 경유')
    return {
        'company': company, 'name': names.get(company, company), 'cutoff': cutoff, 'last_usable_date': last,
        'rows': [{k: r.get(k) for k in ('trade_date', 'foreign_net_qty', 'institution_net_qty', 'individual_net_qty', 'foreign_hold_pct', 'volume')} for r in flows],
        'lending': [{k: r.get(k) for k in ('trade_date', 'balance_qty', 'balance_amt', 'lent_qty', 'repaid_qty')} for r in lend],
        'shares_outstanding': shares.get(company), 'excluded_after_cutoff': later, 'source': src,
        'notes': ['투자자별 순매수는 포털(네이버)에서 수집한 값이며, 거래소(KRX) 공식 자료와 아직 대조하지 않았습니다.'
                  + (f' 최근 {nkf}거래일은 한국투자증권 조회값으로 보충했습니다(겹치는 날 네이버 값과 주 단위까지 같음을 확인한 회사만).' if nkf else ''),
                  '순매수는 주식 수(주) 기준입니다. 금액 기준이 아닙니다.',
                  f'기준시점에 확정된 거래일({last})까지만 사용했습니다.'],
    }


# ---------------------------------------------------------------- T09 비교기업 / T10 거시 시계열
from datetime import date as _date

REPORT_LAG_DAYS = 45          # 분기 말 이후 공시까지 걸리는 기간(국내 분기보고서 기한) — 기준시점에 이미 공개됐다고 볼 수 있는 분기만 쓴다
STALE_DAYS = 200              # 마지막 분기가 이보다 오래되면 비교에서 뺀다
KR_CHIP = {'2611', '2612'}    # 한국표준산업분류: 전자집적회로 / 다이오드·트랜지스터 등 반도체소자
US_CHIP = {'3674', '3663'}    # SIC: 반도체·관련 소자 / 무선통신장비(팹리스 일부)
US_EQUIP = {'3559', '3825', '3827'}


def peer_role(c, base_tickers=()):
    """비교기업 역할 분류(규칙). 반도체 제조·설계 / 장비 / 소재 / 부품·기타."""
    t, sec, mkt = c.get('ticker'), str(c.get('sector') or ''), c.get('market')
    if t in base_tickers or t in ('005930', '000660'):
        return 'chip'
    if mkt == 'US':
        return 'chip' if sec in US_CHIP else 'equipment' if sec in US_EQUIP else 'other'
    if sec in KR_CHIP:
        return 'chip'
    if sec.startswith('29'):
        return 'equipment'
    if sec.startswith('20'):
        return 'materials'
    return 'parts'


ROLE_LABEL = {'chip': '반도체 제조·설계', 'equipment': '반도체 장비', 'materials': '반도체 소재', 'parts': '부품·기타', 'other': '기타'}


def peer_package(company, cutoff, snapshot='', method_prefix='manual:'):
    root = resolve(snapshot)
    man = load_manifest(root)
    last = last_usable_date(cutoff)
    pg, pgm = read_table(root, man, 'peer_group')
    groups = sorted({(r['method'], r['peer_group_id']) for r in pg if r['base_ticker'] == company})
    chosen = [g for g in groups if g[0].startswith(method_prefix)] or groups
    if not chosen:
        raise SnapshotError('no_peer_group', f'{company}의 비교기업 묶음이 사본에 없습니다.')
    method, gid = chosen[0]
    members = sorted((r for r in pg if r['peer_group_id'] == gid), key=lambda r: r['rank'])
    pc, pcm = read_table(root, man, 'peer_company')
    comp = {c['ticker']: c for c in pc}
    fq, fqm = read_table(root, man, 'peer_financial_quarter')
    pp, ppm = read_table(root, man, 'peer_price_daily')
    lim = (_date.fromisoformat(last) - timedelta(days=REPORT_LAG_DAYS)).isoformat()
    tick = [company] + [m['ticker'] for m in members if m['ticker'] != company]
    fin = {t: sorted((r for r in fq if r['ticker'] == t and str(r['period_end']) <= lim), key=lambda r: (r['period_end'], r['metric'])) for t in tick}
    cap = {}
    for t in tick:
        rows = [r for r in pp if r['ticker'] == t and r['trade_date'] <= last and r.get('source') == 'fsc' and r.get('market_cap')]
        if rows:
            r = max(rows, key=lambda r: r['trade_date']); cap[t] = {'date': r['trade_date'], 'market_cap': r['market_cap']}
    excluded = [{'method': g[0], 'reason': '업종 분류만 같고 사업이 다른 회사가 섞여 있어 쓰지 않음'} for g in groups if g != chosen[0]]
    return {
        'company': company, 'name': comp.get(company, {}).get('name', company), 'cutoff': cutoff, 'last_usable_date': last,
        'financial_cutoff': lim, 'group': {'method': method, 'peer_group_id': gid, 'excluded_groups': excluded},
        'members': [{'ticker': m['ticker'], 'name': m['name'], 'rank': m['rank'], 'reason': m['reason'],
                     'market': comp.get(m['ticker'], {}).get('market'), 'sector': comp.get(m['ticker'], {}).get('sector'),
                     'role': peer_role(comp.get(m['ticker'], {'ticker': m['ticker']}), (company,))} for m in members if m['ticker'] != company],
        'financials': {t: [{k: r.get(k) for k in ('period_end', 'fiscal_year', 'fiscal_q', 'metric', 'amount', 'currency', 'source')} for r in rows] for t, rows in fin.items()},
        'market_cap': cap,
        'source': {'peer_group': _src(root, man, pgm, 'core.peer_group', '팀이 고른 비교기업 묶음 (Neon 공용 DB)'),
                   'financials': _src(root, man, fqm, 'core.financial_quarter', 'DART(국내)·SEC EDGAR(해외) 분기 재무 (Neon 공용 DB)'),
                   'prices': _src(root, man, ppm, 'core.price_daily', '금융위 시세(국내만 시가총액에 사용)')},
        'notes': [f'비교군: 「{method}」 묶음 (팀이 고른 목록). 업종 자동 묶음은 사업이 달라 쓰지 않았습니다.',
                  f'분기 재무는 분기 말 후 {REPORT_LAG_DAYS}일이 지난 것({lim} 이전 분기 말)만 썼습니다 — 기준시점에 공개됐다고 볼 수 있는 것만.',
                  '해외 기업은 달러 기준이라 금액은 비교하지 않고 비율(성장률·이익률·부채비율)만 비교합니다.',
                  '시가총액 순위는 금융위 시세가 있는 국내 기업만 셉니다.'],
    }


AVAIL_LAG = {'D': 0, 'M': 45, 'Q': 75}


def macro_series(cutoff, snapshot=''):
    """T10: 거시 지표 25종. 기준시점에 공개됐다고 볼 수 있는 관측만(일별=당일, 월별=말일+15일 무렵, 분기=+75일)."""
    root = resolve(snapshot)
    man = load_manifest(root)
    last = last_usable_date(cutoff)
    ser, sm = read_table(root, man, 'macro_series')
    obs, om = read_table(root, man, 'macro_obs')
    out = {}
    for s in ser:
        lag = AVAIL_LAG.get(s.get('frequency') or 'D', 30)
        lim = (_date.fromisoformat(last) - timedelta(days=lag)).isoformat()
        kcs = s.get('source') == 'kcs' and (s.get('frequency') or 'M') == 'M'
        if kcs:
            lag = '다음 달 1일'          # 관세청 월간 수출입은 다음 달 1일 공개
        def ok(d):
            if not kcs:
                return d <= lim
            y, m = int(d[:4]), int(d[5:7])
            nxt = f'{y + (m == 12):04d}-{m % 12 + 1:02d}-01'
            return nxt <= last
        rows = sorted(((str(o['obs_date'])[:10], o['value']) for o in obs if o['series_id'] == s['series_id'] and ok(str(o['obs_date'])[:10])), key=lambda x: x[0])
        out[s['series_id']] = {'name': s['name'], 'source': s['source'], 'frequency': s['frequency'], 'unit': s.get('unit'),
                               'availability_lag_days': lag, 'obs': [[d, v] for d, v in rows]}
    return {'cutoff': cutoff, 'last_usable_date': last, 'series': out,
            'source': {'series': _src(root, man, sm, 'core.macro_series', 'Neon 공용 DB'), 'obs': _src(root, man, om, 'core.macro_obs', 'FRED·한국은행 ECOS·관세청 (Neon 공용 DB)')},
            'notes': ['월별 지표는 그 달 말일 후 약 45일, 분기 지표는 약 75일이 지난 관측만 썼습니다(공개 시차 가정).']}


# ---------------------------------------------------------------- T11 회사 공시 재무·민감도 (키트 2)
ACCOUNT_METRIC = {
    'ifrs-full_Revenue': 'revenue', 'dart_OperatingIncomeLoss': 'operatingProfit',
    'ifrs-full_ProfitLoss': 'netIncome', 'ifrs-full_ProfitLossAttributableToOwnersOfParent': 'netIncomeOwners',
    'ifrs-full_CashFlowsFromUsedInOperatingActivities': 'cfo', 'ifrs-full_Assets': 'assets',
    'ifrs-full_Liabilities': 'liabilities', 'ifrs-full_Equity': 'equity', 'ifrs-full_CurrentAssets': 'currentAssets',
    'ifrs-full_CurrentLiabilities': 'currentLiabilities', 'ifrs-full_Inventories': 'inventory',
    'ifrs-full_BasicEarningsLossPerShare': 'eps',
    'ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities': 'ppeAcquisition',
    'ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities': 'intangibleAcquisition'}
REPORT_LABEL = {'11011': '사업보고서(연간)', '11012': '반기보고서', '11013': '1분기보고서', '11014': '3분기보고서'}
SJ_RANK = {'IS': 0, 'CIS': 1, 'BS': 0, 'CF': 0}


def _filed_date(rcept_no):
    r = str(rcept_no or '')
    return f'{r[:4]}-{r[4:6]}-{r[6:8]}' if len(r) >= 8 and r[:8].isdigit() else None


def company_filings(company, cutoff, snapshot=''):
    """T11: 공시 API 재무(연간 사업보고서, 연결 우선) + 공시 민감도. 기준시점 이전에 접수된 보고서만."""
    root = resolve(snapshot)
    man = load_manifest(root)
    cos = companies(root, man)
    if cos and company not in cos:
        raise SnapshotError('company_unknown', f'사본 기업 목록에 {company} 가 없습니다.')
    if 'financial_fact' not in man['tables']:
        raise SnapshotError('table_missing', '사본에 financial_fact 표가 없습니다. 사본 도구 v4로 다시 받아 주세요.')
    last = last_usable_date(cutoff)
    ff, fm = read_rows(root, man, 'financial_fact', company)
    later, chosen = 0, {}
    for r in ff:
        if r.get('report_code') != '11011' or r.get('account_id') not in ACCOUNT_METRIC:
            continue
        fd = _filed_date(r.get('rcept_no'))
        if not fd or fd > last:
            later += 1
            continue
        key = (int(r['fiscal_year']), ACCOUNT_METRIC[r['account_id']])
        rank = (0 if r.get('fs_div') == 'CFS' else 1, SJ_RANK.get(r.get('sj_div'), 2), -int(fd.replace('-', '')))
        if key not in chosen or rank < chosen[key][0]:
            chosen[key] = (rank, r, fd)
    facts = []
    for (y, m), (_, r, fd) in sorted(chosen.items()):
        facts.append({'year': y, 'metric': m, 'account_id': r['account_id'], 'account_nm': r.get('account_nm'),
                      'amount': r.get('amount'), 'currency': r.get('currency'), 'fs_div': r.get('fs_div'), 'sj_div': r.get('sj_div'),
                      'rcept_no': r.get('rcept_no'), 'filed_at': fd, 'period_end': r.get('period_end')})
    exp, em = [], None
    if 'report_exposure' in man['tables']:
        rows, em = read_rows(root, man, 'report_exposure', company)
        for r in rows:
            fd = _filed_date(r.get('rcept_no'))
            if fd and fd <= last:
                exp.append({k: r.get(k) for k in ('fiscal_year', 'rcept_no', 'metric', 'currency', 'value', 'change_pct', 'basis', 'unit_raw', 'evidence', 'file', 'table_index')} | {'filed_at': fd})
    quarters = []
    if 'financial_quarter' in man['tables']:
        lim = (_date.fromisoformat(last) - timedelta(days=REPORT_LAG_DAYS)).isoformat()
        qr, qm = read_rows(root, man, 'financial_quarter', company)
        quarters = sorted(({'period_end': str(r['period_end'])[:10], 'fiscal_year': r.get('fiscal_year'), 'fiscal_q': r.get('fiscal_q'),
                            'metric': r['metric'], 'amount': r.get('amount'), 'currency': r.get('currency')}
                           for r in qr if str(r['period_end'])[:10] <= lim), key=lambda x: (x['period_end'], x['metric']))
    from .edi import dart_quarters
    dq = dart_quarters([r for r in ff if (_filed_date(r.get('rcept_no')) or '9999') <= last])
    # v0.24 분기 성적표용: 기준시점까지 접수된 정기보고서의 분기 단독 매출·영업이익, 잠정실적 공시일
    from .broker_quarter import dart_actuals, prelim_dates
    qa, _, qfiled = dart_actuals([r for r in ff if (_filed_date(r.get('rcept_no')) or '9999') <= last])
    quarter_actuals = [{'fiscal_year': y, 'quarter': q, 'metric': m, 'value_mn': format(v, 'f'), 'filed_at': qfiled.get((y, q))} for (y, q, m), v in sorted(qa.items())]
    prelims, dm = [], None
    if 'disclosure' in man['tables']:
        drows, dm = read_rows(root, man, 'disclosure', company)
        prelims = [d for d in prelim_dates(drows) if d <= last]
    src = {'financials': _src(root, man, fm, 'core.financial_fact', 'DART 정기보고서 재무(공시 API) — Neon 공용 DB 경유')}
    if em:
        src['exposure'] = _src(root, man, em, 'core.report_exposure', '사업보고서 표에서 규칙으로 읽은 민감도 — Neon 공용 DB 경유')
    if dm:
        src['disclosure'] = _src(root, man, dm, 'core.disclosure', 'DART 공시 목록(잠정실적 공시일) — Neon 공용 DB 경유')
    c = cos.get(company, {})
    return {'company': company, 'name': c.get('name', company), 'market': c.get('market'), 'krx_sector': c.get('krx_sector'),
            'cutoff': cutoff, 'last_usable_date': last, 'facts': facts, 'exposures': exp, 'quarters': quarters, 'dart_quarters': dq, 'quarter_actuals': quarter_actuals, 'prelim_dates': prelims, 'excluded_after_cutoff': later, 'source': src,
            'notes': ['재무는 DART 공시 API 값(연결 우선, 없으면 별도)입니다. 원문 표 셀과 직접 대조한 값은 아닙니다(두 기준 기업은 원문 대조 68/68 일치 확인).',
                      '기준시점 이전에 접수된 사업보고서만 썼습니다(접수번호 날짜 기준).']}


# ---------------------------------------------------------------- T08 뉴스·사건 (공시 목록 = 공식, 뉴스 = 제목·링크·날짜만)
import re as _re

EVENT_RULES = [   # (분류, 보고서명에 들어 있으면) — 위에서부터 먼저 맞는 것
    ('earnings', '실적', ('영업실적', '매출액또는손익구조', '잠정')),
    ('periodic', '정기보고서', ('사업보고서', '반기보고서', '분기보고서', '감사보고서')),
    ('capital', '자본 조달·주식 수 변동', ('상장', '유상증자', '무상증자', '전환사채', '신주인수권부사채', '교환사채', '증권예탁증권', '주식소각', '감자')),
    ('buyback', '자기주식', ('자기주식', '자사주')),
    ('dividend', '배당', ('배당',)),
    ('holder', '지분 변동', ('대량보유', '최대주주등소유주식', '최대주주변경', '주식등의대량')),
    ('insider', '임원·주요주주 거래', ('임원ㆍ주요주주', '임원·주요주주')),
    ('deal', '계약·투자·인수합병', ('공급계약', '신규시설투자', '타법인주식', '유형자산취득', '영업양수', '영업양도', '합병', '분할', '출자')),
    ('rumor', '풍문·조회공시', ('풍문', '조회공시')),
    ('governance', '지배구조·주주총회', ('주주총회', '대표이사', '의결권', '지배구조', '기업가치제고', '지속가능', '임원')),
    ('ir', 'IR·경영계획', ('공정공시', '기업설명회', '장래사업', '경영계획')),
    ('risk', '손실·사고·소송', ('손실', '중대재해', '소송', '횡령', '배임', '부도', '정지')),
]
EVENT_LABEL = {k: lab for k, lab, _ in EVENT_RULES} | {'other': '기타'}
ROUTINE = {'insider', 'periodic'}   # 건수가 많고 반복되는 공시 — 사건 목록에서는 따로 센다


def classify_disclosure(report_nm):
    nm = _re.sub(r'\s+', '', report_nm or '')
    for key, _, words in EVENT_RULES:
        if any(w in nm for w in words):
            return key
    return 'other'


def _norm_title(t):
    t = _re.sub(r'\[[^\]]*\]|\([^)]*\)|<[^>]*>', ' ', t or '')
    return _re.sub(r'[^0-9A-Za-z가-힣]+', '', t).lower()[:60]


def news_events(company, cutoff, snapshot='', lookback_days=180):
    root = resolve(snapshot)
    man = load_manifest(root)
    cos = companies(root, man)
    if cos and company not in cos:
        raise SnapshotError('company_unknown', f'사본 기업 목록에 {company} 가 없습니다.')
    last = last_usable_date(cutoff)
    start = (_date.fromisoformat(last) - timedelta(days=int(lookback_days))).isoformat()
    dis, dm = read_rows(root, man, 'disclosure', company)
    disclosures, later = [], 0
    for r in sorted(dis, key=lambda r: (str(r['rcept_dt']), r['rcept_no'])):
        d = str(r['rcept_dt'])[:10]
        if d > last:
            later += 1
            continue
        if d < start:
            continue
        k = classify_disclosure(r.get('report_nm'))
        disclosures.append({'date': d, 'rcept_no': r['rcept_no'], 'title': r.get('report_nm'), 'filer': r.get('filer'), 'category': k,
                            'category_label': EVENT_LABEL[k], 'db_event_type': r.get('event_type'), 'url': r.get('url'), 'routine': k in ROUTINE})
    news, comments, dup, nm = [], 0, 0, None
    try:
        rows, nm = read_rows(root, man, 'news_title', company)
    except SnapshotError as e:
        if e.code != 'table_missing':
            raise
        rows = []
    seen = {}
    for r in sorted(rows, key=lambda r: (str(r.get('published_at')), r.get('doc_id') or 0)):
        d = str(r.get('published_at') or '')[:10]
        if not d or d > last or d < start:
            continue
        src = r.get('source') or ''
        if src == 'youtube_comment':
            comments += 1                       # 댓글은 개수만(내용은 쓰지 않음)
            continue
        if not src.startswith('naver_news'):
            continue
        key = _norm_title(r.get('title'))
        if key in seen:
            dup += 1
            seen[key]['dups'] += 1
            continue
        item = {'date': d, 'title': r.get('title'), 'url': r.get('url'), 'source': src, 'score': r.get('score'), 'label': r.get('label'),
                'method': r.get('method'), 'dups': 0}
        seen[key] = item
        news.append(item)
    def _opt(table):
        try:
            rs, m = read_rows(root, man, table, company)
            return [r for r in rs if start <= str(r.get('trade_date') or r.get('d') or '')[:10] <= last], m
        except SnapshotError as e:
            if e.code != 'table_missing':
                raise
            return [], None
    sent, sm = _opt('doc_daily_agg')
    ment, mm = _opt('mention_count')
    src = {'disclosure': _src(root, man, dm, 'core.disclosure', 'DART 공시 목록 — Neon 공용 DB 경유')}
    if nm:
        src['news'] = _src(root, man, nm, 'rag.document', '네이버 뉴스 제목·링크(포털 수집) — 본문 미사용')
    if sm:
        src['sentiment'] = _src(root, man, sm, 'core.doc_daily_agg', '사전 기반 감성 일별 합(규칙)')
    if mm:
        src['mentions'] = _src(root, man, mm, 'core.mention_count', '네이버 검색 결과 건수(포털)')
    c = cos.get(company, {})
    return {'company': company, 'name': c.get('name', company), 'cutoff': cutoff, 'last_usable_date': last, 'window': [start, last],
            'disclosures': disclosures, 'news': news, 'news_duplicates_removed': dup, 'comment_count': comments,
            'sentiment_daily': [{k: r.get(k) for k in ('d', 'source', 'n_docs', 'n_scored', 'score_sum')} for r in sent],
            'mentions': [{k: r.get(k) for k in ('trade_date', 'source', 'query', 'total')} for r in ment],
            'excluded_after_cutoff': later, 'source': src,
            'notes': ['공시는 접수일 기준이며, 접수 시각을 몰라 기준시점 이전 「확정된 날」까지만 씁니다.',
                      '뉴스는 제목·링크·날짜만 씁니다(본문 없음). 같은 제목은 하나로 합쳤습니다.',
                      '공시 분류는 보고서명 규칙으로 정했습니다(DB의 사건 분류가 대부분 비어 있음).',
                      '감성 점수는 사전 기반 규칙 값이며 사실 판단이 아닙니다.']}


def index_series(cutoff, snapshot='', symbol='^KS11'):
    root = resolve(snapshot)
    man = load_manifest(root)
    last = last_usable_date(cutoff)
    rows, m = read_table(root, man, 'market_index_daily')
    out = sorted(((r['trade_date'][:10], r['close']) for r in rows if r['symbol'] == symbol and r['trade_date'][:10] <= last), key=lambda x: x[0])
    return out, _src(root, man, m, 'core.market_index_daily', '야후 파이낸스 지수(비공식, 참고용)')


# ---------------------------------------------------------------- T12 지분·대주주 자료
def ownership_data(company, cutoff, snapshot=''):
    root = resolve(snapshot)
    man = load_manifest(root)
    cos = companies(root, man)
    if cos and company not in cos:
        raise SnapshotError('company_unknown', f'사본 기업 목록에 {company} 가 없습니다.')
    last = last_usable_date(cutoff)
    lh, lm = read_rows(root, man, 'largest_holder', company)
    holders = [{k: r.get(k) for k in ('fiscal_year', 'holder', 'relate', 'stock_kind', 'end_qty', 'stake_rt', 'begin_rt', 'settle_dt', 'rcept_no')} | {'filed_at': _filed_date(r.get('rcept_no'))}
               for r in lh if (_filed_date(r.get('rcept_no')) or '9999') <= last]
    ow, om = read_rows(root, man, 'ownership_report', company)
    reports = sorted(({k: r.get(k) for k in ('rcept_no', 'repror', 'rcept_dt', 'report_tp', 'report_resn', 'stkqy', 'stkrt', 'stkrt_irds', 'ctr_stkrt')}
                      for r in ow if str(r.get('rcept_dt'))[:10] <= last), key=lambda r: (str(r['rcept_dt']), r['rcept_no']))
    dis, dm = read_rows(root, man, 'disclosure', company)
    insider = sorted((str(r['rcept_dt'])[:10] for r in dis if classify_disclosure(r.get('report_nm')) == 'insider' and str(r['rcept_dt'])[:10] <= last))
    c = cos.get(company, {})
    return {'company': company, 'name': c.get('name', company), 'cutoff': cutoff, 'last_usable_date': last,
            'holders': holders, 'reports': reports, 'insider_dates': insider, 'shares_outstanding': c.get('shares_outstanding'),
            'source': {'holders': _src(root, man, lm, 'core.largest_holder', 'DART 최대주주 현황(공시 API) — Neon 공용 DB 경유'),
                       'reports': _src(root, man, om, 'core.ownership_report', 'DART 대량보유(5%) 보고(공시 API) — Neon 공용 DB 경유'),
                       'disclosure': _src(root, man, dm, 'core.disclosure', 'DART 공시 목록 — 임원·주요주주 보고 개수')},
            'notes': ['최대주주 현황은 사업보고서 기준일(연말) 값입니다. 그 뒤 변동은 대량보유 보고·임원 보고로만 보입니다.',
                      '기준시점 이전에 접수된 보고서만 썼습니다.']}
