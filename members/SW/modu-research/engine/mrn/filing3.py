"""v0.38 T2-3 공시 1건을 숫자로 — 유상증자 결정(이어서 전환사채류). filing2.py 와 같은 원칙·같은 틀이며, 끝에서 filing2 의 종류 목록에 스스로 등록한다.

판단 기록(번호는 NOTES.md 와 같음)
- 결정 1: 이론 권리락 주가는 주주배정·일반공모에서만 계산한다(제3자배정은 권리락이 없음).
- 결정 2: 확정 발행가가 없으면 예정 발행가로 계산하고 「예정」임을 이름에 적는다. 확정되면(정정 공시) 다시 계산하고 예정 대비 변화를 보인다.
- J12: 발행가 산정 산식은 원문 글에서 읽는다(할인율 · 1차·2차 기산일 · 하한 60%). 글이 표준 꼴(1개월·1주일 가중산술평균과 기산일 종가의 평균과 기산일 종가 중 낮은 값)이 아니면 시나리오·확률을 내지 않고 보류한다.
- J13: 제3자배정의 「할인율 또는 할증율」 칸은 회사마다 부호를 다르게 적는다 → 발행가 ÷ 기준주가로 다시 계산해 크기를 견주고, 할인인지 할증인지는 다시 계산한 값으로 적는다.
"""
import re
from . import filing2 as F2
from .promise import tokens, _date, _find, _all, _one, _num

KINDS = ('rights_issue', 'convertible')
LABELS = {'rights_issue': '유상증자 결정', 'convertible': '전환사채·신주인수권부사채·교환사채 발행 결정'}
FUNDS = (('facility', '시설자금'), ('acquisition', '영업양수자금'), ('operating', '운영자금'), ('debt', '채무상환자금'), ('securities', '타법인증권취득자금'), ('other', '기타자금'))
_PCT = r'(\d+(?:\.\d+)?)'


def _fl(t):
    s = (t or '').replace(',', '').replace(' ', '').replace('%', '')
    return float(s) if re.fullmatch(r'-?\d+(\.\d+)?', s) else None


def _cls(seg, f=_num):
    """「보통주식 (…) | 값 | 기타주식 (…) | 값」 → (보통, 기타). 없으면 None."""
    a = b = None
    for j, t in enumerate(seg[:-1]):
        s = t.replace(' ', '')
        if s.startswith('보통주식') and a is None:
            a = f(seg[j + 1])
        elif (s.startswith('기타주식') or s.startswith('종류주식')) and b is None:
            b = f(seg[j + 1])
    return a, b


def _block(T, pat, stop, cap=30):
    i = (_all(T, pat) or [-1])[-1]
    if i < 0:
        return []
    out = []
    for t in T[i + 1:i + 1 + cap]:
        if re.match(stop, t.replace(' ', '')):
            break
        out.append(t)
    return out


def pricing_terms(T):
    """J12: 「기타 투자판단에 참고할 사항」의 발행가 산정방법 글에서 산식의 값만 읽는다. 표준 꼴인지도 함께 판단.
    원문은 날짜마다 칸이 끊기는 일이 많아(색을 입힌 정정 표시) 칸을 이어 붙인 한 줄에서 「예정 → 1차 → 2차 → 확정」 제목 사이를 잘라 읽는다."""
    i = (_all(T, r'^\d{1,2}\.기타투자판단에참고할사항$') or _all(T, r'^\d{1,2}\.기타투자판단') or [-1])[-1]
    S = ' '.join(T[i + 1:]) if i >= 0 else ' '.join(T)
    k = S.find('신주의 배정방법', S.find('확정') if '확정' in S else 0)
    heads = []
    for key, pat in (('plan', r'예정\s*발행가액\s*[:：]'), ('first', r'1차\s*발행가액\s*[:：]'), ('second', r'2차\s*발행가액\s*[:：]'), ('final', r'확정\s*발행가액\s*[:：]')):
        g = re.search(pat, S)
        if g:
            heads.append((g.start(), key))
    heads.sort()
    seg = {key: S[a:(heads[n + 1][0] if n + 1 < len(heads) else a + 900)] for n, (a, key) in enumerate(heads)}
    order_ok = [key for _, key in heads if key != 'plan'] == ['first', 'second', 'final']
    t0, t1, t2, t3 = seg.get('plan'), seg.get('first'), seg.get('second'), seg.get('final')

    def disc(t):
        u = (t or '').replace(' ', '')
        g = re.search(r'할인율은?' + _PCT + '%', u) or re.search(_PCT + r'%의할인율', u)
        return float(g.group(1)) if g else None

    def base_day(t):
        """「… 전 제3거래일」 뒤 25자 안에 처음 나오는 날짜(기산일). 글에 날짜가 없으면 None."""
        g = re.search(r'제\s*3\s*거래일', t or '')
        return _date(t[g.end():g.end() + 28]) if g else None

    def anchor(t):
        g = re.search(r'(기준일|청약일|청약개시일|청약 개시일)\s*\(([^)]{6,20})\)\s*전\s*제\s*3\s*거래일', t or '')
        return _date(g.group(2)) if g else None
    allt = S.replace(' ', '')
    std1 = bool(t1 and '1개월' in t1 and '1주일' in t1 and '낮은' in t1)
    std2 = bool(t2 and '1주일' in t2 and '낮은' in t2 and '1개월' not in t2.split('낮은')[0])
    div1 = bool(re.search(r'1차발행가액=\[?(1차)?기준주가[×xX\*]\(1-할인율\)\]?/\[?1\+\(?증자비율[×xX\*]할인율', allt))
    floor = 0.6 if t3 and (re.search(r'40%\s*할인율', t3) or re.search(r'의\s*60%', t3)) else None
    return {'disc0': disc(t0), 'disc1': disc(t1), 'disc2': disc(t2), 'day1': base_day(t1), 'day2': base_day(t2), 'anchor1': anchor(t1), 'anchor2': anchor(t2),
            'floor': floor, 'div1': div1,
            'standard': bool(order_ok and std1 and std2 and t3 and '낮은' in t3 and disc(t1) is not None and disc(t2) is not None and div1 and floor),
            'has': {'plan': bool(t0), 'first': bool(t1), 'second': bool(t2), 'final': bool(t3)}}


def parse_rights_issue(doc):
    """주요사항보고서(유상증자결정) 본문 표. 주주배정·일반공모 서식과 제3자배정 서식 둘 다."""
    T = tokens(doc)
    out = F2._correction_head(T)
    if out.get('correction_reason') and re.search(r'굵은|색으로|표시', out['correction_reason']):       # 「정정사항은 굵은 파란색으로 표시」 같은 안내 글은 사유가 아님
        out['correction_reason'] = None
    new, new_o = _cls(_block(T, r'^1\.신주의종류와수', r'^2\.', 6))
    pre, pre_o = _cls(_block(T, r'^3\.증자전발행주식총수', r'^4\.', 6))
    out.update(new=new, new_other=new_o, par=_one(T, r'^2\.1주당액면가액', _num), pre=pre, pre_other=pre_o,
               method=(_one(T, r'^5\.증자방식') or '').strip() or None)
    blk = _block(T, r'^4\.자금조달의목적', r'^5\.', 16)
    out['funds'] = {}
    for key, lab in FUNDS:
        j = next((n for n, t in enumerate(blk[:-1]) if t.replace(' ', '').startswith(lab)), None)
        out['funds'][key] = _num(blk[j + 1]) if j is not None else None
    blk = _block(T, r'^6\.신주발행가액', r'^7[\.\-]', 20)
    lab = [t.replace(' ', '') for t in blk]
    out.update(final=None, final_other=None, plan=None, plan_other=None, fix_date=None)
    if '확정발행가' in lab or '예정발행가' in lab:
        i, j = (lab.index('확정발행가') if '확정발행가' in lab else None), (lab.index('예정발행가') if '예정발행가' in lab else None)
        if i is not None:
            out['final'], out['final_other'] = _cls(blk[i + 1:(j if j is not None and j > i else len(blk))])
        if j is not None:
            seg = blk[j + 1:]
            out['plan'], out['plan_other'] = _cls(seg)
            k = next((n for n, t in enumerate(seg[:-1]) if t.replace(' ', '') == '확정예정일'), None)
            out['fix_date'] = _date(seg[k + 1]) if k is not None else None
    else:
        out['final'], out['final_other'] = _cls(blk)
    b, bo = _cls(_block(T, r'^7\.기준주가', r'^7-1', 6))
    out.update(base=b, base_other=bo, base_method=(_one(T, r'^7-1\.기준주가산정방법') or '').strip()[:300] or None, premium_text=(_one(T, r'^7-2\.기준주가에대한할인율') or '').strip() or None)
    out.update(record_date=_one(T, r'^8\.신주배정기준일', _date), alloc=_fl(_one(T, r'^9\.1주당신주배정주식수')), esop=_fl(_one(T, r'^10\.우리사주조합원우선배정비율')),
               pay_date=_one(T, r'^\d{1,2}\.납입일', _date), list_date=_one(T, r'^\d{1,2}\.신주의상장예정일', _date), decided=_one(T, r'^\d{1,2}\.이사회결의일', _date),
               transferable=(_one(T, r'^\d{1,2}\.신주인수권양도여부') or '').strip() or None)
    out['sub'] = [None, None]
    i = (_all(T, r'^11\.청약예정일') or [-1])[-1]
    if i >= 0:
        seg = T[i + 1:i + 14]
        j = next((n for n, t in enumerate(seg) if t.replace(' ', '') == '구주주'), None)
        if j is not None:
            s2 = seg[j + 1:j + 6]
            for n, t in enumerate(s2[:-1]):
                if t.replace(' ', '') == '시작일' and out['sub'][0] is None:
                    out['sub'][0] = _date(s2[n + 1])
                elif t.replace(' ', '') == '종료일' and out['sub'][1] is None:
                    out['sub'][1] = _date(s2[n + 1])
    m = (out['method'] or '').replace(' ', '')
    out['mode'] = 'third' if '3자' in m else 'holders' if '주주배정' in m else 'public' if '일반공모' in m else 'other' if m else None
    out['pricing'] = pricing_terms(T) if out['mode'] in ('holders', 'public') else None
    return out


