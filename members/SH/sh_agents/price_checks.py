"""Price sanity checks: OHLC logic, daily price limit, trading calendar and corporate actions.

Rows are never modified, filled or dropped. Findings only decide pass/partial/hold for the quality gate.
A passed check means "no rule violation found", not that the provider's prices are verified.
"""
import csv
import itertools
import math
from datetime import date
from pathlib import Path

# KRX 유가·코스닥 일일 가격제한폭(2015-06-15 이후 기준가 대비 ±30%). 다른 시장은 규칙을 등록한 뒤 사용합니다.
DAILY_LIMITS = {'KR': 0.30}
LIMIT_TOLERANCE = 0.005  # 호가단위 반올림 여유
ACTION_TYPES = {'split', 'reverse_split', 'bonus_issue', 'rights_issue', 'dividend', 'merger',
                'spin_off', 'capital_reduction', 'listing', 'trading_halt', 'other'}
# 이 유형은 기준가가 바뀌어 전일 종가 대비 ±30%를 넘을 수 있습니다.
PRICE_BASE_ACTIONS = {'split', 'reverse_split', 'bonus_issue', 'rights_issue', 'merger', 'spin_off',
                      'capital_reduction', 'listing', 'trading_halt'}
SPLIT_LIKE = {'split', 'reverse_split', 'bonus_issue', 'capital_reduction'}


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _iso(value):
    return date.fromisoformat(str(value)[:10])


def ohlc_issues(prices):
    """Rows whose complete OHLC values contradict each other. Incomplete rows are counted elsewhere."""
    issues = []
    for p in prices:
        values = [p.get(k) for k in ['open', 'high', 'low', 'close']]
        if not all(_finite(v) for v in values):
            continue
        o, h, lo, c = values
        if min(values) <= 0:
            issues.append({'day': p.get('day'), 'issue': '0 이하 가격'})
        elif h < lo:
            issues.append({'day': p.get('day'), 'issue': '고가 < 저가'})
        elif h < max(o, c):
            issues.append({'day': p.get('day'), 'issue': '고가 < 시가/종가'})
        elif lo > min(o, c):
            issues.append({'day': p.get('day'), 'issue': '저가 > 시가/종가'})
    return issues


def large_moves(prices, limit):
    """Close-to-close changes beyond limit + tolerance. Uses consecutive observations as stored."""
    moves = []
    for prev, cur in itertools.pairwise(prices):
        a, b = prev.get('close'), cur.get('close')
        if _finite(a) and _finite(b) and a > 0:
            change = b / a - 1
            if abs(change) > limit + LIMIT_TOLERANCE:
                moves.append({'day': cur.get('day'), 'previousDay': prev.get('day'), 'change': change})
    return moves


def load_trading_calendar(path, market='KR'):
    """CSV with `date` (ISO) and optional `market`. Holidays must be absent, not marked closed."""
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    if not rows or 'date' not in rows[0]:
        raise ValueError('거래일 달력 CSV에는 date 열이 필요합니다.')
    days = sorted({_iso(r['date']) for r in rows if not r.get('market') or r['market'] == market})
    if not days:
        raise ValueError(f'{market} 시장 거래일이 없습니다.')
    return days


def load_corporate_actions(path):
    """CSV columns: ticker, date, type, source (ratio/notes optional). Unknown types are rejected."""
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    actions = []
    for n, r in enumerate(rows, start=2):
        if not r.get('ticker') or not r.get('date') or r.get('type') not in ACTION_TYPES:
            raise ValueError(f'기업행위 CSV {n}행: ticker·date·허용된 type이 필요합니다.')
        if not (r.get('source') or '').strip():
            raise ValueError(f'기업행위 CSV {n}행: 확인 출처(source)가 필요합니다.')
        actions.append({**r, 'date': _iso(r['date']).isoformat()})
    return actions


