"""v0.17 B: 관계 기록 조사 — 「함께 움직인 기록」을 재되, 인과로 말하지 않는다.

안전장치(시험으로 고정, tests/test_relations.py)
1. 최소 표본: 겹치는 달이 MIN_MONTHS(24) 미만이면 그 지표는 계산하지 않는다(보류).
2. 여러 시차를 시험한 만큼 엄격하게: 시차 0~3개월 중 가장 큰 값을 고르므로 95% 범위를 Bonferroni 보정(z≈2.50)으로 넓혀 판정한다.
3. 기간 나눔 재확인: 앞 절반·뒤 절반에서 방향이 같고 둘 다 |r| ≥ 0.15여야 「안정」.
4. 과거 맞히기 시험: 앞선 시차(미리 알 수 있었던 값)만, 앞 2/3로 방향을 정하고 뒤 1/3에서 맞힌 비율을
   「늘 많던 방향」 기준선과 비교한다. 기준선보다 10%p 이상 높아야 통과.
5. 결과 문구는 항상 「관계의 기록이며 인과가 아님」을 붙인다(NOTICE).
"""
import math

MIN_MONTHS = 24
MAX_LAG = 3
STABLE_R = 0.15
OOS_MARGIN = 0.10
OOS_MIN_TEST = 8
NOTICE = ('관계의 기록이지 인과가 아닙니다. 두 값이 같은 시기에 함께(또는 시차를 두고) 움직였다는 뜻일 뿐, '
          '하나가 다른 하나를 움직였다는 뜻도, 앞으로도 그렇다는 뜻도 아닙니다. 다른 요인이 둘 다 움직였을 수 있습니다.')

# 금리처럼 수준 차이(%p)로 보는 지표 — 나머지는 변화율(%)
LEVEL_DIFF = {'ECOS_KTB3Y', 'ECOS_KTB10Y', 'DGS10', 'ECOS_BASE_RATE', 'FEDFUNDS'}
INDEX_FACTORS = {'^KS11': '코스피 지수', '^KQ11': '코스닥 지수', '^SOX': '미국 필라델피아 반도체 지수', '^GSPC': '미국 S&P 500'}
DEFAULT_FACTORS = ['ECOS_USDKRW', '^KS11', '^SOX', 'ECOS_KTB3Y', 'DGS10', 'KCS_EXP_854232_USD', 'DCOILBRENTEU']
GRADE_LABEL = {
    'too_few': '표본 부족 — 계산하지 않음',
    'indistinct': '관계 없음과 구분되지 않음',
    'unstable': '기간마다 달라짐 — 안정된 기록 아님',
    'same_month': '같은 달에 함께 움직인 기록',
    'lead': '앞서 움직인 기록 (과거 맞히기 통과)',
    'lead_weak': '앞서 움직인 듯하나 과거 맞히기 실패',
}


def monthly_last(points):
    """[(YYYY-MM-DD, value)] → {YYYY-MM: 그 달 마지막 값}."""
    out = {}
    for d, v in sorted(points):
        if v is None:
            continue
        try:
            out[d[:7]] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def changes(levels, diff=False):
    """{YYYY-MM: 수준} → {YYYY-MM: 전월 대비 변화} (연속한 달만)."""
    ks = sorted(levels)
    out = {}
    for a, b in zip(ks, ks[1:]):
        if _next(a) != b:
            continue
        x, y = levels[a], levels[b]
        if diff:
            out[b] = y - x
        elif x:
            out[b] = y / x - 1
    return out


def _next(m):
    y, mo = int(m[:4]), int(m[5:7])
    return f'{y + (mo == 12):04d}-{mo % 12 + 1:02d}'


def _shift(m, k):
    y, mo = int(m[:4]), int(m[5:7]) - 1 + k
    return f'{y + mo // 12:04d}-{mo % 12 + 1:02d}'


def pearson(x, y):
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in x)); sy = math.sqrt(sum((b - my) ** 2 for b in y))
    if not sx or not sy:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)


def fisher_ci(r, n, z=1.96):
    if r is None or n < 4:
        return None
    r = max(min(r, 0.999999), -0.999999)
    f, se = math.atanh(r), 1 / math.sqrt(n - 3)
    return math.tanh(f - z * se), math.tanh(f + z * se)