def _price(p):
    """계산에 쓰는 발행가: (보통주 값, 기타주 값, 「확정」 또는 「예정」)."""
    if p.get('final') is not None or p.get('final_other') is not None:
        return p.get('final'), p.get('final_other'), '확정'
    if p.get('plan') is not None or p.get('plan_other') is not None:
        return p.get('plan'), p.get('plan_other'), '예정'
    return None, None, None


# ── 발행가 산식(J12·J14): 원문 산식을 시세로 다시 계산 · 주가 수준별 시나리오 표 · 시장 대비 확률(prob.py)
TICKS = ((2000, 1), (5000, 5), (20000, 10), (50000, 50), (200000, 100), (500000, 500))
LEVELS = (-30, -20, -10, 0, 10, 20, 30)
MARKETS = ((-0.10, '10% 내릴 때'), (0.0, '제자리일 때'), (0.10, '10% 오를 때'))


def tick_up(x):
    """호가 단위 미만 절상(유가증권·코스닥 공통 호가가격단위, 2023년 1월 이후)."""
    import math
    t = next((s for lim, s in TICKS if x < lim), 1000)
    return int(math.ceil(x / t - 1e-9) * t)


def _rows(prices):
    out = []
    for r in prices or []:
        try:
            c = float(r['close'])
        except (TypeError, ValueError, KeyError):
            continue
        v, a = r.get('volume'), r.get('trade_value')
        out.append((str(r['trade_date'])[:10], c, float(v) if v not in (None, '') else None, float(a) if a not in (None, '') else None))
    return sorted(out)


def _vwap(R, a, b):
    """a~b(달력 날짜, 양끝 포함)의 가중산술평균주가 = 거래대금 합 ÷ 거래량 합. 거래량·거래대금이 빠진 날이 있으면 None."""
    x = [r for r in R if a <= r[0] <= b]
    if not x or any(r[2] is None or r[3] is None for r in x) or sum(r[2] for r in x) <= 0:
        return None
    return sum(r[3] for r in x) / sum(r[2] for r in x)


def _back(day, months=0, days=0):
    import calendar
    from datetime import date, timedelta
    d = date.fromisoformat(day)
    if months:
        m, y = d.month - months, d.year
        while m < 1:
            m += 12; y -= 1
        return (date(y, m, min(d.day, calendar.monthrange(y, m)[1])) + timedelta(days=1)).isoformat()
    return (d - timedelta(days=days - 1)).isoformat()


def _trading_before(R, day, k):
    """day 앞 k번째 거래일. 시세가 있는 날까지는 실제 거래일, 그 뒤(미래)는 거래일 달력(주말 + 한국거래소 휴장일 표)으로 센다(T2-4c)."""
    from . import tradecal as C
    if R and day <= R[-1][0]:
        ds = [r[0] for r in R if r[0] < day]
        return ds[-k] if len(ds) >= k else None
    return C.shift(day, -k)


def base_first(R, day):
    """1차 기준주가 = min((1개월 가중산술평균 + 1주일 가중산술평균 + 기산일 종가) ÷ 3, 기산일 종가)."""
    c = next((r[1] for r in R if r[0] == day), None); m = _vwap(R, _back(day, months=1), day); w = _vwap(R, _back(day, days=7), day)
    return None if None in (c, m, w) else min((m + w + c) / 3, c)


def base_second(R, day):
    """2차 기준주가 = min((1주일 가중산술평균 + 기산일 종가) ÷ 2, 기산일 종가)."""
    c = next((r[1] for r in R if r[0] == day), None); w = _vwap(R, _back(day, days=7), day)
    return None if None in (c, w) else min((w + c) / 2, c)


