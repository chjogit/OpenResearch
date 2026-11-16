"""v0.19: 기대 부채 지수(EDI) — 주가가 실적이 받치는 가치보다 미래를 몇 년치 당겨 썼는가 (KIRI 시간자본론 지표).

원칙 (tests/test_edi.py 로 고정)
- 그때 알 수 있던 것만: 날짜마다 분기 말 후 REPORT_LAG_DAYS(45일)가 지난 분기 재무만 쓴다.
- V(실적이 받치는 가치)는 가정 아래의 계산값이다. 적정주가·목표주가가 아니며, 그렇게 부르지 않는다.
- 한 가지 V로 단정하지 않는다: 정규화(최근 3년 평균 ROE)·최근 4분기 ROE·장부가 세 가지를 나란히 보인다.
- ROE가 장기성장률 이하이면 잔여이익 식의 V가 0 이하가 되어 EDI를 계산하지 않는다(보류). 0으로 채우지 않는다.

식
  잔여이익(RIM) 영구 성장형:  V = B × (ROE − g_lt) / (r − g_lt)
  기대 부채 지수:             EDI = ln(P / V) ÷ ln(1 + g)      (주가가 미리 당겨 쓴 「미래 성장의 햇수」)
  시장이 요구하는 ROE:         ROE* = g_lt + (r − g_lt) × P / B   (V = P 가 되게 하는 ROE)
"""
import math
from datetime import date, timedelta

LAG_DAYS = 45
STABLE_GAP = 0.02      # ROE − 장기성장 이 2%p 미만이면 V가 0에 가까워져 EDI가 과장된다 → 「불안정」, 최고·최저·상환 분해에서 뺀다
DEFAULTS = {'cost_of_equity': 9.0, 'long_growth': 2.0, 'edi_growth': 8.0}
METHODS = [('norm', '정규화 RIM (최근 3년 평균 ROE)'), ('ttm', '최근 4분기 ROE RIM'), ('book', '장부가 (순자산)')]
METHOD_LABEL = dict(METHODS)
NOTICE = ('기대 부채 지수(EDI)는 「주가 ÷ 실적이 받치는 가치(V)」를 햇수로 바꾼 계산값입니다. V는 자기자본비용·장기성장률 가정과 '
          'ROE 산정법에 따라 크게 달라지는 가정 아래의 값이며, 적정주가·목표주가·매매 판단이 아닙니다.')


def _f(x):
    try:
        return float(x) if x not in (None, '') else None
    except (TypeError, ValueError):
        return None


def quarter_table(quarters):
    """T11 quarters → [{end, equity, ni, op}] (분기 말 순)."""
    by = {}
    for r in quarters:
        by.setdefault(str(r['period_end'])[:10], {})[r['metric']] = _f(r.get('amount'))
    return [{'end': e, 'equity': v.get('equity'), 'ni': v.get('net_income'), 'op': v.get('operating_income')} for e, v in sorted(by.items())]


def _contiguous_tail(q):
    """분기 말이 60~120일 간격으로 이어진 마지막 구간."""
    out = [q[-1]]
    for a in reversed(q[:-1]):
        if 60 <= (date.fromisoformat(out[0]['end']) - date.fromisoformat(a['end'])).days <= 120:
            out.insert(0, a)
        else:
            break
    return out


def value(B, roe, r, g_lt):
    """RIM 영구 성장형 V(총액). ROE ≤ g_lt 이면 None (식의 적용 범위 밖)."""
    if roe is None or roe <= g_lt:
        return None
    return B * (roe - g_lt) / (r - g_lt)


def edi(P, V, g):
    if not P or not V or P <= 0 or V <= 0:
        return None
    return math.log(P / V) / math.log(1 + g)


def point(row, fu, shares, r, g_lt, g):
    """한 날짜의 세 가지 V(주당)와 EDI."""
    P = _f(row['close'])
    out = {'date': row['trade_date'], 'P': P, 'basis_q': fu['end']}
    for m in ('norm', 'ttm', 'book'):
        Vt = fu['B'] if m == 'book' else value(fu['B'], fu['roe_' + m], r, g_lt)
        V = Vt / shares if Vt else None
        out['V_' + m] = V
        out['EDI_' + m] = edi(P, V, g)
        if m != 'book':
            out['unstable_' + m] = V is not None and fu['roe_' + m] - g_lt < STABLE_GAP
    return out


