"""v0.25: 공시 반응 사전 (감성-주가 프레임워크 T1) — 「이런 공시가 나오면 예전엔 주가가 어땠나?」

하는 일
- 사본(Neon 사본, 해시 재대조)의 모든 회사 공시를 보고서명 규칙으로 세부 유형(약 30종)에 나눈다.
- 공시마다 시장 모형 비정상수익률(AR = 종목 수익률 − (α + β × 코스피 수익률))을 더해
  첫 반응 CAR[0,+1] · 이어진 반응 CAR[+2,+5] · CAR[+2,+20]을 잰다.
- 유형마다 모아 평균·중앙값·오른 비율·날짜 묶음 t값을 내고, 정해진 규칙으로 기록 분류를 붙인다.
- 새 공시 제목 하나를 넣으면 같은 유형의 과거 기록을 바로 돌려준다(judge). AI 모델 호출 0회.

원칙 (tests/test_reaction.py 로 고정)
- 그때 알 수 있던 것만: 기준시점에 이미 확정된 거래일까지의 가격·공시만 쓰고, 창(window)이 끝나지 않은 사건은 그 창의 통계에서 뺀다.
- 판정이 아니라 기록: 「과거엔 대체로 올랐던 공시」처럼 과거 반응만 말한다. 매수·매도·목표주가·이번에도 오른다는 단정은 만들지 않는다.
- 접수 시각을 몰라(장중·장후) 접수일 또는 그 다음 거래일을 0일로 두고, 첫 반응은 0일과 +1일을 합쳐 잰다.
- 같은 날 같은 회사의 다른 주요 공시가 섞인 사건, 정정 공시, 자회사 공시는 분류 통계에서 빼거나 따로 센다.
- 표본이 MIN_EVENTS 건보다 적으면 보류. 「뚜렷」은 날짜 묶음 |t| ≥ T_STRONG + 앞·뒤 절반 같은 방향 + |평균| ≥ MIN_EFFECT 일 때만.
"""
import bisect
import math
import re
from datetime import date as _date, datetime, timezone

from .market import (SnapshotError, _src, companies, index_series, last_usable_date, load_manifest, read_rows, resolve)
from . import price_src as _PS   # v0.39.3 가격 출처(금융위 + KIS 보충, 연구용 스위치)

MIN_EVENTS = 20          # 이보다 적으면 보류
T_STRONG = 2.50          # 관계 기록(N15)과 같은 문턱 — 유형이 30개 남짓이라 여러 번 시험한 효과를 감안
T_LEAN = 2.00
MIN_EFFECT = 0.30        # %p — 이보다 작은 평균은 「뚜렷」이라 부르지 않는다
EST = (260, 21)          # β 추정 구간: 0일 기준 260~21거래일 전
EST_MIN = 120
BENCH = 'equal'         # 'equal' = 사본 국내 회사 동일 가중 평균(자기 제외) · 'kospi' = 코스피 지수
WINDOWS = {'first': (0, 1), 'drift5': (2, 5), 'drift20': (2, 20)}
WINDOW_LABEL = {'first': '첫 반응 (접수일~다음 거래일)', 'drift5': '이어진 반응 (2~5거래일)', 'drift20': '이어진 반응 (2~20거래일)'}

NOTICE = ('공시 반응 사전은 과거에 같은 종류의 공시가 나온 뒤 주가가 시장보다 어떻게 움직였는지를 모은 기록입니다. '
          '이번 공시의 결과를 말해 주지 않으며, 매수·매도 추천이나 주가 예측이 아닙니다. 같은 날 다른 소식·시장 변화가 섞여 있습니다.')

