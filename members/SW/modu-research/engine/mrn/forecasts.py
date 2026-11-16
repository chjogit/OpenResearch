"""v0.18: 증권사 실적 전망 추이·자체 집계(컨센서스 아님)와 「모두의 가정」 분포.

원칙 (tests/test_forecasts.py 로 고정)
- 사람이 승인한 전망만 쓴다. 기준 날짜 뒤에 나온 보고서는 쓰지 않는다.
- 날짜마다 「그날까지 나온 증권사별 최신 전망」만 모은다. STALE_DAYS(120일)보다 오래된 전망은 뺀다.
- 집계 이름은 「승인된 보고서 n건 집계」이며 컨센서스라고 부르지 않는다. n < MIN_REPORTS(3)이면 추이로 보지 말라고 표시한다.
- 목표주가는 다루지 않는다(전문가 모드 비교표에만 있음).
- 모두의 가정: 먼저 내 가정을 낸 사람만 분포를 본다 · 결론(매매·목표주가)은 받지 않고 실적 가정만 · 사람마다 최신 1건 ·
  CROWD_MIN(5)명 이상일 때만 중앙값·사분위만 공개(개인 값·최솟값·최댓값은 공개하지 않음).
"""
from datetime import date
from decimal import Decimal
from statistics import median, quantiles

STALE_DAYS = 120
MIN_REPORTS = 3
CROWD_MIN = 5
FLAT_PCT = Decimal('0.5')            # ±0.5% 안이면 「유지」
METRICS = {'revenue': '매출액', 'operatingProfit': '영업이익'}
NOTICE = ('증권사 외부 전망을 앱이 모아 계산한 집계입니다. 컨센서스(공식 시장 예상치)가 아니며, 사실이 아닙니다. '
          '승인된 보고서만 썼고, 보고서 수가 적으면 대표성이 없습니다.')


def _d(s):
    return date.fromisoformat(str(s)[:10])


def trend(forecasts, metric, fy, until=None):
    """forecasts: [{broker, report_date, metric, fiscal_year, value(백만원 문자열), id}] → 날짜별 집계."""
    rows = sorted((f for f in forecasts if f['metric'] == metric and int(f['fiscal_year']) == int(fy)
                   and (until is None or str(f['report_date'])[:10] <= str(until)[:10])),
                  key=lambda f: (str(f['report_date']), f['broker']))
    if not rows:
        return None
    per = {}
    for f in rows:
        per.setdefault(f['broker'], []).append({'date': str(f['report_date'])[:10], 'value': str(f['value']), 'id': f.get('id')})
    series = []
    for d in sorted({r['date'] for p in per.values() for r in p}):
        latest = {}
        for b, pts in per.items():
            ok = [p for p in pts if p['date'] <= d and (_d(d) - _d(p['date'])).days <= STALE_DAYS]
            if ok:
                latest[b] = ok[-1]
        vs = sorted(Decimal(p['value']) for p in latest.values())
        series.append({'date': d, 'n': len(vs), 'median': str(median(vs)), 'min': str(vs[0]), 'max': str(vs[-1]),
                       'brokers': sorted(latest), 'thin': len(vs) < MIN_REPORTS})
    rev = {'up': [], 'down': [], 'flat': []}
    for b, pts in per.items():
        for a, c in zip(pts, pts[1:]):
            va, vc = Decimal(a['value']), Decimal(c['value'])
            ch = (vc / va - 1) * 100 if va else Decimal(0)
            k = 'flat' if abs(ch) <= FLAT_PCT else ('up' if ch > 0 else 'down')
            rev[k].append({'broker': b, 'from': a['date'], 'to': c['date'], 'change_pct': f'{ch:.1f}'})
    first, last = series[0], series[-1]
    move = None
    if Decimal(first['median']):
        move = f"{(Decimal(last['median']) / Decimal(first['median']) - 1) * 100:.1f}"
    return {'metric': metric, 'metric_label': METRICS.get(metric, metric), 'fiscal_year': int(fy), 'series': series, 'per_broker': per,
            'latest': last, 'first': first, 'median_move_pct': move, 'revisions': rev, 'stale_days': STALE_DAYS, 'min_reports': MIN_REPORTS}


def as_of(tr, d):
    """그 날짜(포함) 직전의 집계 한 점."""
    pts = [s for s in (tr or {}).get('series', []) if s['date'] <= str(d)[:10]]
    return pts[-1] if pts else None


def versus_actual(tr, actual_mn, disclosed):
    """실제(공시)와 공시 전날까지의 집계 비교 — 사후 기록."""
    pt = as_of(tr, _prev(disclosed))
    if not pt or actual_mn in (None, ''):
        return None
    a, m = Decimal(str(actual_mn)), Decimal(pt['median'])
    return {'aggregate_date': pt['date'], 'n': pt['n'], 'median': pt['median'], 'actual': str(a), 'disclosed': str(disclosed)[:10],
            'gap_pct': f'{(a / m - 1) * 100:.1f}' if m else None,
            'inside_range': Decimal(pt['min']) <= a <= Decimal(pt['max'])}


def _prev(d):
    from datetime import timedelta
    return (_d(d) - timedelta(days=1)).isoformat()


def crowd_stats(values):
    """사람마다 최신 1건의 값 목록 → 공개 가능한 요약(5명 이상일 때만)."""
    vs = sorted(Decimal(str(v)) for v in values)
    if len(vs) < CROWD_MIN:
        return {'n': len(vs), 'shown': False, 'min_n': CROWD_MIN}
    q1, q2, q3 = quantiles(vs, n=4, method='inclusive')
    return {'n': len(vs), 'shown': True, 'min_n': CROWD_MIN, 'median': str(q2), 'q1': str(q1), 'q3': str(q3)}


def check_value(metric, value_mn, reference_mn=None):
    """말이 안 되는 값을 막는다(조작·오타). 참고값(최근 집계 중앙값)이 있으면 그 1/5~5배 안."""
    try:
        v = Decimal(str(value_mn))
    except Exception:
        return '숫자로 적어 주세요.'
    if metric not in METRICS:
        return '매출액·영업이익만 적을 수 있어요.'
    if metric == 'revenue' and v <= 0:
        return '매출액은 0보다 커야 해요.'
    if reference_mn not in (None, ''):
        r = abs(Decimal(str(reference_mn)))
        if r and not (abs(v) <= r * 5 and (metric != 'revenue' or v >= r / 5)):
            return '증권사 집계와 너무 멀어요(1/5~5배 밖). 단위(조 원)를 확인해 주세요.'
    return None