def shares_at(row, extra):
    mc, c = _f(row.get('market_cap')), _f(row.get('close'))
    if not mc or not c:
        return None
    return mc / c + (extra or 0)




def required_roe(P, shares, B, r, g_lt):
    """V = P 가 되게 하는 ROE (시장이 지금 가격으로 요구하는 수익성)."""
    return g_lt + (r - g_lt) * P * shares / B


def repayment(pts, key='norm'):
    """창 안 EDI 최고점 → 마지막 날: ln(P/V) 감소분을 주가 하락분과 V 상승분으로 나눈다. 의미 있는 감소가 없으면 None."""
    ok = [p for p in pts if p.get('EDI_' + key) is not None and not p.get('unstable_' + key)]
    if len(ok) < 2:
        return None
    pk = max(ok, key=lambda p: p['EDI_' + key])
    now = ok[-1]
    if pk is now:
        return None
    dP = math.log(now['P'] / pk['P'])
    dV = math.log(now['V_' + key] / pk['V_' + key])
    tot = dP - dV
    if tot >= -1e-9 or (pk['EDI_' + key] - now['EDI_' + key]) < 1.0:
        return None
    return {'peak': pk, 'now': now, 'share_V': dV / -tot, 'share_P': -dP / -tot}


def monthly(pts):
    by = {}
    for p in pts:
        by[p['date'][:7]] = p
    return [by[k] for k in sorted(by)]


# ================================================================ v0.20 DART 분기(실제 접수일) · 이벤트 구간 · 국면 판정 (C)
RC_Q = {'11013': 1, '11012': 2, '11014': 3, '11011': 4}
Q_END = {1: '03-31', 2: '06-30', 3: '09-30', 4: '12-31'}
ACC = {'ifrs-full_Equity': 'equity', 'ifrs-full_ProfitLoss': 'ni', 'dart_OperatingIncomeLoss': 'op'}
STALE_DAYS = 185          # 쓴 분기 말에서 185일이 넘으면 재무가 오래됨 → 판정 보류. 3분기(9월 말) 재무는 사업보고서(결산 후 90일 기한)가 나오는 3월까지 최대 약 182일 정상적으로 쓰인다
SHARE_LEAD = 0.70         # 줄어든 몫의 70% 이상이 한쪽이면 그쪽 「주도」
MIN_YEARS = 1.0           # EDI 변화가 1년 미만이면 판정하지 않음(변화 작음)


def dart_quarters(ff_rows):
    """DART 정기보고서(분기·반기·사업보고서) 행 → 분기 표. 실제 접수일(접수번호 앞 8자리)을 공개일로 쓴다.
    연결(CFS)을 우선하되 한 분기 안에서는 자본·순이익을 같은 재무제표(연결 또는 별도)에서만 가져온다.
    4분기 흐름값 = 사업보고서 연간값 − 3분기 보고서 누적값. 날짜(접수일)는 정정 공시면 정정일이 된다(늦게 잡히는 쪽, 미래정보 없음)."""
    best = {}
    for r in ff_rows:
        k, q = ACC.get(r.get('account_id')), RC_Q.get(str(r.get('report_code')))
        if not k or not q or r.get('amount') in (None, ''):
            continue
        key = (int(r['fiscal_year']), q, r.get('fs_div'), k)
        rank = {'BS': 0, 'IS': 0, 'CIS': 1}.get(r.get('sj_div'), 2)
        if key not in best or rank < best[key][0]:
            best[key] = (rank, r)
    out = []
    for y, q in sorted({(k[0], k[1]) for k in best}):
        fs = next((f for f in ('CFS', 'OFS') if (y, q, f, 'equity') in best and (y, q, f, 'ni') in best), None)
        if not fs:
            continue
        def flow(k):
            x = best.get((y, q, fs, k))
            if not x:
                return None
            if q < 4:
                return _f(x[1]['amount'])
            p3 = best.get((y, 3, fs, k))
            ytd = _f(p3[1].get('amount_ytd')) if p3 else None
            a = _f(x[1]['amount'])
            return None if ytd is None or a is None else a - ytd
        rc = max(str(best[(y, q, fs, k)][1].get('rcept_no') or '') for k in ('equity', 'ni'))
        if len(rc) < 8 or not rc[:8].isdigit():
            continue
        out.append({'end': f'{y}-{Q_END[q]}', 'equity': _f(best[(y, q, fs, 'equity')][1]['amount']), 'ni': flow('ni'), 'op': flow('op'),
                    'filed': f'{rc[:4]}-{rc[4:6]}-{rc[6:8]}', 'fs': fs})
    return out