def _outlook(f, p, px, H, fact, calc, held, T, notes):
    """확정 전(예정 발행가 단계)의 공시: 기준 날짜까지의 시세로 이미 정해진 단계는 다시 계산하고, 남은 단계는 시나리오 표와 시장 대비 확률로 보인다."""
    import math
    from . import filing as FL
    pr = p.get('pricing') or {}
    if not pr.get('standard'):
        held.append('확정 발행가 시나리오·확률: 원문의 발행가 산정방법 글을 표준 꼴(1차·2차 발행가 중 낮은 값, 하한 60%)로 읽지 못해 계산하지 않음 — 원문을 확인해 주세요'); return
    R = _rows(H.get('prices'))
    new, pre = p.get('new'), p.get('pre')
    if not R or not new or not pre:
        held.append('확정 발행가 시나리오·확률: 가격 자료(또는 보통주 수)가 없어 계산하지 않음'); return
    L, P0 = R[-1][0], R[-1][1]
    d1, d2, rr = pr['disc1'] / 100, pr['disc2'] / 100, new / pre
    day1 = pr.get('day1') or (_trading_before(R, p['record_date'], 3) if p.get('record_date') else None)
    day2 = pr.get('day2') or (_trading_before(R, p['sub'][0], 3) if (p.get('sub') or [None])[0] else None)
    # J14 → J22(T2-4c): 기산일이 원문 글에 없고 기준일이 아직 오지 않았으면 거래일 달력으로 센다. 휴장일 표가 있는 해면 그 날짜를 믿고,
    # 표가 없는 해(평일로 센 어림값)일 때만 예전처럼 「이미 정해졌다」고 단정하지 않는다
    from . import tradecal as C
    cal1 = not pr.get('day1') and bool(p.get('record_date')) and p['record_date'] > L
    cal2 = not pr.get('day2') and bool((p.get('sub') or [None])[0]) and p['sub'][0] > L
    est1 = cal1 and not C.covered(p['record_date'])
    est2 = cal2 and not C.covered(p['sub'][0])
    tag = lambda cal, est: '(휴장일 표가 없는 해라 평일로 센 어림값)' if est else '(원문에 날짜가 없어 거래일 달력으로 셈)' if cal else ''
    if not day1 or not day2 or day2 <= day1:
        held.append('확정 발행가 시나리오·확률: 신주배정기준일·구주주 청약일이 비어 있어 기산일을 정할 수 없음 — 계산하지 않음'); return
    won = H['won']
    fact('확정 발행가 산식(원문 글에서 읽은 값)', f"1차 = 1차 기준주가 × (1 − {pr['disc1']:g}%) ÷ (1 + 증자비율 × {pr['disc1']:g}%), 기산일 {day1}{tag(cal1, est1)} · 2차 = 2차 기준주가 × (1 − {pr['disc2']:g}%), 기산일 {day2}{tag(cal2, est2)} · 확정 = 둘 중 낮은 값(다만 청약일 전 3~5거래일 가중산술평균주가의 60%보다 낮으면 그 60%)")
    first = None; first_src = None
    prev_plan = next((h['parsed'].get('plan') for h in reversed(f.get('history') or []) if h['parsed'].get('plan')), None)
    from datetime import date as _d
    near = bool(p.get('record_date')) and 0 <= (_d.fromisoformat(p['record_date']) - _d.fromisoformat(f['rcept_dt'])).days <= 7
    stated = bool(px) and ((not est1 and f['rcept_dt'] > day1) or (est1 and near and prev_plan is not None and prev_plan != px))
    if est1 and stated:
        notes.append('신주배정기준일 직전에 예정 발행가 칸이 바뀐 공시라 이 값을 회사가 계산한 1차 발행가로 보았습니다(1차 기산일이 원문 글에 없어 날짜로는 확인하지 못함).')
    if est1 and not stated and day1 <= L:
        day1 = None                                                       # 어림한 기산일이 지났는지 알 수 없음 → 1차는 아직 모르는 것으로 두고 남은 단계로 계산
    if stated and est1:
        first, first_src = px, '공시'
    elif day1 and day1 <= L:
        b1 = base_first(R, day1)
        mine = tick_up(b1 * (1 - d1) / (1 + rr * d1)) if b1 else None
        if stated:                                                        # 기산일 뒤에 낸 공시의 예정 발행가 칸 = 회사가 계산한 1차 발행가
            first, first_src = px, '공시'
            if mine:
                gap = px - mine
                calc('1차 발행가를 시세로 다시 계산', f"{mine:,}원" + (' · 공시 값과 같음' if gap == 0 else f" · 공시 값 {px:,}원과 호가 한두 칸 차이({gap:+,}원)" if abs(gap) <= 2 * (tick_up(px + 0.1) - tick_up(px - 0.1) or 1) or abs(gap) / px < 0.003 else f" · 공시 값 {px:,}원과 {gap:+,}원 다름 — 원문을 직접 확인해 주세요"),
                     f'1차 기준주가({day1} 기산) × (1 − 할인율) ÷ (1 + 증자비율 × 할인율), 호가 단위 올림. 금융위 시세의 거래대금 ÷ 거래량으로 가중산술평균', mine, '원')
        elif mine:
            first, first_src = mine, '계산'
            calc('1차 발행가(시세로 계산 — 회사 공시 전)', f"{mine:,}원", f'1차 기준주가({day1} 기산) × (1 − 할인율) ÷ (1 + 증자비율 × 할인율), 호가 단위 올림. 회사가 공시하면 그 값이 우선', mine, '원')
        else:
            held.append(f'1차 발행가: {day1} 기산일의 시세(거래량·거래대금)가 사본에 없어 다시 계산하지 않음')
    if day2 <= L and first and not est2:
        b2 = base_second(R, day2); a5, a3 = _trading_before(R, day2, 2), day2
        fl = _vwap(R, a5, a3) if a5 else None
        if b2 and fl:
            second, floor = tick_up(b2 * (1 - d2)), tick_up(fl * 0.6); final = max(min(first, second), floor)
            calc('확정 발행가(시세로 계산 — 회사의 확정 공시 전)', f"{final:,}원 — 1차 {first:,}원 · 2차 {second:,}원 · 하한 {floor:,}원", '확정 = max(min(1차, 2차), 청약일 전 3~5거래일 가중산술평균주가 × 60%). 회사가 확정 공시를 내면 그 값이 우선', final, '원')
        else:
            held.append(f'확정 발행가: {day2} 기산일의 시세가 사본에 없어 계산하지 않음')
        return
    # 남은 단계 — ① 주가 수준별 시나리오 표(가정)
    ref, ref_lbl = (first, '1차 발행가') if first else (px, '예정 발행가')
    TR = []
    for lv in LEVELS:
        P = P0 * (1 + lv / 100)
        f1 = first or tick_up(P * (1 - d1) / (1 + rr * d1)); s2 = tick_up(P * (1 - d2)); fl = tick_up(P * 0.6); fin = max(min(f1, s2), fl)
        TR.append([f'{lv:+d}%' if lv else '지금 수준', f'{P:,.0f}원', f'{f1:,}원' + ('' if first else ''), f'{s2:,}원', f'{fl:,}원', f'{fin:,}원', f'{(fin / ref - 1) * 100:+.1f}%' if ref else '—'])
    T.append({'title': f"확정 발행가 시나리오 — 주가가 {L} 종가 {P0:,.0f}원 대비 이 수준에 머문 채 기산일을 맞는다면",
              'cols': ['주가 수준', '주가', '1차 발행가' + ('(정해짐)' if first else ''), '2차 발행가', '하한(60%)', '확정 발행가', f'{ref_lbl} 대비'], 'rows': TR,
              'hint': '가정으로 넣은 주가 수준마다 원문 산식을 그대로 적용한 값입니다(가중산술평균주가 대신 그 수준의 주가 하나로 계산). 어느 수준이 될지는 말하지 않습니다.'})
    # ② 시장 대비 확률(추정)
    from . import prob as PB
    h2 = max(1, C.count(_next(L), day2))
    h1 = min(h2, max(1, C.count(_next(L), day1))) if (day1 and day1 > L) else 1
    if h2 > PB.H_COARSE:
        held.append(f'확정 발행가 확률: 2차 기산일까지 {h2}거래일이 남아 너무 멀어요 — {PB.H_COARSE}거래일 안으로 들어오면 보입니다'); return
    try:
        S, key = PB.series_from_snapshot(H.get('snapshot') or '')        # 시세를 가져온 그 사본으로(확인서를 다시 계산해도 같은 값)
    except Exception:
        S, key = None, None
    tk = H.get('ticker')
    sg = PB.sigma(S, tk, L) if S and tk else None
    lib = PB.library(S, L, h2, key) if S else None
    if sg is None or lib is None:
        held.append('확정 발행가 확률: 이 회사의 직전 60거래일 시장 대비 변동성(또는 과거 경로)을 구하지 못해 계산하지 않음'); return
    import numpy as np
    hist = np.array([r[1] for r in R[-25:]], dtype=float)
    if len(hist) < 25:
        held.append('확정 발행가 확률: 직전 25거래일 시세가 모자라 계산하지 않음'); return
    PR = []
    for ms, lbl in MARKETS:
        cum = PB.paths(lib, sg, h2, math.log(1 + ms))
        full = np.concatenate([np.tile(hist, (cum.shape[0], 1)), P0 * np.exp(cum)], axis=1)
        i2 = 25 + h2 - 1
        if first:
            f1 = np.full(cum.shape[0], float(first))
        else:
            i1 = 25 + h1 - 1; c1 = full[:, i1]
            f1 = np.minimum((full[:, i1 - 20:i1 + 1].mean(1) + full[:, i1 - 4:i1 + 1].mean(1) + c1) / 3, c1) * (1 - d1) / (1 + rr * d1)
        c2 = full[:, i2]
        s2 = np.minimum((full[:, i2 - 4:i2 + 1].mean(1) + c2) / 2, c2) * (1 - d2)
        fin = np.maximum(np.minimum(f1, s2), full[:, i2 - 2:i2 + 1].mean(1) * 0.6)
        q10, q50, q90 = (tick_up(float(x)) for x in np.quantile(fin, [0.1, 0.5, 0.9]))
        pb = PB.share(fin, lambda v: v < ref) if ref else None
        shown = PB.shown(pb, h2)
        H['est'](f'확정 발행가 추정 — 시장 전체가 {lbl}', f"가운데 값 {q50:,}원 · 열에 여덟은 {q10:,}원~{q90:,}원" + (f" · {ref_lbl}({ref:,}원)보다 낮게 정해질 확률 {shown}" if shown else ''),
                 f"사본 회사들의 과거 경로 {lib['n']:,}개({lib['from']}~{lib['to']})를 이 회사의 직전 60거래일 시장 대비 변동성에 맞춰 다시 쓰고, 경로마다 원문 산식(1차·2차·하한 60%)을 적용. 가중산술평균주가는 종가 평균으로 대신함. 2차 기산일까지 {h2}거래일(한국거래소 휴장일 반영).{C.note(L, day2)} {PB.evidence(h2) or ''}", q50, '원')
        PR.append([f'시장 전체가 {lbl}', f'{q10:,}원', f'{q50:,}원', f'{q90:,}원', shown or '—'])
    T.append({'title': f'확정 발행가 추정 — 시장 시나리오별(추정, 2차 기산일 {day2}까지 {h2}거래일)', 'cols': ['시장 가정', '낮은 쪽(열에 하나)', '가운데 값', '높은 쪽(열에 하나)', f'{ref_lbl}보다 낮을 확률'], 'rows': PR,
              'hint': '시장 전체가 얼마나 오르내릴지는 맞히지 않고 가정으로 넣었습니다. 확률은 이 회사가 시장과 다르게 움직이는 부분에만 붙였고, 과거 검증 오차에 맞춰 거칠게만 보입니다. 증자 발표 뒤에는 주가가 평소보다 크게 움직이는 일이 많아 실제 범위는 더 넓을 수 있습니다.'})