def check_prices(prices, *, market='KR', adjustment=None, trading_dates=None, corporate_actions=None,
                 ticker=None):
    """Return quality rows (rule, status pass/partial/hold, reason, observed) for ISO-dated prices.

    trading_dates=None means no calendar was provided; corporate_actions=None means not provided,
    while [] means the team confirmed that no action exists for the ticker and period.
    """
    out = []

    def add(rule, status, reason, observed=None):
        out.append({'rule': rule, 'status': status, 'reason': reason, 'observed': observed})

    bad = ohlc_issues(prices)
    add('ohlc_logic', 'hold' if bad else 'pass',
        'OHLC 논리 위반(고가≥시가·종가≥저가>0)' if bad else 'OHLC 논리 위반 없음(전체 필드 있는 행 기준)',
        bad[:10] or None)

    days = [_iso(p['day']) for p in prices]
    actions = None
    if corporate_actions is not None:
        actions = [a for a in corporate_actions if ticker is None or str(a.get('ticker')) == str(ticker)]
        if days:
            actions = [a for a in actions if days[0] <= _iso(a['date']) <= days[-1]]

    def explained_by(move):
        start, end = _iso(move['previousDay']), _iso(move['day'])
        return [a for a in actions or [] if start < _iso(a['date']) <= end and a['type'] in PRICE_BASE_ACTIONS]

    limit = DAILY_LIMITS.get(market)
    if limit is None:
        add('daily_limit', 'partial', f'{market} 시장 가격제한폭 규칙 미등록: 급변 검사 생략')
    else:
        moves = large_moves(prices, limit)
        unexplained, explained, suspicious = [], [], []
        for m in moves:
            found = explained_by(m)
            if not found:
                unexplained.append(m)
            elif adjustment == 'split_adjusted' and any(a['type'] in SPLIT_LIKE for a in found):
                suspicious.append(m)  # 수정주가라면 분할일 급변이 남아 있으면 안 됩니다.
            else:
                explained.append({**m, 'actions': [a['type'] for a in found]})
        if unexplained:
            add('daily_limit', 'hold', f'전일 대비 ±{limit:.0%} 초과 변동: 기업행위 자료로 설명되지 않음',
                unexplained[:10])
        if suspicious:
            add('adjustment_consistency', 'hold',
                '수정주가로 표시됐지만 분할·병합일 급변이 남아 있음: 조정 기준 확인 필요', suspicious[:10])
        if explained:
            add('daily_limit', 'partial', '가격제한폭 초과 변동이 기업행위일과 일치: 조정 기준 수동 확인',
                explained[:10])
        if not moves:
            add('daily_limit', 'pass', f'전일 대비 ±{limit:.0%} 초과 변동 없음', 0)

    if actions is None:
        add('corporate_actions', 'partial', '기업행위(분할·병합·권리락 등) 자료 미제공: 대조하지 않음')
    else:
        add('corporate_actions', 'pass', '제공된 기업행위 자료와 대조(자료 완전성은 제공자 책임)',
            [f"{a['date']} {a['type']}" for a in actions] or 0)

    if trading_dates is None:
        add('calendar', 'partial', '공식 거래일 달력 미제공: 누락 거래일 판정 안 함')
    elif days:
        calendar = sorted({_iso(d) for d in trading_dates})
        if not calendar or calendar[0] > days[0] or calendar[-1] < days[-1]:
            add('calendar', 'partial', '거래일 달력이 보유 시세 기간을 모두 포함하지 않음',
                f'{calendar[0] if calendar else None} ~ {calendar[-1] if calendar else None}')
        else:
            expected = {d for d in calendar if days[0] <= d <= days[-1]}
            observed = set(days)
            missing = sorted(str(d) for d in expected - observed)
            extra = sorted(str(d) for d in observed - expected)
            if missing or extra:
                add('calendar', 'hold', '거래일 달력 대비 누락 또는 달력 밖 날짜',
                    {'missing': missing[:20], 'missingCount': len(missing), 'extra': extra[:20]})
            else:
                add('calendar', 'pass', '보유 구간 안에서 달력 거래일과 일치', len(expected))
    return out