# (키, 쉬운 이름, 보고서명에 들어 있으면, 들어 있으면 제외) — 위에서부터 먼저 맞는 것. 정기·반복 공시는 routine=True
SUBTYPES = [
    ('earnings_prelim', '잠정 실적', ('영업(잠정)실적', '영업실적', '잠정실적'), ('전망',), False),
    ('earnings_change', '매출·손익 30%(대규모 15%) 이상 변동', ('매출액또는손익구조',), (), False),
    ('earnings_guidance', '실적 전망·경영계획', ('실적등에대한전망', '장래사업', '경영계획'), (), False),
    ('earnings_preview', '실적 발표 예고', ('결산실적공시예고',), (), True),
    ('supply_cancel', '공급계약 해지', ('공급계약해지',), (), False),
    ('supply_contract', '공급계약 체결', ('공급계약체결',), (), False),
    ('buyback_trust_end', '자사주 신탁계약 해지', ('신탁계약해지',), (), False),
    ('buyback', '자사주 취득', ('자기주식취득',), (), False),
    ('treasury_sale', '자사주 처분', ('자기주식처분',), (), False),
    ('retire', '주식 소각', ('주식소각',), (), False),
    ('dividend', '현금·현물 배당 결정', ('배당결정',), ('주주명부', '폐쇄'), False),
    ('bonus_issue', '무상증자', ('무상증자',), (), False),
    ('rights_issue', '유상증자', ('유상증자결정', '유상증자'), ('발행결과', '신주발행가액'), False),
    ('hybrid_bond', '신종자본증권·조건부자본증권 발행', ('조건부자본증권', '자본으로인정되는채무증권'), (), False),
    ('mezzanine', '전환사채·신주인수권부사채·교환사채 발행', ('전환사채권발행', '신주인수권부사채권발행', '교환사채권발행'), (), False),
    ('capital_reduction', '감자', ('감자결정',), (), False),
    ('equity_acq', '다른 회사 주식 취득(출자)', ('타법인주식및출자증권취득',), (), False),
    ('equity_disp', '다른 회사 주식 처분', ('타법인주식및출자증권처분',), (), False),
    ('capex', '신규 시설투자·유형자산 취득', ('신규시설투자', '유형자산취득'), (), False),
    ('asset_disp', '유형자산 처분', ('유형자산처분',), (), False),
    ('merger', '합병·분할·영업양수도·주식교환', ('합병', '분할결정', '영업양수', '영업양도', '주식교환'), (), False),
    ('guarantee', '채무보증·담보제공·금전대여', ('채무보증', '담보제공', '금전대여'), (), False),
    ('value_up', '기업가치 제고 계획', ('기업가치제고',), (), False),
    ('rumor_answer', '풍문·조회공시 답변', ('풍문또는보도에대한해명', '조회공시요구에대한답변'), (), False),
    ('rumor_inquiry', '조회공시 요구', ('조회공시요구',), (), False),
    ('lawsuit', '소송 제기·판결', ('소송',), (), False),
    ('accident', '중대재해·생산중단·영업정지', ('중대재해', '생산중단', '영업정지'), (), False),
    ('misconduct', '횡령·배임·불성실공시·회계 위반', ('횡령', '배임', '불성실공시', '회계처리기준위반', '벌금등의부과'), (), False),
    ('control_change', '최대주주 변경', ('최대주주변경',), (), False),
    ('ceo_change', '대표이사 변경', ('대표이사변경',), (), False),
    ('major_holding', '5% 대량보유 보고', ('대량보유',), (), True),
    ('ir', '기업설명회(IR)', ('기업설명회',), (), True),
    ('routine', '정기보고서·주주총회·임원 보고 등', ('사업보고서', '반기보고서', '분기보고서', '감사보고서', '임원ㆍ주요주주', '주주총회', '의결권대리',
                                             '주주명부', '지배구조', '지속가능', '최대주주등소유주식', '공정거래자율준수', '기준일설정'), (), True),
]
LABEL = {k: lab for k, lab, *_ in SUBTYPES} | {'other': '기타'}
ROUTINE = {k for k, *_, r in SUBTYPES if r}

VERDICT = {
    'up': ('과거엔 대체로 올랐던 공시', '호재형 (과거 반응 기준)'),
    'down': ('과거엔 대체로 내렸던 공시', '악재형 (과거 반응 기준)'),
    'lean_up': ('오른 쪽으로 약한 경향', '중립에 가까움 (약한 호재 쪽)'),
    'lean_down': ('내린 쪽으로 약한 경향', '중립에 가까움 (약한 악재 쪽)'),
    'flat': ('방향이 뚜렷하지 않았던 공시', '중립형 (과거 반응 기준)'),
    'held': ('기록이 아직 부족해요', '판단 보류'),
}