def _next(day):
    from datetime import date, timedelta
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def _rights_issue(f, mkt, fact, calc, held, T, notes, H):
    from fractions import Fraction
    p = f['parsed']; won = H['won']; pc = H['p']
    n = lambda v, u='주': '—' if v is None else f'{v:,}{u}'
    new, new_o, pre, pre_o = p.get('new'), p.get('new_other'), p.get('pre'), p.get('pre_other')
    fact('증자 방식(원문 그대로)', p.get('method') or '—')
    if new is None and new_o is None:
        held.append('신주의 수: 원문 표에서 읽지 못함 — 보류'); return
    fact('새로 발행하는 주식 수', ' · '.join(([f'보통주 {new:,}주'] if new else []) + ([f'기타주 {new_o:,}주'] if new_o else [])), new or new_o, '주')
    if pre is None and pre_o is None:
        held.append('증자 전 발행주식 총수: 원문 표에서 읽지 못함 — 증자비율은 계산하지 않음')
    else:
        fact('증자 전 발행주식 총수', ' · '.join(([f'보통주 {pre:,}주'] if pre else []) + ([f'기타주 {pre_o:,}주'] if pre_o else [])), pre or pre_o, '주')
    nt, pt = (new or 0) + (new_o or 0), (pre or 0) + (pre_o or 0)
    if pt:
        r = round(nt / pt * 100, 4)
        calc('증자비율', pc(r), '새로 발행하는 주식 수 ÷ 증자 전 발행주식 총수 × 100 (보통주 + 기타주)', r, '%')
        calc('증자 후 발행주식 총수', f'{pt + nt:,}주', '증자 전 발행주식 총수 + 새로 발행하는 주식 수', pt + nt, '주')
        d = round(nt / (pt + nt) * 100, 4)
        calc('새 주식을 받지 않는 주주의 지분율이 줄어드는 정도', pc(d), '새로 발행하는 주식 수 ÷ 증자 후 발행주식 총수 × 100 (가진 지분율에서 이 비율만큼이 줄어듦)', d, '%')
    px, pxo, tag = _price(p)
    if tag is None:
        held.append('신주 발행가액: 확정·예정 값이 모두 비어 있어요 — 조달 금액과 주가 대비 계산은 하지 않음')
    else:
        fact(f'신주 발행가액({tag})', ' · '.join(([f'보통주 {px:,}원'] if px is not None else []) + ([f'기타주 {pxo:,}원'] if pxo is not None else [])), px if px is not None else pxo, '원')
        if tag == '예정':
            notes.append('발행가가 아직 확정되지 않아 예정 발행가로 계산했습니다' + (f"(확정 예정일 {p['fix_date']})" if p.get('fix_date') else '') + '. 확정되면 값이 달라집니다.')
        amt = (new or 0) * (px or 0) + (new_o or 0) * (pxo or 0)
        if amt:
            calc(f'조달 금액({tag} 발행가 기준)', won(amt), f'새로 발행하는 주식 수 × {tag} 발행가', amt, '원')
            fs = [v for v in (p.get('funds') or {}).values() if v]
            if fs:
                tot = sum(fs)
                parts = ' · '.join(f"{lab} {won(p['funds'][k])}" for k, lab in FUNDS if p['funds'].get(k))
                fact('자금조달의 목적(원문 표)', f'{parts} — 합계 {won(tot)}', tot, '원')
                gap = tot - amt
                calc('자금 목적 합계와 조달 금액의 대조', '같음' if gap == 0 else f"같음(작은 차이 {gap:+,}원)" if abs(gap) < max(px or 0, pxo or 0) or abs(gap) / amt < 0.0001
                     else f"합계가 조달 금액보다 {-gap:,}원 적음({gap / amt * 100:+.2f}%) — 발행 비용을 뺀 금액을 적는 회사가 있습니다. 원문 표를 확인해 주세요" if -0.03 * amt < gap < 0
                     else f"합계가 {gap:+,}원 다름({gap / amt * 100:+.2f}%) — 원문 표를 직접 확인해 주세요",
                     '자금조달의 목적 여섯 칸의 합계 − 새로 발행하는 주식 수 × 발행가', gap, '원')
            if mkt and mkt.get('market_cap'):
                r = H['pct'](amt, mkt['market_cap'])
                calc('조달 금액 ÷ 시가총액', f"{pc(r)} — {mkt['date']} 시가총액 {won(mkt['market_cap'])}(공시 전 마지막 거래일)", '조달 금액 ÷ 공시 전 마지막 거래일 시가총액 × 100', r, '%')
        close = mkt.get('close') if mkt else None
        if close and px:
            r = round((px / close - 1) * 100, 2)
            calc(f'{tag} 발행가 ÷ 종가', f"{pc(r)} — {mkt['date']} 종가 {close:,.0f}원(공시 전 마지막 거래일)", '(발행가 ÷ 종가 − 1) × 100. 음수면 종가보다 낮게 발행', r, '%')
            if p.get('mode') in ('holders', 'public') and pre and new:                    # 결정 1
                terp = float((Fraction(str(close)) * pre + px * new) / (pre + new))
                calc(f'이론 권리락 주가({tag} 발행가 기준)', f"{terp:,.0f}원 (종가 대비 {(terp / close - 1) * 100:+.2f}%)",
                     '(종가 × 증자 전 보통주 수 + 발행가 × 새 보통주 수) ÷ 증자 후 보통주 수. 새 주식이 싸게 나오는 만큼 1주 값이 낮아지는 산술 값이며 실제 주가는 다를 수 있음', round(terp, 2), '원')
        elif px and not close:
            held.append('발행가 ÷ 종가 · 이론 권리락 주가: 가격 자료가 없어 계산하지 않음')
    if p.get('mode') in ('holders', 'public'):
        if p.get('alloc') is not None:
            fact('1주당 신주배정주식수', f"{p['alloc']:g}주", p['alloc'], '주')
            got = int(Fraction(str(p['alloc'])) * 100)
            calc('100주를 가진 주주에게 배정되는 주식 수', f"{got:,}주" + (f" — 모두 청약하면 {won(got * px)}({tag} 발행가)" if px else ''), '100주 × 1주당 신주배정주식수 (1주 미만 버림)', got, '주')
        if p.get('esop') is not None:
            fact('우리사주조합 우선배정 비율', f"{p['esop']:g}%", p['esop'], '%')
        if p.get('transferable'):
            fact('신주인수권 양도 여부', p['transferable'])
        pr = p.get('pricing') or {}
        if pr.get('disc1') is not None:
            fact('발행가 산정에 쓰는 할인율(원문 글)', f"1차 {pr['disc1']:g}%" + (f" · 2차 {pr['disc2']:g}%" if pr.get('disc2') is not None else ''), pr['disc1'], '%')
        if tag == '예정' and p.get('mode') == 'holders':                                    # 결정 2: 확정 전이면 남은 단계를 시나리오·확률로
            _outlook(f, p, px, H, fact, calc, held, T, notes)
    elif p.get('mode') == 'third':
        b = p.get('base') if p.get('base') is not None else p.get('base_other'); x = px if p.get('base') is not None else pxo
        if b and x:
            fact('기준주가(원문 표)', f'{b:,}원', b, '원')
            if p.get('base_method'):
                fact('기준주가 산정방법(원문 그대로)', p['base_method'])
            r = round((x / b - 1) * 100, 3); st = _fl(p.get('premium_text'))
            chk = ''
            if st is not None:                                                             # J13
                chk = (f" · 공시 값 {p['premium_text']}%와 크기가 같음" if abs(abs(r) - abs(st)) <= 0.011 else f" · 공시 값 {p['premium_text']}%와 같음(호가 단위 올림 등으로 생기는 작은 차이 {abs(r) - abs(st):+.2f}%p)" if abs(abs(r) - abs(st)) <= 0.15 else f" · 공시 값 {p['premium_text']}%와 크기가 {abs(r) - abs(st):+.2f}%p 다름 — 원문을 직접 확인해 주세요")
            calc('기준주가 대비 발행가', f"{'할증' if r > 0 else '할인' if r < 0 else '같은 값'} {abs(r):.2f}%{chk}", '(발행가 ÷ 기준주가 − 1) × 100. 양수면 할증, 음수면 할인', r, '%')
        notes.append('제3자배정 증자입니다. 정해진 상대에게만 새 주식을 주므로 기존 주주에게 신주인수권이 없고 권리락도 없습니다.')
    for nm, key in (('신주배정기준일', 'record_date'), ('발행가 확정 예정일', 'fix_date'), ('납입일', 'pay_date'), ('신주 상장 예정일', 'list_date'), ('이사회 결의일', 'decided')):
        if p.get(key):
            fact(nm, p[key])
    if p.get('sub') and p['sub'][0]:
        fact('구주주 청약 예정일', f"{p['sub'][0]} ~ {p['sub'][1] or '미정'}")
    if tag == '확정' and px:                                                               # 결정 2: 예정 → 확정
        plan = p.get('plan') or next((h['parsed'].get('plan') for h in reversed(f.get('history') or []) if h['parsed'].get('plan')), None)
        if plan:
            r = round((px / plan - 1) * 100, 2)
            calc('예정 발행가 대비 확정 발행가', f"{plan:,}원 → {px:,}원 ({r:+.2f}%)", '(확정 발행가 ÷ 예정 발행가 − 1) × 100', r, '%')
    d8 = lambda v: v or '—'
    F2._generic_diff(f, calc, notes, H, [
        ('새 주식 수(보통주)', lambda x: x.get('new'), n), ('새 주식 수(기타주)', lambda x: x.get('new_other'), n),
        ('예정 발행가(보통주)', lambda x: x.get('plan'), lambda v: n(v, '원')), ('확정 발행가(보통주)', lambda x: x.get('final'), lambda v: n(v, '원')),
        ('확정 발행가(기타주)', lambda x: x.get('final_other'), lambda v: n(v, '원')),
        ('자금 목적 합계', lambda x: sum(v for v in (x.get('funds') or {}).values() if v) or None, lambda v: n(v, '원')),
        ('증자 방식', lambda x: x.get('method'), d8), ('1주당 신주배정주식수', lambda x: x.get('alloc'), lambda v: '—' if v is None else f'{v:g}주'),
        ('신주배정기준일', lambda x: x.get('record_date'), d8), ('발행가 확정 예정일', lambda x: x.get('fix_date'), d8),
        ('구주주 청약 시작일', lambda x: (x.get('sub') or [None])[0], d8), ('납입일', lambda x: x.get('pay_date'), d8), ('신주 상장 예정일', lambda x: x.get('list_date'), d8)])