def _available(r, d):
    if r.get('filed'):
        return r['filed'] <= d
    return r['end'] <= (date.fromisoformat(d) - timedelta(days=LAG_DAYS)).isoformat()


def fundamentals_at(qt, d):
    """날짜 d에 공개됐다고 볼 수 있는 분기만으로 B·정규화 ROE·최근 4분기 ROE. 공개일 = DART 접수일(있으면), 없으면 분기 말 + 45일.
    이어진 4분기 미만이거나 최근 4분기 중 자본이 0 이하면 None."""
    q = [r for r in qt if _available(r, d) and r['equity'] is not None and r['ni'] is not None]
    if len(q) < 4:
        return None
    q = _contiguous_tail(q)
    if len(q) < 4:
        return None
    last, t4, w = q[-1], q[-4:], q[-12:]
    eq4 = [r['equity'] for r in t4]; eqw = [r['equity'] for r in q[-13:]]
    if min(eq4) <= 0:
        return None
    ops = [r['op'] for r in t4]
    return {'end': last['end'], 'B': last['equity'], 'roe_ttm': sum(r['ni'] for r in t4) / (sum(eq4) / 4),
            'roe_norm': (sum(r['ni'] for r in w) * 4 / len(w)) / (sum(eqw) / len(eqw)), 'n_norm': len(w),
            'ni_ttm': sum(r['ni'] for r in t4), 'op_ttm': sum(ops) if all(o is not None for o in ops) else None,
            'ni_w': sum(r['ni'] for r in w), 'op_w': sum(r['op'] for r in w) if all(r.get('op') is not None for r in w) else None,
            'available_from': last.get('filed') or (date.fromisoformat(last['end']) + timedelta(days=LAG_DAYS)).isoformat(),
            'fs': last.get('fs'), 'age': (date.fromisoformat(d) - date.fromisoformat(last['end'])).days}


NI_OP_DEFAULT = 0.76   # 순이익/영업이익 기본 가정: 법인세 약 24%, 영업외손익 0 (v0.22, 적자·자료 부족일 때만)


def ni_op_ratio(fu):
    """증권사 영업이익 전망 → 순이익 환산 비율과 근거. 최근 4분기 → 최근 최대 12분기 → 기본 가정 순서.
    둘 다 흑자일 때만 실제 비율을 쓴다(적자 구간 비율은 부호가 뒤집혀 뜻이 없음)."""
    if fu.get('op_ttm') and fu['op_ttm'] > 0 and fu['ni_ttm'] > 0:
        return fu['ni_ttm'] / fu['op_ttm'], '최근 4분기 순이익/영업이익'
    if fu.get('op_w') and fu['op_w'] > 0 and fu.get('ni_w', 0) > 0:
        return fu['ni_w'] / fu['op_w'], f"최근 {fu.get('n_norm', 12)}분기 순이익/영업이익(최근 4분기는 적자라 더 긴 기간 사용)"
    return NI_OP_DEFAULT, f'기본 가정 {NI_OP_DEFAULT:.2f}(법인세 약 24%·영업외손익 0 — 최근 실적으로 비율을 만들 수 없어 가정함)'


def series(rows, qt, r, g_lt, g, extra=0):
    """날짜별 세 가지 V·EDI. 재무 나이(age, 쓴 분기 말부터 일수)와 재무 지문(fkey, 바뀌면 실적 반영일)을 함께 담는다."""
    out = []
    for row in rows:
        fu = fundamentals_at(qt, row['trade_date'])
        sh = shares_at(row, extra)
        if fu and sh and _f(row.get('close')):
            p = point(row, fu, sh, r, g_lt, g)
            p['age'] = fu['age']; p['fkey'] = (fu['end'], round(fu['B']), round(fu['roe_norm'], 8))
            out.append(p)
    return out