def normalize(report_nm):
    return re.sub(r'\s+', '', report_nm or '')


def classify(report_nm):
    """보고서명 → {key, label, correction, subsidiary, routine}. 괄호 안(주요사항보고서(자기주식취득결정))도 본다."""
    nm = normalize(report_nm)
    corr = bool(re.match(r'^\[(기재|첨부|발행조건)?정정\]', nm)) or nm.startswith('[정정')
    body = re.sub(r'^\[[^\]]*\]', '', nm)
    sub = '자회사의주요경영사항' in body or '종속회사의주요경영사항' in body
    key = 'other'
    for k, _, words, excl, _ in SUBTYPES:
        if any(w in body for w in words) and not any(x in body for x in excl):
            key = k
            break
    if re.match(r'^(8-K|10-Q|10-K|6-K|20-F)', body) or '해외증권거래소' in body:
        key = 'other'
    return {'key': key, 'label': LABEL[key], 'correction': corr, 'subsidiary': sub, 'routine': key in ROUTINE,
            'group': f'{key}:sub' if sub and key not in ROUTINE and key != 'other' else key}


def group_label(g):
    k, _, s = g.partition(':')
    return LABEL.get(k, k) + (' (자회사·종속회사 공시)' if s else '')


# ---------------------------------------------------------------- 계산 (순수 함수 — 시험에서 바로 부른다)
def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def returns(series):
    """[(날짜, 종가)] → (날짜 목록, {날짜: 전일 대비 수익률})."""
    s = [(d, _f(c)) for d, c in series if _f(c)]
    s.sort()
    dates = [d for d, _ in s]
    r = {s[i][0]: s[i][1] / s[i - 1][1] - 1 for i in range(1, len(s))}
    return dates, r


def beta(stock_r, mkt_r, days):
    """구간 날짜들로 OLS α·β. 표본이 EST_MIN 미만이면 (0, 1) = 시장 조정 모형."""
    xs = [(mkt_r[d], stock_r[d]) for d in days if d in stock_r and d in mkt_r]
    if len(xs) < EST_MIN:
        return 0.0, 1.0, len(xs)
    mx = sum(x for x, _ in xs) / len(xs)
    my = sum(y for _, y in xs) / len(xs)
    vx = sum((x - mx) ** 2 for x, _ in xs)
    if vx <= 0:
        return 0.0, 1.0, len(xs)
    b = sum((x - mx) * (y - my) for x, y in xs) / vx
    return my - b * mx, b, len(xs)


def event_car(dates, stock_r, mkt_r, rcept_dt, last):
    """한 공시의 CAR(%) — 0일 = 접수일 또는 그 다음 거래일. 창 끝이 last 를 넘으면 그 창은 None."""
    i = bisect.bisect_left(dates, rcept_dt)
    if i >= len(dates) or i == 0 or dates[i] > last:
        return None
    lo, hi = max(1, i - EST[0]), i - EST[1]
    a, b, n_est = beta(stock_r, mkt_r, dates[lo:hi]) if hi > lo else (0.0, 1.0, 0)
    out = {'t0': dates[i], 'alpha': a, 'beta': b, 'n_est': n_est, 'model': 'market_model' if n_est >= EST_MIN else 'market_adjusted'}
    for w, (s, e) in WINDOWS.items():
        j0, j1 = i + s, i + e
        if j1 >= len(dates) or dates[j1] > last:
            out[w] = None
            continue
        ar = []
        for j in range(j0, j1 + 1):
            d = dates[j]
            if d not in stock_r or d not in mkt_r:
                break
            ar.append(stock_r[d] - (a + b * mkt_r[d]))
        out[w] = sum(ar) * 100 if len(ar) == j1 - j0 + 1 else None
    return out


def _pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    f = math.floor(k)
    return xs[f] + (xs[min(f + 1, len(xs) - 1)] - xs[f]) * (k - f)