# ── 전환사채·신주인수권부사채·교환사채(v0.38 T2-3, 결정 3)
CV_WORD = {'CB': ('전환', '전환가액', '전환청구기간'), 'BW': ('행사', '행사가액', '권리행사기간'), 'EB': ('교환', '교환가액', '교환청구기간')}   # (하면 쓰는 말, 가액 이름, 기간 이름)
CV_NAME = {'CB': '전환사채', 'BW': '신주인수권부사채', 'EB': '교환사채'}


def _bond_kind(report_nm, T):
    nm = (report_nm or '').replace(' ', '')
    if '교환사채' in nm:
        return 'EB'
    if '신주인수권부사채' in nm:
        return 'BW'
    if '전환사채' in nm:
        return 'CB'
    u = ''.join(T[:60]).replace(' ', '')                              # 엔진은 원문만 넘기므로 표지 제목·9번 항목 이름으로 가른다
    for key, word in (('EB', '교환사채권'), ('BW', '신주인수권부사채권'), ('CB', '전환사채권')):
        if word in u:
            return key
    a = ''.join(T).replace(' ', '')
    return 'EB' if '9.교환에관한사항' in a else 'BW' if '9.신주인수권에관한사항' in a else 'CB'


def _after(seg, label, f=None, start=0, join=False):
    """seg 안에서 공백을 뺀 글이 label 로 시작하는 첫 칸의 다음 칸.
    join=True: 숫자 칸이 색 입힌 정정 표시로 「1 | 4.18」처럼 끊긴 서식이면 이어 붙인다(J19)."""
    for n in range(start, len(seg) - 1):
        if seg[n].replace(' ', '').startswith(label):
            v = seg[n + 1]
            if join and re.fullmatch(r'[0-9]{1,3}', v.strip()) and n + 2 < len(seg) and re.fullmatch(r'[0-9][0-9,\.]*', seg[n + 2].strip()):
                v = v.strip() + seg[n + 2].strip()                       # 앞 조각이 콤마 없는 1~3자리일 때만(콤마 있는 완성된 숫자 뒤의 다른 칸 값과 붙이지 않게)
            return f(v) if f else v.strip()
    return None


def refix_terms(text):
    """J16: 「시가하락에 따른 조정」 글에서 조정 주기·시작·날짜 목록·상향 여부·시가 산식이 표준 꼴인지를 읽는다. 못 읽은 것은 None."""
    u = (text or '').replace(' ', '').replace('\n', '')
    out = {'months': None, 'days': 0, 'dates': [], 'start_years': None, 'start_months': None, 'up': False, 'standard_base': False, 'none': False}
    if re.search(r'시가하락에따른(조정|전환가액조정|행사가액조정|교환가액조정)[:：]?없음', u):
        out['none'] = True; return out
    g = None
    for m in re.finditer(r'매\s*\[?\s*([0-9]+)\s*\]?\s*개월([0-9]+일)?', u):
        tail = u[m.end():m.end() + 70]
        if re.search(r'조정일|경과한날|경과일|되는날|되는시점|경과한시점|마다', tail[:40]) and not re.search(r'이자|후급|이자지급', u[max(0, m.start() - 40):m.start()] + tail[:20]):
            g = m; break
    if g:
        out['months'] = int(g.group(1)); out['days'] = int(g.group(2)[:-1]) if g.group(2) else 0
        k = u.find('(', g.end(), g.end() + 30)
        if k >= 0:
            e = u.find(')', k)
            out['dates'] = sorted({d for d in (_date(x) for x in re.split(r'[,，]', u[k + 1:e])) if d})
        pre = u[max(0, g.start() - 50):g.start()]
        y = re.search(r'([0-9]+)년이(?:경과|되는)한?날(?:부터|이후)', pre); mo = re.search(r'([0-9]+)개월이(?:경과|되는)한?날(?:부터|이후)', pre)
        out['start_years'] = int(y.group(1)) if y else None; out['start_months'] = int(mo.group(1)) if mo else None
        seg = u[g.start():g.start() + 700]
        out['standard_base'] = '1개월' in seg and '1주일' in seg
    if not g:                                                          # 「(2019년 12월 02일, 2020년 03월 02일, …, 이하 "조정일")마다」처럼 날짜만 나열한 서식
        for m in re.finditer(r'\(([^()]{20,800}?)(?:,?이하|\))', u):
            ds = sorted({d for d in (_date(x) for x in re.split(r'[,，]', m.group(1))) if d})
            if len(ds) >= 3 and re.search(r'조정일', u[m.end():m.end() + 30] + m.group(1)[-30:]):
                out['dates'] = ds
                seg = u[m.start():m.start() + 900]; out['standard_base'] = '1개월' in seg and '1주일' in seg
                break
    out['up'] = bool(re.search(r'높은경우(에는)?(동|그)높은가액|상향조정(시|할수있|하되)|최초(전환|행사|교환)가(액|격)(이내|을한도)', u))
    return out