# 국면: 앱(모두의리서치)에는 중립어, KIRI 콘텐츠에는 시간자본론 용어. 같은 코드에서 두 이름을 함께 낸다.
PHASES = {
    'price_ahead': ('가격이 실적보다 앞섬', '기대 차입'),
    'in_step':     ('실적과 함께 움직임', '실적 동반'),
    'earn_led':    ('실적 주도로 격차 축소', '건강한 상환'),
    'mixed':       ('실적·가격 함께 격차 축소', '혼합 상환'),
    'price_led':   ('가격 주도로 격차 축소', '강제 상환'),
    'both_down':   ('실적·가격 동반 하락', '실적 악화형'),
    'deeper':      ('실적 수준 아래로 더 내려감', '저평가 심화'),
    'small':       ('변화 작음 (1년 미만)', '변화 미미'),
    'split':       ('가정에 따라 갈림', '가정에 따라 갈림'),
    'held':        ('판정 보류', '판정 보류'),
    'open':        ('진행 중 (다음 실적 반영 전)', '진행 중'),
}


def classify(a, b, e0, g):
    """a = ln 주가 변화, b = ln V 변화, e0 = 구간 시작 EDI. 규칙은 docs/EXPERT_GUIDE.md 「국면 판정」과 같다."""
    if a < 0 and b < 0:
        return 'both_down', None
    dE = (a - b) / math.log(1 + g)
    if abs(dE) < MIN_YEARS:
        return ('in_step' if b > 0 else 'small'), None
    if dE > 0:
        return 'price_ahead', None
    sV, sP = b / (b - a), -a / (b - a)
    if e0 is not None and e0 <= 0:
        return 'deeper', sV
    if sV >= SHARE_LEAD:
        return 'earn_led', sV
    if sP >= SHARE_LEAD:
        return 'price_led', sV
    return 'mixed', sV


def driver(phase, sV=None):
    """두 가정의 결론이 같은지 볼 때 쓰는 「누가 움직였나」. 이름표가 달라도(예: 실적 주도 vs 저평가 심화) 실적이 줄였다면 같은 결론."""
    if phase == 'price_ahead':
        return 'up'
    if phase in ('earn_led', 'mixed', 'price_led', 'deeper'):
        if sV is None:
            return 'down'
        return 'V' if sV >= SHARE_LEAD else 'P' if 1 - sV >= SHARE_LEAD else 'mix'
    if phase == 'both_down':
        return 'both'
    return 'flat'


def windows(pts, g):
    """실적 반영(재무 지문이 바뀐 날) 사이 구간. 각 구간에는 V 변화가 정확히 한 번(끝에서) 들어간다.
    마지막 열린 구간은 V 변화가 아직 없으므로 판정하지 않고 「진행 중」."""
    starts = [i for i, p in enumerate(pts) if i == 0 or p['fkey'] != pts[i - 1]['fkey']]
    out = []
    for j, i0 in enumerate(starts):
        p0 = pts[i0]
        if j + 1 < len(starts):
            p1 = pts[starts[j + 1]]
        else:
            p1 = pts[-1]
        w = {'start': p0['date'], 'end': p1['date'], 'basis_from': p0['basis_q'], 'basis_to': p1['basis_q'],
             'P0': p0['P'], 'P1': p1['P'], 'EDI0': p0['EDI_norm'], 'EDI1': p1['EDI_norm']}
        if j + 1 >= len(starts):
            w.update(phase='open', share_V=None)
            out.append(w); continue
        res = {}
        for m in ('norm', 'ttm'):
            V0, V1 = p0['V_' + m], p1['V_' + m]
            if not V0 or not V1 or p0.get('unstable_' + m) or p1.get('unstable_' + m):
                res[m] = ('held', None); continue
            res[m] = classify(math.log(p1['P'] / p0['P']), math.log(V1 / V0), p0['EDI_' + m], g)
        if res['norm'][0] == 'held' or p0['age'] > STALE_DAYS or p1['age'] > STALE_DAYS:
            ph, sv = 'held', None
            w['why'] = '재무가 오래됨' if (p0['age'] > STALE_DAYS or p1['age'] > STALE_DAYS) else 'ROE가 장기성장률에 가까움·V 계산 불가'
        elif res['ttm'][0] != 'held' and driver(*res['ttm']) != driver(*res['norm']) and 'flat' not in (driver(*res['ttm']), driver(*res['norm'])):
            ph, sv = 'split', res['norm'][1]
            w['why'] = f"정규화 {PHASES[res['norm'][0]][0]} · 최근 4분기 {PHASES[res['ttm'][0]][0]}"
        else:
            ph, sv = res['norm']
        w.update(phase=ph, share_V=sv, phase_ttm=res['ttm'][0], dEDI=None if w['EDI0'] is None or w['EDI1'] is None else w['EDI1'] - w['EDI0'])
        out.append(w)
    return out