def summarize(events, w):
    """사건 목록의 창 w 요약. t값은 같은 날 사건을 먼저 평균한 뒤(날짜 묶음) 날짜 평균으로 구한다(실적 시즌 쏠림 보정)."""
    xs = [(e['t0'], e[w]) for e in events if e.get(w) is not None]
    n = len(xs)
    if not n:
        return {'n': 0}
    vals = [v for _, v in xs]
    by = {}
    for d, v in xs:
        by.setdefault(d, []).append(v)
    dm = [sum(v) / len(v) for _, v in sorted(by.items())]
    m = sum(dm) / len(dm)
    t = None
    if len(dm) >= 3:
        sd = math.sqrt(sum((x - m) ** 2 for x in dm) / (len(dm) - 1))
        t = m / (sd / math.sqrt(len(dm))) if sd > 0 else None
    half = len(dm) // 2
    h1 = sum(dm[:half]) / half if half else None
    h2 = sum(dm[half:]) / (len(dm) - half) if len(dm) - half else None
    return {'n': n, 'n_dates': len(dm), 'mean': m, 'median': _pct(vals, 0.5), 'p25': _pct(vals, 0.25), 'p75': _pct(vals, 0.75),
            'up_share': sum(1 for v in vals if v > 0) / n, 't': t, 'first_half': h1, 'second_half': h2}


def verdict(s):
    """요약 → 기록 분류(판정 아님). 규칙은 모듈 머리말과 같다."""
    if not s or s.get('n', 0) < MIN_EVENTS or s.get('t') is None:
        return 'held'
    t, m = s['t'], s['mean']
    same = s['first_half'] is not None and s['second_half'] is not None and (s['first_half'] > 0) == (s['second_half'] > 0) == (m > 0)
    if abs(t) >= T_STRONG and same and abs(m) >= MIN_EFFECT:
        return 'up' if m > 0 else 'down'
    if abs(t) >= T_LEAN:
        return 'lean_up' if m > 0 else 'lean_down'
    return 'flat'


def describe(group, s, v):
    """쉬운 한 줄 — 결론이 아니라 정리."""
    if v == 'held':
        return f"{group_label(group)}: 비교할 과거 공시가 {s.get('n', 0)}건뿐이라 아직 모아 보는 중이에요 (최소 {MIN_EVENTS}건)."
    return (f"{group_label(group)} 공시 {s['n']}건 뒤 이틀 동안 주가는 시장보다 평균 {s['mean']:+.2f}% 움직였고, "
            f"{round(s['up_share'] * 100)}%가 시장보다 올랐어요 → {VERDICT[v][0]}.")


# ---------------------------------------------------------------- 사본에서 사전 만들기
_CACHE = {}


def _clean_events(rows):
    """회사 공시 목록 → 사건 후보. 같은 날 같은 묶음은 하나로, 같은 날 다른 주요 공시가 있으면 mixed."""
    by = {}
    for r in rows:
        c = classify(r.get('report_nm'))
        if c['correction'] or c['key'] == 'other':
            continue
        d = str(r.get('rcept_dt'))[:10]
        by.setdefault((d, c['group']), (r, c))
    days = {}
    for (d, g), (r, c) in by.items():
        if not c['routine']:
            days.setdefault(d, set()).add(g)
    out = []
    for (d, g), (r, c) in sorted(by.items()):
        out.append({'date': d, 'group': g, 'key': c['key'], 'routine': c['routine'], 'title': r.get('report_nm'), 'rcept_no': r.get('rcept_no'),
                    'mixed': len(days.get(d, ())) > 1 and not c['routine']})
    return out


_EW = {}


def equal_weight_ex(cutoff='', snapshot='', exclude=''):
    """v0.28.2 (N12): 사본 국내 회사 동일 가중 일별 수익률(자기 제외). 20곳 미만이면 SnapshotError."""
    cutoff = cutoff or datetime.now(timezone.utc).isoformat()
    root = resolve(snapshot)
    man = load_manifest(root)
    last = last_usable_date(cutoff)
    key = (man['_manifest_sha256'], last)
    if key not in _EW:
        cos = companies(root, man)
        parts = (man['tables'].get('price_daily') or {}).get('parts') or {}
        rets = {}
        for t in sorted(parts):
            c = cos.get(t, {})
            if c and c.get('market') not in (None, 'KR'):
                continue
            try:
                px, _ = read_rows(root, man, 'price_daily', t)
            except SnapshotError:
                continue
            px = [(r['trade_date'][:10], r['close']) for r in px if _PS.ok(r.get('source')) and r['trade_date'][:10] <= last]
            if len(px) >= 30:
                rets[t] = returns(px)[1]
        tot, cnt = {}, {}
        for r in rets.values():
            for d, v in r.items():
                tot[d] = tot.get(d, 0.0) + v
                cnt[d] = cnt.get(d, 0) + 1
        _EW[key] = (rets, tot, cnt)
    rets, tot, cnt = _EW[key]
    me = rets.get(exclude, {})
    out = {d: (tot[d] - me.get(d, 0.0)) / (cnt[d] - (1 if d in me else 0)) for d in tot if cnt[d] - (1 if d in me else 0) >= 20}
    if not out:
        raise SnapshotError('few_companies', '비교 기준(국내 회사 평균)을 만들 회사가 20개보다 적습니다.')
    n = len(rets) - (1 if exclude in rets else 0)
    return out, f'국내 회사 {n}곳 동일 가중 평균(자기 제외)'