def parse_convertible(doc, report_nm=''):
    """주요사항보고서(전환사채권·신주인수권부사채권·교환사채권 발행결정) 본문 표."""
    T = tokens(doc)
    out = F2._correction_head(T)
    if out.get('correction_reason') and re.search(r'굵은|색으로|표시', out['correction_reason']):
        out['correction_reason'] = None
    k = _bond_kind(report_nm, T); w, pw, per = CV_WORD[k]
    out['bond'] = k
    s1 = _block(T, r'^1\.사채의종류', r'^2\.', 8)
    out['series'] = _after(s1, '회차'); out['bond_type'] = _after(s1, '종류')
    out['face'] = _one(T, r'^2\.사채의권면', _num)
    out['funds'] = {}
    blk = _block(T, r'^3\.자금조달의목적', r'^4\.', 16)
    for key, lab in FUNDS:
        j = next((n for n, t in enumerate(blk[:-1]) if t.replace(' ', '').startswith(lab.replace('증권취득', '증권취득'))), None)
        if j is None and key == 'securities':
            j = next((n for n, t in enumerate(blk[:-1]) if t.replace(' ', '').startswith('타법인증권')), None)
        out['funds'][key] = _num(blk[j + 1]) if j is not None else None
    s4 = _block(T, r'^4\.사채의이율', r'^5\.', 6)
    out['coupon'], out['ytm'] = _after(s4, '표면이자율', _fl), _after(s4, '만기이자율', _fl)
    out['maturity'] = _one(T, r'^5\.사채만기일', _date)
    out['offering'] = (_one(T, r'^8\.사채발행방법') or '').strip() or None
    s9 = _block(T, r'^9\.(전환|신주인수권|교환)에관한사항$', r'^(9-1|10)\.', 160)
    out['ratio_pct'] = _after(s9, '전환비율' if k == 'CB' else '행사비율' if k == 'BW' else '교환비율', _fl, join=True)
    out['price'] = _after(s9, pw + '(원', _num, join=True)
    out['price_method'] = (_after(s9, pw + '결정방법') or '')[:400] or None
    i = next((n for n, t in enumerate(s9) if t.replace(' ', '') in ('주식수',)), None)
    out['shares'] = _after(s9[i:], '주식수', _num, join=True) if i is not None else None
    out['share_kind'] = _after(s9, '종류')
    out['share_pct'] = _after(s9, '주식총수대비비율', _fl, join=True)
    j = next((n for n, t in enumerate(s9) if t.replace(' ', '') == per), None)
    out['period'] = [None, None]
    if j is not None:
        out['period'] = [_after(s9, '시작일', _date, j), _after(s9, '종료일', _date, j)]
    out['floor'] = _after(s9, '최저조정가액(원', _num, join=True)
    out['floor_basis'] = (_after(s9, '최저조정가액근거') or '').strip()
    fb = out['floor_basis'].replace(' ', '')
    g = re.search(r'100분의\|?([0-9]+)', fb) or re.search(r'([0-9]+)%', fb)
    if not g:                                                            # 「… 100분의 | 80 | 에 해당하는 가액」처럼 칸이 끊긴 서식
        n0 = next((n for n, t in enumerate(s9) if t.replace(' ', '').startswith('최저조정가액근거')), None)
        if n0 is not None:
            g = re.search(r'([0-9]{2,3})(?:%|에해당)', ''.join(s9[n0 + 1:n0 + 5]).replace(' ', ''))
    out['floor_pct_text'] = float(g.group(1)) if g else None
    k0 = next((n for n, t in enumerate(s9) if t.replace(' ', '').startswith(pw + '조정에관한사항')), None)
    k1 = next((n for n, t in enumerate(s9) if t.replace(' ', '').startswith('시가하락에따른')), None)
    adj = ' '.join(s9[k0 + 1:k1 if k1 else None]) if k0 is not None else ''
    out['refix'] = refix_terms(adj)
    if not out['refix']['months'] and not out['refix']['dates'] and not out['refix']['none'] and out['floor']:     # 조정 규칙을 「기타 투자판단에 참고할 사항」 등 다른 곳에 적은 서식
        i = (_all(T, r'^\d{1,2}\.기타투자판단') or [-1])[-1]
        alt = refix_terms(' '.join(T[i + 1:]) if i >= 0 else '')
        if alt['months'] or alt['dates']:
            alt['where'] = '기타 투자판단에 참고할 사항'; out['refix'] = alt
    if k == 'BW':
        out['separable'] = _after(s9, '사채와인수권의분리여부'); out['pay_in'] = _after(s9, '신주대금납입방법')
    if k == 'EB':
        st = (out['share_kind'] or '')
        out['eb_own'] = bool(re.search(r'자기주식|자사주', st))
    s91 = _block(T, r'^9-1\.옵션에관한사항', r'^10\.', 6)
    out['options'] = ' '.join(t.strip() for t in s91)[:900] or None
    out['call'] = bool(re.search(r'매도청구권|Call', out['options'] or '', re.I))
    out['call_pct'] = None
    if out['call']:
        g = re.search(r'(?:매도청구권|Call\s*Option)[^.]{0,400}?(?:권면|사채)\s*(?:총액|금액|원금)?의\s*([0-9]+(?:\.[0-9]+)?)\s*%', out['options'] or '', re.I)
        out['call_pct'] = float(g.group(1)) if g else None
    out.update(sub_date=_one(T, r'^\d{1,2}\.청약일', _date), pay_date=_one(T, r'^\d{1,2}\.납입일', _date), decided=_one(T, r'^\d{1,2}\.이사회결의일', _date))
    return out


def _months_after(day, months, days=0):
    import calendar
    from datetime import date, timedelta
    d = date.fromisoformat(day); m = d.month - 1 + months; y = d.year + m // 12; m = m % 12 + 1
    return (date(y, m, min(d.day, calendar.monthrange(y, m)[1])) + timedelta(days=days)).isoformat()