def _z_bonf(tests):
    """양측 α=0.05를 tests개로 나눈 임계값 (정규 근사, 표 값)."""
    return {1: 1.96, 2: 2.24, 3: 2.39, 4: 2.50, 5: 2.58, 6: 2.64, 7: 2.69, 8: 2.73}.get(tests, 2.8)


def pairs(stock, factor, lag):
    """주가 t월 수익률 ↔ 지표 (t−lag)월 변화."""
    ms = sorted(m for m in stock if _shift(m, -lag) in factor)
    return ms, [factor[_shift(m, -lag)] for m in ms], [stock[m] for m in ms]


def oos_hit(xs, ys):
    """앞 2/3로 방향(기울기 부호)을 정하고, 뒤 1/3에서 주가 수익률 방향을 맞힌 비율 vs 기준선."""
    n = len(xs)
    cut = (2 * n) // 3
    tr_x, tr_y, te_x, te_y = xs[:cut], ys[:cut], xs[cut:], ys[cut:]
    if len(te_x) < OOS_MIN_TEST:
        return None
    r = pearson(tr_x, tr_y)
    if r is None:
        return None
    sgn = 1 if r > 0 else -1
    up_share = sum(1 for v in tr_y if v > 0) / len(tr_y)
    majority = 1 if up_share >= 0.5 else -1
    hit = sum(1 for a, b in zip(te_x, te_y) if (sgn * a > 0) == (b > 0)) / len(te_x)
    base = sum(1 for b in te_y if (b > 0) == (majority > 0)) / len(te_y)
    return {'train_months': cut, 'test_months': len(te_x), 'train_r': r, 'hit': hit, 'baseline': base,
            'passed': hit >= base + OOS_MARGIN}


def record(stock, factor, pub_lag=0, max_lag=MAX_LAG, min_months=MIN_MONTHS):
    """stock·factor: {YYYY-MM: 변화}. pub_lag: 그 달 값이 공개되기까지 걸리는 달 수(일별 0, 관세청 1, 그 밖 월별 2).
    반환: 시차별 상관과 판정. 판정은 「기록의 등급」이며 원인·방향 판단이 아니다."""
    lags = []
    for k in range(0, max_lag + 1):
        ms, xs, ys = pairs(stock, factor, k)
        r = pearson(xs, ys) if len(ms) >= min_months else None
        lags.append({'lag': k, 'n': len(ms), 'r': r, 'from': ms[0] if ms else None, 'to': ms[-1] if ms else None,
                     'known_before': k >= max(1, pub_lag)})
    usable = [l for l in lags if l['r'] is not None]
    if not usable:
        n0 = max((l['n'] for l in lags), default=0)
        return {'grade': 'too_few', 'grade_label': GRADE_LABEL['too_few'], 'lags': lags, 'n': n0, 'min_months': min_months}
    best = max(usable, key=lambda l: abs(l['r']))
    z = _z_bonf(len(usable))
    ci95 = fisher_ci(best['r'], best['n'])
    ciadj = fisher_ci(best['r'], best['n'], z)
    ms, xs, ys = pairs(stock, factor, best['lag'])
    h = len(xs) // 2
    r1, r2 = pearson(xs[:h], ys[:h]), pearson(xs[h:], ys[h:])
    stable = r1 is not None and r2 is not None and (r1 > 0) == (r2 > 0) and abs(r1) >= STABLE_R and abs(r2) >= STABLE_R
    oos = oos_hit(xs, ys) if best['known_before'] else None
    if ciadj[0] <= 0 <= ciadj[1]:
        g = 'indistinct'
    elif not stable:
        g = 'unstable'
    elif not best['known_before']:
        g = 'same_month'
    elif oos and oos['passed']:
        g = 'lead'
    else:
        g = 'lead_weak'
    return {'grade': g, 'grade_label': GRADE_LABEL[g], 'lags': lags, 'best_lag': best['lag'], 'r': best['r'], 'n': best['n'],
            'from': best['from'], 'to': best['to'], 'ci95': ci95, 'ci_adjusted': ciadj, 'z_adjusted': z, 'lags_tested': len(usable),
            'halves': {'first': r1, 'second': r2, 'stable': stable}, 'oos': oos, 'known_before': best['known_before'],
            'min_months': min_months}