def build(cutoff='', snapshot='', bench=None):
    """모든 회사 공시 → 반응 사전. manifest 해시 + 기준 거래일 + 비교 기준으로 캐시한다."""
    cutoff = cutoff or datetime.now(timezone.utc).isoformat()
    bench = bench or BENCH
    root = resolve(snapshot)
    man = load_manifest(root)
    last = last_usable_date(cutoff)
    key = (man['_manifest_sha256'], last, bench)
    if key in _CACHE:
        return _CACHE[key]
    cos = companies(root, man)
    idx, isrc = index_series(cutoff, snapshot, '^KS11')
    parts = (man['tables'].get('disclosure') or {}).get('parts') or {}
    if not parts:
        raise SnapshotError('table_missing', '사본에 기업별 공시 목록(disclosure)이 없습니다.')
    # 1) 가격 먼저 — 비교 기준(보통 종목 = 사본 국내 회사 동일 가중 평균, 자기 자신 제외)을 만들기 위해
    rets, dsha, psha, no_price = {}, {}, {}, 0
    for t in sorted(parts):
        c = cos.get(t, {})
        if c and c.get('market') not in (None, 'KR'):
            continue
        px, pm = read_rows(root, man, 'price_daily', t)
        px = [(r['trade_date'][:10], r['close']) for r in px if _PS.ok(r.get('source')) and r['trade_date'][:10] <= last]
        if len(px) < 30:
            no_price += 1
            continue
        rets[t] = returns(px)
        psha[t] = pm['sha256']
    if bench != 'kospi' and len(rets) < 20:
        raise SnapshotError('few_companies', '비교 기준(보통 종목 평균)을 만들 회사가 20개보다 적습니다.')
    tot, cnt = {}, {}
    for _, (_, r) in rets.items():
        for d, v in r.items():
            tot[d] = tot.get(d, 0.0) + v
            cnt[d] = cnt.get(d, 0) + 1
    kdates, kret = returns(idx)
    events, per_co, n_rows, later = [], {}, 0, 0
    for t, (dates, sret) in rets.items():
        c = cos.get(t, {})
        rows, dm = read_rows(root, man, 'disclosure', t)
        n_rows += len(rows)
        later += sum(1 for r in rows if str(r.get('rcept_dt'))[:10] > last)
        rows = [r for r in rows if str(r.get('rcept_dt'))[:10] <= last]
        if not rows:
            continue
        dsha[t] = dm['sha256']
        if bench == 'kospi':
            mret = kret
        else:
            mret = {d: (tot[d] - sret[d]) / (cnt[d] - 1) for d in sret if cnt.get(d, 0) >= 20}
        for ev in _clean_events(rows):
            car = event_car(dates, sret, mret, ev['date'], last)
            if car is None:
                continue
            e = ev | car | {'ticker': t, 'name': c.get('name', t)}
            events.append(e)
            per_co.setdefault(t, []).append(e)
    groups = {}
    for e in events:
        if not e['mixed']:
            groups.setdefault(e['group'], []).append(e)
    table = []
    for g, evs in groups.items():
        s = {w: summarize(evs, w) for w in WINDOWS}
        v = {w: verdict(s[w]) for w in WINDOWS}
        table.append({'group': g, 'label': group_label(g), 'routine': g in ROUTINE, 'stats': s, 'verdict': v['first'], 'verdict_drift20': v['drift20'],
                      'verdict_label': VERDICT[v['first']][0], 'plain': VERDICT[v['first']][1], 'line': describe(g, s['first'], v['first'])})
    table.sort(key=lambda r: (r['routine'], -(r['stats']['first'].get('n') or 0)))
    res = {'cutoff': cutoff, 'last_usable_date': last, 'snapshot': root.name, 'manifest_sha256': man['_manifest_sha256'],
           'n_disclosures': n_rows, 'n_events': len(events), 'n_mixed': sum(1 for e in events if e['mixed']), 'excluded_after_cutoff': later,
           'companies_without_price': no_price, 'n_companies': len(per_co), 'table': table, '_events': per_co,
           'rules': {'min_events': MIN_EVENTS, 't_strong': T_STRONG, 't_lean': T_LEAN, 'min_effect_pct': MIN_EFFECT, 'estimation': list(EST),
                     'windows': {w: list(x) for w, x in WINDOWS.items()},
                     'benchmark': 'kospi' if bench == 'kospi' else 'equal_weight_ex_self',
                     'benchmark_label': '코스피 지수' if bench == 'kospi' else f'사본 국내 회사 {len(rets)}곳 동일 가중 평균(자기 제외)'},
           'source': {'index': isrc, 'disclosure': {'table': 'core.disclosure', 'files': len(dsha), 'sha256_of_parts': _hash_map(dsha)},
                      'price': {'table': 'core.price_daily', 'files': len(psha), 'sha256_of_parts': _hash_map(psha)}},
           'notice': NOTICE,
           'notes': ['공시 접수 시각을 몰라 접수일(또는 다음 거래일)과 다음 거래일을 합쳐 첫 반응으로 잽니다.',
                     '같은 날 같은 회사에 다른 주요 공시가 있으면(섞인 사건) 분류 통계에서 뺐습니다.',
                     '정정 공시는 원래 공시 때 이미 반응했을 수 있어 뺐고, 자회사·종속회사 공시는 따로 셉니다.',
                     f'β는 0일 기준 {EST[0]}~{EST[1]}거래일 전 비교 기준(보통 종목 평균)과의 관계로 추정했고, {EST_MIN}일 미만이면 시장 조정(β=1)으로 대신했습니다.',
                     '「시장보다」의 시장은 사본에 있는 국내 회사들의 하루 수익률 평균(그 회사 자신은 뺌)입니다. 코스피 지수는 삼성전자·SK하이닉스 비중이 커서 보통 종목의 기준으로 쓰기 어렵습니다(지수 기준 결과는 전문가용 bench=kospi).',
                     '정기·반복 공시(정기보고서·임원 보고 등)는 대조군입니다. 대조군의 반응이 0에 가까워야 비교 기준이 치우치지 않은 것입니다.']}
    _CACHE.clear()
    _CACHE[key] = res
    return res