def refix_dates(p, until):
    """조정일 목록(오름차순, until 까지). 원문에 날짜가 나열돼 있으면 그것을, 아니면 발행일(납입일) + 매 N개월로 센다."""
    rf = p.get('refix') or {}
    if rf.get('dates'):
        return [d for d in rf['dates'] if d <= until]
    if not rf.get('months') or not p.get('pay_date'):
        return []
    first = 1
    if rf.get('start_years') or rf.get('start_months'):
        first = max(1, ((rf.get('start_years') or 0) * 12 + (rf.get('start_months') or 0)) // rf['months'])
    out, k = [], first
    while True:
        d = _months_after(p['pay_date'], k * rf['months'], k * (rf.get('days') or 0))
        if d > until or (p.get('maturity') and d >= p['maturity']):
            return out
        out.append(d); k += 1


def _refix_once(prev, base, floor, orig, up):
    """조정일 하루: 새 가액 = 시가산정액(base)과 지금 가액·최저 조정가액·최초 가액으로 정함. 원 단위 미만 올림."""
    import math
    new = max(floor, min(orig if up else prev, base))
    return int(math.ceil(new - 1e-9))


def _share_check(exp, stated):
    """J18: 공시 주식 수와 다시 계산한 값의 대조. 사채권자별로 1주 미만을 버리면 합계가 몇 주 적게 나온다(0.01% 안이면 같음으로 봄)."""
    if not stated:
        return ''
    if abs(exp - stated) <= 1:
        return ' · 공시 값과 같음'
    if stated < exp and exp - stated <= max(2, exp * 0.0001):
        return f' · 공시 값 {stated:,}주와 같음(사채권자별로 1주 미만을 버려 생기는 작은 차이 {stated - exp:+,}주)'
    return f' · 공시 값 {stated:,}주와 {stated - exp:+,}주 다름 — 원문을 직접 확인해 주세요'


def _convertible(f, mkt, fact, calc, held, T, notes, H):
    p = f['parsed']; won = H['won']; pc = H['p']; k = p['bond']; w, pw, per = CV_WORD[k]
    n = lambda v, u='주': '—' if v is None else f'{v:,}{u}'
    fact('사채 종류', f"{CV_NAME[k]}" + (f" · {p['bond_type']}" if p.get('bond_type') and p['bond_type'] != '-' else '') + (f" · {p['series']}회차" if p.get('series') and p['series'] != '-' else '') + (f" · {p['offering']}" if p.get('offering') else ''))
    if not p.get('face') and not p.get('price'):                                   # 철회 등으로 칸이 비어 있음(J5와 같음)
        held.append('사채 금액·가액 칸이 모두 비어 있어요(「-」) — 계산하지 않음. 발행 결정을 거둔 공시일 수 있으니 원문을 확인해 주세요')
        if p.get('correction_reason'):
            notes.append(f"회사가 적은 정정사유(원문 그대로): 「{p['correction_reason']}」")
        return
    face, price, shares = p.get('face'), p.get('price'), p.get('shares')
    fact('사채 권면 총액', won(face) if face else '—', face, '원')
    if price:
        fact(f'{pw}(원문 표)', f'{price:,}원', price, '원')
    if p.get('coupon') is not None or p.get('ytm') is not None:
        fact('이자율(원문 표)', f"표면 {'—' if p.get('coupon') is None else format(p['coupon'], 'g') + '%'} · 만기 {'—' if p.get('ytm') is None else format(p['ytm'], 'g') + '%'}")
    if p.get('maturity'):
        fact('사채 만기일', p['maturity'])
    if p.get('period') and p['period'][0]:
        fact(f'{per}', f"{p['period'][0]} ~ {p['period'][1] or '미정'}")
    fs = [v for v in (p.get('funds') or {}).values() if v]
    if fs and face:
        tot = sum(fs); gap = tot - face
        calc('자금 목적 합계와 사채 금액의 대조', '같음' if gap == 0 else f"합계가 {gap:+,}원 다름({gap / face * 100:+.2f}%) — 원문 표를 직접 확인해 주세요", '자금조달의 목적 여섯 칸의 합계 − 사채 권면 총액', gap, '원')
    if k == 'EB':                                                                   # 결정 3: 새 주식이 생기지 않음(J15: 자기주식이면 시장으로 나가는 주식 수)
        fact('교환 대상 주식(원문 그대로)', p.get('share_kind') or '—')
        if shares:
            fact('교환 대상 주식 수', f'{shares:,}주', shares, '주')
        if p.get('eb_own') and shares:
            base = mkt.get('shares') if mkt else None
            calc('시장으로 나갈 수 있는 자기주식', f"{shares:,}주" + (f" — 상장 주식 수의 {pc(round(shares / base * 100, 4))}" if base else ''), '교환 대상 자기주식 수 (÷ 공시 전 마지막 거래일 상장 주식 수 × 100)', shares, '주')
            notes.append('회사가 가진 자기주식과 바꿔 주는 교환사채입니다. 새 주식이 생기지 않아 발행주식 수는 그대로이지만, 교환되면 자기주식이 시장으로 나가 의결권 있는·유통되는 주식이 그만큼 늘어납니다.')
        else:
            notes.append('이 회사가 아닌 다른 회사 주식과 바꿔 주는 교환사채입니다. 이 회사의 주식 수는 바뀌지 않습니다.')
        if face and price and shares:
            exp = int(face * (p.get('ratio_pct') or 100) / 100 // price)
            calc('교환 주식 수 대조', f"{exp:,}주{_share_check(exp, shares)}", '사채 권면 총액 × 교환비율 ÷ 교환가액 (1주 미만 버림)', exp, '주')
    else:
        if face and price:
            exp = int(face * (p.get('ratio_pct') or 100) / 100 // price)
            chk = _share_check(exp, shares)
            calc(f'{w}하면 새로 생기는 주식 수(최대, 가정)', f"{exp:,}주{chk}", f'사채 권면 총액 × {w}비율 ÷ {pw} (1주 미만 버림). 모두 {w}한다고 놓은 최대 값', exp, '주')
            shares = shares or exp
        base, src = None, None
        if mkt and mkt.get('shares'):
            base, src = mkt['shares'], f"{mkt['date']} 상장 주식 수(시가총액 ÷ 종가)"
        elif shares and p.get('share_pct'):
            base, src = round(shares / p['share_pct'] * 100), '공시의 「주식총수 대비 비율」로 거꾸로 셈'
        if p.get('share_pct') is not None:
            fact('주식총수 대비 비율(원문 표)', f"{p['share_pct']:g}%", p['share_pct'], '%')
        if base and shares:
            d = round(shares / (base + shares) * 100, 4)
            calc(f'모두 {w}하면 기존 주주 지분이 줄어드는 정도(가정)', pc(d), f'새로 생기는 주식 수 ÷ (기존 주식 수 + 새로 생기는 주식 수) × 100. 기존 주식 수 = {src}', d, '%')
            if mkt and mkt.get('shares') and p.get('share_pct') is not None:      # J20: 회사마다 비율의 분모가 다름(증자 전 주식 수 / 증자 뒤 주식 수)
                r = round(shares / mkt['shares'] * 100, 2); r2 = round(d, 2); st = p['share_pct']
                chk = (' · 공시 비율과 같음(증자 전 주식 수 기준)' if abs(r - st) <= 0.5 else f" · 공시 비율 {st:g}%는 증자 뒤 주식 수 기준 값({pc(r2)})과 같음" if abs(r2 - st) <= 0.5
                       else f" · 공시 비율 {st:g}%와 {r - st:+.2f}%p 차이(공시는 다른 기준일 주식 수나 다른 사채까지 더한 값을 쓸 수 있음)")
                calc('새로 생기는 주식 수 ÷ 상장 주식 수', f"{pc(r)}{chk}", '새로 생기는 주식 수 ÷ 공시 전 마지막 거래일 상장 주식 수 × 100', r, '%')
        if k == 'BW':
            if p.get('separable'):
                fact('사채와 신주인수권 분리 여부', p['separable'])
            if p.get('pay_in'):
                fact('신주대금 납입방법', p['pay_in'])
                if '현금' in p['pay_in'] and shares and price:
                    calc('행사 때 회사로 들어오는 돈(현금 납입이면)', won(shares * price), '새로 생기는 주식 수 × 행사가액', shares * price, '원')
    close = mkt.get('close') if mkt else None
    if close and price:
        r = round((price / close - 1) * 100, 2)
        calc(f'{pw} ÷ 종가', f"{pc(r)} — {mkt['date']} 종가 {close:,.0f}원(공시 전 마지막 거래일)", f'({pw} ÷ 종가 − 1) × 100', r, '%')
    if p.get('call'):
        fact('콜옵션(매도청구권) 원문 일부', (p.get('options') or '')[:300])
        notes.append('콜옵션(매도청구권)이 있는 사채입니다. 회사나 회사가 정한 사람이 사채 일부를 되사 갈 수 있어, 주식으로 바꿀 사람이 달라질 수 있습니다. 최대 희석 계산은 바뀌지 않습니다.')
    for nm, key in (('청약일', 'sub_date'), ('납입일(발행일)', 'pay_date'), ('이사회 결의일', 'decided')):
        if p.get(key):
            fact(nm, p[key])
    if k != 'EB':
        _refix(f, p, mkt, fact, calc, held, T, notes, H)
    d8 = lambda v: v or '—'
    F2._generic_diff(f, calc, notes, H, [
        ('사채 권면 총액', lambda x: x.get('face'), lambda v: n(v, '원')), (pw, lambda x: x.get('price'), lambda v: n(v, '원')),
        ('새로 생기는(교환) 주식 수', lambda x: x.get('shares'), n), ('최저 조정가액', lambda x: x.get('floor'), lambda v: n(v, '원')),
        ('표면이자율', lambda x: x.get('coupon'), lambda v: '—' if v is None else f'{v:g}%'), ('만기이자율', lambda x: x.get('ytm'), lambda v: '—' if v is None else f'{v:g}%'),
        ('사채 만기일', lambda x: x.get('maturity'), d8), ('납입일', lambda x: x.get('pay_date'), d8), (f'{per} 시작일', lambda x: (x.get('period') or [None])[0], d8)])


def _refix(f, p, mkt, fact, calc, held, T, notes, H):
    """결정 3: 시가하락에 따른 조정(리픽싱) — 조건 상세 · 지난 조정일 다시 계산 · 주가 수준별 시나리오 표 · 시장 대비 확률."""
    k = p['bond']; w, pw, per = CV_WORD[k]; won = H['won']
    price, floor, face, rf = p.get('price'), p.get('floor'), p.get('face'), p.get('refix') or {}
    ratio = (p.get('ratio_pct') or 100) / 100
    if not floor:
        if rf.get('months') or rf.get('dates'):
            held.append(f'시가하락에 따른 {pw} 조정: 글에는 조정 주기가 있으나 최저 조정가액 칸이 비어 있어 시나리오는 계산하지 않음 — 원문을 확인해 주세요')
        else:
            notes.append(f'시가하락에 따른 {pw} 조정(리픽싱) 조건이 없는 사채입니다(최저 조정가액 칸 「-」). {pw}은 증자·감자 같은 사유가 있을 때만 바뀝니다.')
        return
    if not price or not face:
        return
    fact('최저 조정가액(원문 표)', f"{floor:,}원 — {pw}의 {floor / price * 100:.1f}%" + (f" · 근거(원문 일부): {p['floor_basis'][:120]}" if p.get('floor_basis') else ''), floor, '원')
    if floor >= price:
        notes.append(f'최저 조정가액이 지금 {pw} 이상이라 시가가 내려도 {pw}이 더 낮아지지 않습니다.'); return
    fs = int(face * ratio // floor)
    calc('최저 조정가액까지 내려가면 생기는 주식 수(최대, 가정)', f"{fs:,}주 — 지금 {pw} 기준보다 {fs - int(face * ratio // price):+,}주", f'사채 권면 총액 × {w}비율 ÷ 최저 조정가액 (1주 미만 버림)', fs, '주')
    base = (mkt or {}).get('shares')
    if base:
        d = round(fs / (base + fs) * 100, 4)
        calc(f'최저 조정가액에서 모두 {w}하면 기존 주주 지분이 줄어드는 정도(가정)', H['p'](d), '위 주식 수 ÷ (상장 주식 수 + 위 주식 수) × 100', d, '%')
    when = (f"매 {rf['months']}개월" + (f" {rf['days']}일" if rf.get('days') else '')) if rf.get('months') else None
    fact(f'{pw} 조정 주기(원문 글)', (when or '읽지 못함') + (f" · 조정일 {', '.join(rf['dates'][:6])}{' …' if len(rf['dates']) > 6 else ''}" if rf.get('dates') else '')
         + (' · 시가가 오르면 최초 가액까지 다시 올림' if rf.get('up') else ' · 내리는 쪽으로만 조정'))
    R = _rows(H.get('prices')); L = R[-1][0] if R else None
    cur, cur_src = price, '원문 표'
    if R and p.get('pay_date') and rf.get('standard_base'):                        # 지난 조정일은 기준 날짜까지의 시세로 다시 계산(회사의 조정 공시가 우선)
        hist = []
        for d in refix_dates(p, L):
            day = _trading_before(R, d, 1)
            c = next((r[1] for r in R if r[0] == day), None) if day else None
            m = _vwap(R, _back(day, months=1), day) if day else None; wk = _vwap(R, _back(day, days=7), day) if day else None; last = _vwap(R, day, day) if day else None
            if None in (c, m, wk, last):
                hist = None; break
            b = max((m + wk + last) / 3, last); new = _refix_once(cur, b, floor, price, rf.get('up')); hist.append((d, new)); cur = new
        if hist:
            cur_src = '시세로 다시 계산'
            calc(f'지난 조정일의 {pw}(시세로 다시 계산)', ' · '.join(f"{d} {v:,}원" for d, v in hist[-6:]) + f" — 지금 {cur:,}원",
                 f'조정일 전 거래일 기준 시가산정액 = max((1개월 + 1주일 + 그날 가중산술평균주가) ÷ 3, 그날 가중산술평균주가), 새 {pw} = max(최저 조정가액, min(이전 {pw}, 시가산정액)), 원 단위 올림. 회사의 조정 공시가 있으면 그 값이 우선', cur, '원')
        elif hist is None:
            cur = price
    close = R[-1][1] if R else (mkt or {}).get('close')
    if not close:
        held.append(f'{pw} 조정 시나리오: 가격 자료가 없어 계산하지 않음'); return
    TR = []
    cur_sh = int(face * ratio // cur)
    for lv in (-50, -40, -30, -20, -10, 0, 10, 20):
        P = close * (1 + lv / 100); new = _refix_once(cur, P, floor, price, rf.get('up')); sh = int(face * ratio // new)
        TR.append([f'{lv:+d}%' if lv else '지금 수준', f'{P:,.0f}원', f'{new:,}원' + (' (최저)' if new == floor else ''), f'{sh:,}주', f'{sh - cur_sh:+,}주',
                   H['p'](round(sh / (base + sh) * 100, 2)) if base else '—'])
    T.append({'title': f"{pw} 조정 시나리오 — 다음 조정일 시가산정액이 {L or mkt['date']} 종가 {close:,.0f}원 대비 이 수준이라면",
              'cols': ['주가 수준', '시가산정액', f'조정 후 {pw}', f'모두 {w}하면 생기는 주식', f'지금 {pw}({cur:,}원, {cur_src}) 대비', '기존 주주 지분이 줄어드는 정도'], 'rows': TR,
              'hint': f'원문의 조정 규칙(최저 {floor:,}원' + (', 오르면 최초 가액까지 다시 올림' if rf.get('up') else ', 내리는 쪽으로만') + ')을 가정한 주가 수준마다 적용한 값입니다. 어느 수준이 될지는 말하지 않습니다.'})
    _refix_prob(p, R, cur, close, fact, calc, held, T, notes, H)


def _refix_prob(p, R, cur, close, fact, calc, held, T, notes, H):
    """J17: 시장 시나리오별로, 앞으로 120거래일 안의 조정일마다 원문 규칙을 적용해 「한 번이라도 내려갈 확률」과 「최저 조정가액에 닿을 확률」."""
    import math
    from datetime import date, timedelta
    from . import filing as FL
    from . import prob as PB
    from . import tradecal as C
    k = p['bond']; w, pw, per = CV_WORD[k]; rf = p.get('refix') or {}; floor, price, face = p['floor'], p['price'], p['face']; ratio = (p.get('ratio_pct') or 100) / 100
    if not R or len(R) < 25 or not rf.get('standard_base') or not (rf.get('months') or rf.get('dates')) or not p.get('pay_date'):
        held.append(f'{pw} 조정 확률: 조정일·시가 산식을 원문에서 읽지 못했거나 시세가 모자라 계산하지 않음'); return
    L = R[-1][0]
    horizon = (date.fromisoformat(L) + timedelta(days=int(PB.H_COARSE * 7 / 5) + 10)).isoformat()
    days = []
    for d in refix_dates(p, horizon):
        if d <= L or (p.get('period') and p['period'][1] and d > p['period'][1]):
            continue
        h = C.count(_next(L), _trading_before(R, d, 1))
        if 1 <= h <= PB.H_COARSE:
            days.append((d, h))
    if not days:
        held.append(f'{pw} 조정 확률: 앞으로 {PB.H_COARSE}거래일 안에 조정일이 없어 계산하지 않음'); return
    try:
        S, key = PB.series_from_snapshot(H.get('snapshot') or '')
    except Exception:
        S, key = None, None
    tk = H.get('ticker'); hmax = days[-1][1]
    sg = PB.sigma(S, tk, L) if S and tk else None
    lib = PB.library(S, L, hmax, key) if S else None
    if sg is None or lib is None:
        held.append(f'{pw} 조정 확률: 이 회사의 직전 60거래일 시장 대비 변동성(또는 과거 경로)을 구하지 못해 계산하지 않음'); return
    import numpy as np
    hist = np.array([r[1] for r in R[-25:]], dtype=float)
    PR = []
    for ms, lbl in MARKETS:
        cum = PB.paths(lib, sg, hmax, math.log(1 + ms)); full = np.concatenate([np.tile(hist, (cum.shape[0], 1)), close * np.exp(cum)], axis=1)
        px_ = np.full(cum.shape[0], float(cur)); lowered = np.zeros(cum.shape[0], bool)
        for d, h in days:
            i = 25 + h - 1; c = full[:, i]
            b = np.maximum((full[:, i - 20:i + 1].mean(1) + full[:, i - 4:i + 1].mean(1) + c) / 3, c)
            new = np.ceil(np.maximum(floor, np.minimum(price if rf.get('up') else px_, b)) - 1e-9)
            lowered |= new < cur; px_ = new
        sh = np.floor(face * ratio / px_)
        p_low, p_floor = float(lowered.mean()), float((px_ <= floor).mean())
        q10, q50, q90 = (int(x) for x in np.quantile(sh, [0.1, 0.5, 0.9]))
        a, b_ = PB.shown(p_low, hmax), PB.shown(p_floor, hmax)
        H['est'](f'{pw} 조정 추정 — 시장 전체가 {lbl}', f"{days[-1][0]}까지 조정일 {len(days)}번 · {pw}이 지금({cur:,}원)보다 내려갈 확률 {a or '—'} · 최저 조정가액({floor:,}원)에 닿을 확률 {b_ or '—'} · 모두 {w}하면 생기는 주식 가운데 값 {q50:,}주(열에 여덟은 {q10:,}~{q90:,}주)",
                 f"사본 회사들의 과거 경로 {lib['n']:,}개({lib['from']}~{lib['to']})를 이 회사의 직전 60거래일 시장 대비 변동성에 맞춰 다시 쓰고, 조정일마다 원문 규칙(시가산정액, 최저 {floor:,}원" + (', 최초 가액까지 다시 올림' if rf.get('up') else ', 내리는 쪽으로만') + f")을 적용. 가중산술평균주가는 종가 평균으로 대신함. 마지막 조정일까지 {hmax}거래일(한국거래소 휴장일 반영).{C.note(L, days[-1][0])} {PB.evidence(hmax) or ''}", q50, '주')
        PR.append([f'시장 전체가 {lbl}', a or '—', b_ or '—', f'{q10:,}주', f'{q50:,}주', f'{q90:,}주'])
    T.append({'title': f'{pw} 조정 추정 — 시장 시나리오별(추정, {days[-1][0]}까지 조정일 {len(days)}번)', 'cols': ['시장 가정', f'지금 {pw}보다 내려갈 확률', '최저 조정가액에 닿을 확률', '생기는 주식(낮은 쪽)', '가운데 값', '높은 쪽'], 'rows': PR,
              'hint': '시장 전체가 얼마나 오르내릴지는 맞히지 않고 가정으로 넣었습니다. 확률은 이 회사가 시장과 다르게 움직이는 부분에만 붙였고, 과거 검증 오차에 맞춰 거칠게만 보입니다. 사채 발행 뒤에는 주가가 평소보다 크게 움직이는 일이 많아 실제 범위는 더 넓을 수 있습니다.'})


def parse_adjustment(doc):
    """v0.38 T2-4b 「전환가액(행사가액·교환가액)의 조정」 공시: 사유 · 적용일 · 회차별 조정 전후 가액. 두 서식(거래소 단독 서식 · 안내공시 서식)을 함께 읽는다.
    계산 종류가 아니라 리픽싱 계산을 실제 결과와 대조하는 데 쓴다."""
    T = tokens(doc); U = [t.replace(' ', '') for t in T]
    i = next((n for n in range(len(U) - 1, -1, -1) if re.match(r'^\d\.조정에관한사항', U[n])), None)
    rows = []
    if i is not None:
        h = i + 1
        while h < len(U) and re.search(r'회차|상장여부|조정전|조정후', U[h]):
            h += 1
        n = h - i - 1; k = h
        while n >= 3 and k + n <= len(U) and not re.match(r'^\d\.', U[k]):
            row = T[k:k + n]; pre, post = _num(row[-2]), _num(row[-1])
            if pre is not None and post is not None:
                rows.append({'series': row[0].strip(), 'pre': pre, 'post': post})
            k += n
    reason = _one(T, r'^\d\.조정사유')
    return {'reason': (reason or '').strip() or None, 'date': _one(T, r'^\d\.조정가액적용일', _date), 'rows': rows,
            'market_drop': bool(reason and '시가하락' in reason.replace(' ', ''))}


def compute(k, f, mkt, fact, calc, held, T, notes, H):
    if k == 'rights_issue':
        _rights_issue(f, mkt, fact, calc, held, T, notes, H)
    elif k == 'convertible':
        _convertible(f, mkt, fact, calc, held, T, notes, H)


# ── filing2 에 등록(종류 · 이름 · 읽는 함수 · 계산 함수)
F2.KINDS2 = tuple(dict.fromkeys(F2.KINDS2 + KINDS))
F2.KIND_LABEL2.update(LABELS)
F2.PARSERS2.update({'rights_issue': parse_rights_issue, 'convertible': parse_convertible})
F2.EXTRA.update({k: compute for k in KINDS})