def _hash_map(m):
    import hashlib
    return hashlib.sha256('\n'.join(f'{k}:{v}' for k, v in sorted(m.items())).encode()).hexdigest()


def public(res):
    """API로 내보낼 사전 (사건 원자료 제외)."""
    return {k: v for k, v in res.items() if not k.startswith('_')}


def _row(res, group):
    return next((r for r in res['table'] if r['group'] == group), None)


def judge(title, company='', cutoff='', snapshot='', bench=None):
    """새 공시 제목 하나 → 같은 유형의 과거 기록. 이번 공시의 결과를 말하지 않는다."""
    res = build(cutoff, snapshot, bench)
    c = classify(title)
    row = _row(res, c['group'])
    out = {'title': title, 'classified': c, 'group': c['group'], 'group_label': group_label(c['group']), 'last_usable_date': res['last_usable_date'],
           'notice': NOTICE, 'model_calls': 0, 'stats': None, 'verdict_drift20': 'held'}
    cautions = []
    if c['correction']:
        cautions.append('정정 공시예요 — 원래 공시가 나왔을 때 이미 반응했을 수 있어요.')
    if c['routine']:
        cautions.append('정기·반복 공시예요 — 내용(숫자)에 따라 반응이 갈려 종류만으로는 말하기 어려워요.')
    if c['key'] in ('earnings_prelim', 'earnings_change', 'earnings_guidance'):
        cautions.append('실적 공시는 숫자가 좋았는지 나빴는지에 따라 반대로 움직여요. 제목만으로는 방향을 알 수 없어 「종류」의 평균만 보여 드려요.')
    if c['key'] in ('supply_contract', 'equity_acq', 'capex', 'rights_issue'):
        cautions.append('계약·투자·증자는 금액이 회사 규모에 비해 얼마나 큰지에 따라 반응이 크게 달라요(이번 사전은 금액을 아직 보지 않아요).')
    out['cautions'] = cautions
    if c['key'] == 'other':
        out.update(verdict='held', verdict_label='분류 규칙에 없는 공시예요', plain='판단 보류',
                   line='이 제목은 반응 사전의 공시 종류에 해당하지 않아요. 전문가 모드에서 제목 그대로 확인해 주세요.')
        return out
    if not row:
        out.update(verdict='held', verdict_label=VERDICT['held'][0], plain=VERDICT['held'][1],
                   line=f"{group_label(c['group'])}: 기준 날짜까지 비교할 과거 공시가 없어요.")
    else:
        out.update(verdict=row['verdict'], verdict_label=row['verdict_label'], plain=row['plain'], line=row['line'], stats=row['stats'],
                   verdict_drift20=row['verdict_drift20'])
    if company:
        mine = [e for e in res['_events'].get(company, []) if e['group'] == c['group']]
        out['company'] = company
        out['company_history'] = [{k: e.get(k) for k in ('date', 't0', 'title', 'rcept_no', 'first', 'drift5', 'drift20', 'mixed', 'model', 'beta')} for e in mine[-10:]]
    return out


def recent(company='', cutoff='', snapshot='', days=30, limit=60, bench=None):
    """최근 공시(한 회사 또는 전체)에 사전 기록을 붙이고, 지금까지의 실제 반응을 나란히 둔다."""
    res = build(cutoff, snapshot, bench)
    last = _date.fromisoformat(res['last_usable_date'])
    lim = _date.fromordinal(last.toordinal() - int(days)).isoformat()
    pool = res['_events'].get(company, []) if company else [e for es in res['_events'].values() for e in es]
    rows = []
    for e in sorted(pool, key=lambda e: (e['t0'], e['ticker']), reverse=True):
        if e['date'] < lim or e['routine']:
            continue
        row = _row(res, e['group'])
        rows.append({'ticker': e['ticker'], 'name': e['name'], 'date': e['date'], 't0': e['t0'], 'title': e['title'], 'rcept_no': e['rcept_no'],
                     'url': f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={e['rcept_no']}", 'group': e['group'], 'group_label': group_label(e['group']),
                     'mixed': e['mixed'], 'actual_first': e.get('first'), 'actual_drift5': e.get('drift5'),
                     'verdict': row['verdict'] if row else 'held', 'verdict_label': row['verdict_label'] if row else VERDICT['held'][0],
                     'plain': row['plain'] if row else VERDICT['held'][1], 'typical_first': row['stats']['first'].get('mean') if row else None})
        if len(rows) >= limit:
            break
    return {'company': company, 'last_usable_date': res['last_usable_date'], 'days': days, 'rows': rows, 'notice': NOTICE,
            'snapshot': res['snapshot'], 'manifest_sha256': res['manifest_sha256']}


def control(res):
    """대조군(정기·반복 공시)의 첫 반응 — 비교 기준이 치우쳤는지 보는 눈금."""
    row = _row(res, 'routine')
    return row['stats']['first'] if row else None


# ---------------------------------------------------------------- 쉬운 화면 카드 (엔진 근거 사슬이 아니라 이 모듈이 직접 답한다)
CARD = {'id': 'reaction', 'title': '이런 공시가 나오면 예전엔 어땠나?', 'sub': '공시 종류별 과거 주가 반응 기록 · 새 공시 제목을 넣으면 바로 비교 (판단 아님)',
        'group': 'market', 'kind': '관계', 'doors': ['ask', 'test'], 'next': ['events', 'price'], 'needs': ['disclosure', 'price_fsc'], 'view': 'reaction'}
