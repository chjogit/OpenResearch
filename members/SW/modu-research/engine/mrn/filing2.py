"""v0.38 T2-3 공시 1건을 숫자로 — 1등급 나머지(손익구조 변경 → 감자 → 유상증자 → 전환사채류 순으로 더한다).

filing.py 와 같은 원칙(원문 칸 값 그대로 · 읽지 못하면 보류 · 방향 판단 없음 · 식을 문장에). filing.py 가 KINDS2 종류를 이 파일로 넘긴다.
종류마다 따로 떼어 만든다 — PM이 한 종류의 판단만 되돌리고 싶으면 KINDS2 에서 그 종류만 빼면 된다.

판단 기록(PM 결정 2026-11-12 + 진행 중 판단, 번호는 NOTES.md 와 같음)
- J1 손익구조 변경: 증감률은 직전 값이 0보다 클 때만 다시 계산한다. 직전이 적자·0이면 계산하지 않고 공시 값과 부호로 본 전환 여부만 옮긴다(적자 기준 증감률은 뜻이 뒤집히기 쉬움).
- J3 손익구조 변경: 공시에 적힌 증감금액과 다시 계산한 값의 차이가 표 단위 2칸 이내면 「같음(반올림 차이)」로 본다(실제 원문 1,688칸 중 141칸이 이 경우, 그보다 큰 차이는 4칸).
- J4 감자: 감자 방법 칸의 글로 방식을 가른다 — 자기주식 소각 / 주식 병합 / 차등·일부 병합 / 액면 감액 / 유상 소각 / 무상 소각 / 여러 방식 / 그 밖. 주식 수·자본금·감자비율 대조는 방식과 무관하게 한다.
- J8 감자: 글로 가른 방식을 표의 숫자와 맞춰 본다(주식 수가 그대로면 액면 감액, 병합 비율과 주식 수가 0.5% 넘게 어긋나면 차등·일부 병합). 방법 칸이 여러 칸으로 나뉜 서식은 이어 붙여 읽는다.
  회사마다 표를 채우는 법이 달라(감자 주식 수 칸에 전체 주식을 적음 · 감자비율을 병합 비율로 적음 · 자본금이 주식 수 × 액면가와 다름) 그 경우를 「같음」의 다른 근거로 밝혀 적는다(상장사 전체 표본 332건으로 검증, 설명되지 않는 차이 3건).
- J9 감자(결정 4): 방식별 가치 변화는 방향 판단 없이 산술만 — 병합: 병합 배수·100주 주주의 주식 수와 단주·종가 × 배수 / 액면 감액: 바뀌지 않음 / 무상 소각: 남는 주식의 몫 배수 / 유상 소각: 지급 총액·감자차손익·(시가총액 − 지급액) ÷ 남는 주식 수.
  무상감자 공통으로 「자본잠식을 가르는 선」(자본금)이 내려가는 것을 보인다. 자본총계는 감자 공시에 없어 자본잠식률 자체는 계산하지 않는다(보류 T2-H5). 차등·여러 방식 감자는 1주 산술 값을 계산하지 않는다.
- J5 감자: 칸이 모두 「-」인 정정 공시(철회로 보이는 것)는 계산하지 않고 「값이 비어 있음 — 원문 확인」으로 알린다. 철회라고 단정하지 않는다.
- J2 정정 공시(결정 5): 같은 결산기간의 앞선 공시를 함께 읽어 바뀐 칸을 숫자로, 이유는 원문 「정정사유」 그대로. 뒤에 정정본이 있으면(기준 날짜 안) 이 공시는 계산하지 않고 최신본을 안내한다.
"""
import re
from .promise import tokens, _date, _find, _all, _one, _num, _pair, _span, UNIT

KINDS2 = ('pl_change', 'capital_reduction')
KIND_LABEL2 = {'pl_change': '매출액·손익구조 변경', 'capital_reduction': '감자 결정'}
PL_ROWS = (('revenue', '매출액'), ('op', '영업이익'), ('pretax', '법인세비용차감전계속사업이익'), ('net', '당기순이익'))
PL_NAME = {'revenue': '매출액', 'op': '영업이익', 'pretax': '법인세차감전 계속사업이익', 'net': '당기순이익'}
BS_ROWS = (('assets', '자산총계'), ('liab', '부채총계'), ('equity', '자본총계'), ('capital', '자본금'))
BS_NAME = {'assets': '자산총계', 'liab': '부채총계', 'equity': '자본총계', 'capital': '자본금'}
_NUM = re.compile(r'^-?\d+(\.\d+)?$')


def _v(t):
    """표의 숫자 칸 → float(없음·「-」는 None). △·▲·괄호 음수도 읽는다."""
    s = (t or '').replace(',', '').replace(' ', '').replace('△', '-').replace('▲', '-')
    if re.fullmatch(r'\(\d+(\.\d+)?\)', s):
        s = '-' + s[1:-1]
    return float(s) if _NUM.match(s) else None


def _amt(t, mult):
    from decimal import Decimal
    s = (t or '').replace(',', '').replace(' ', '').replace('△', '-').replace('▲', '-')
    if re.fullmatch(r'\(\d+(\.\d+)?\)', s):
        s = '-' + s[1:-1]
    return int(Decimal(s) * mult) if mult and _NUM.match(s) else None


def _unit(T, pat, start):
    for k in range(start, len(T)):
        m = re.search(pat + r'\(단위:([^)]+)\)', T[k].replace(' ', ''))
        if m:
            return k, m.group(1)
    return -1, None


def parse_pl_change(doc):
    """「매출액 또는 손익구조 30%(대규모법인 15%) 이상 변경」 본문 표. 정정 공시는 앞의 정정표가 아니라 본문(마지막 「1. 재무제표의 종류」 뒤)을 읽는다."""
    T = tokens(doc)
    out = {'basis': None, 'period': {}, 'unit': None, 'rows': {}, 'bs': {}, 'bs_unit': None, 'large': None, 'reasons': [], 'decided': None,
           'corrects': None, 'correction_reason': None, 'layout': None}
    for pat in (r'정정관련공시서류제출일', r'정정대상공시서류의최초제출일'):
        i = _find(T, pat)
        if i >= 0:
            out['corrects'] = next((d for d in (_date(t) for t in T[i:i + 3]) if d), None)
            j = _find(T, r'^3\.정정사유$', i)
            if 0 <= j < len(T) - 1:
                out['correction_reason'] = T[j + 1].strip()
            break
    idx = _all(T, r'^1\.재무제표의종류$')
    if not idx:
        return out
    h = idx[-1]
    out['basis'] = T[h + 1].strip() if h + 1 < len(T) else None
    for key, lab in (('start', '-시작일'), ('end', '-종료일')):
        i = _find(T, '^' + lab + '$', h)
        if i >= 0 and i + 2 < len(T):
            out['period'][key] = (_date(T[i + 1]), _date(T[i + 2]))
    u, unit = _unit(T, r'변동내용', h)
    if u < 0:
        return out
    mult = UNIT.get(unit); out['unit'] = unit
    first = _find(T, r'^-매출액$', u)
    if first < 0:
        return out
    wide = any(T[k].replace(' ', '') == '흑자적자전환여부' for k in range(u, first))
    n = 5 if wide else 4; out['layout'] = n
    for key, lab in PL_ROWS:
        i = _find(T, '^-' + lab + '$', u)
        if i < 0 or i + n >= len(T):
            continue
        v = T[i + 1:i + 1 + n]
        out['rows'][key] = {'cur': _amt(v[0], mult), 'prev': _amt(v[1], mult), 'diff_stated': _amt(v[2], mult), 'rate_stated': _v(v[3]),
                            'rate_text': None if _v(v[3]) is not None or v[3].strip() in ('-', '') else v[3].strip(),
                            'turn': (v[4].strip() if wide and v[4].strip() not in ('-', '') else None)}
    i = _find(T, r'^-대규모법인여부$', u)
    if 0 <= i < len(T) - 1:
        out['large'] = T[i + 1].strip()
    b, bunit = _unit(T, r'재무현황', u)
    if b >= 0:
        bm = UNIT.get(bunit); out['bs_unit'] = bunit
        for key, lab in BS_ROWS:
            i = _find(T, '^-' + lab + '$', b)
            if 0 <= i and i + 2 < len(T):
                out['bs'][key] = {'cur': _amt(T[i + 1], bm), 'prev': _amt(T[i + 2], bm)}
        i = _find(T, r'^-자본총계/자본금비율', b)
        if 0 <= i and i + 2 < len(T):
            out['bs']['eq_cap_stated'] = {'cur': _v(T[i + 1]), 'prev': _v(T[i + 2])}
        i = _find(T, r'^-자본잠식률', b)
        if 0 <= i and i + 2 < len(T):
            out['bs']['impair_stated'] = {'cur': _v(T[i + 1]), 'prev': _v(T[i + 2])}
    r0 = _find(T, r'변동주요원인$', u); r1 = _find(T, r'이사회결의일\(결정일\)$', max(r0, u))
    if 0 <= r0 < r1:
        out['reasons'] = [t.strip() for t in T[r0 + 1:r1] if t.strip() not in ('-', '')][:12]
    if r1 >= 0 and r1 + 1 < len(T):
        out['decided'] = _date(T[r1 + 1])
    i = _find(T, r'^매출액\(단위:', u)
    if 0 <= i and i + 3 < len(T) and T[i + 1].strip() == '별도':
        m = re.search(r'단위:([^)]+)\)', T[i].replace(' ', ''))
        sm = UNIT.get(m.group(1)) if m else None
        out['separate_revenue'] = {'cur': _amt(T[i + 2], sm), 'prev': _amt(T[i + 3], sm)}
    return out


def _correction_head(T):
    out = {'corrects': None, 'correction_reason': None}
    for pat in (r'정정대상공시서류의최초제출일', r'정정관련공시서류제출일'):
        i = _find(T, pat)
        if i >= 0:
            out['corrects'] = next((d for d in (_date(t) for t in T[i:i + 3]) if d), None); break
    j = _find(T, r'^(3\.)?정정사유$')
    if 0 <= j < len(T) - 1:
        nx = [t.replace(' ', '') for t in T[j + 1:j + 5]] + [''] * 4
        if nx[0] == '정정전' and nx[1] == '정정후':            # 주요사항보고서: 「항목 | 정정사유 | 정정전 | 정정후」 머리 → 첫 줄의 둘째 칸이 사유
            v = T[j + 4].strip() if j + 4 < len(T) else ''
            ok = v and not nx[2].startswith('주요사항보고서') and len(v) >= 4 and not re.fullmatch(r'[\d,.\s년월일주원%-]+', v)
            out['correction_reason'] = v if ok else None
        else:                                                 # 거래소 공시: 「3. 정정사유 | 사유」
            out['correction_reason'] = T[j + 1].strip() or None
    return out


def _two_after(T, i, f=_num, span=6):
    """i 뒤 span칸 안에서 처음 나오는 값 두 개(「감자전 | 감자후 | 값 | 값」, 「보통주식(주) | 값 | 값」)."""
    vals = []
    for t in T[i + 1:i + 1 + span]:
        s = t.replace(' ', '')
        if s == '-':
            vals.append(None)
        elif f(t) is not None:
            vals.append(f(t))
        elif vals:
            break
    return (vals + [None, None])[:2]


_RATIO = re.compile(r'(\d[\d,]*(?:\.\d+)?)주를(.{0,40}?)(\d[\d,]*(?:\.\d+)?)주로')
_RATIO2 = re.compile(r'(?<![\d.])(\d{1,3}(?:\.\d+)?)(?::|대)(\d{1,3}(?:\.\d+)?)(?![\d.])')
RED_TYPE = {'treasury': '자기주식 소각', 'merge': '주식 병합(무상감자)', 'merge_diff': '차등·일부 병합(표의 주식 수가 한 가지 병합 비율과 맞지 않는 무상감자)', 'par_cut': '액면 감액(무상감자)',
            'paid': '유상 소각(유상감자)', 'free_retire': '무상 소각', 'mixed': '여러 방식을 함께 쓰는 감자', 'other': '그 밖의 방식', 'empty': '값이 비어 있음'}


def _fnum(s):
    return float(s.replace(',', ''))


def method_facts(method):
    """J8: 감자 방법 칸의 글에서 읽는 것 — 쓰인 방식들(kinds), 병합 비율들(ratios, [앞, 뒤]), 감액 후 액면가(new_par), 1주당 유상소각대금(pay).
    「단주는 … 소각」처럼 단주 처리만 말하는 대목은 방식으로 세지 않는다."""
    m = (method or '').replace(' ', '')
    out = {'kinds': [], 'ratios': [], 'new_par': None, 'pay': None, 'split': False}
    if not m or m == '-':
        return out
    t = re.sub(r'단주[^.。)]{0,60}?소각', '', m)
    ratios = [[_fnum(a), _fnum(b)] for a, _mid, b in _RATIO.findall(t) if _fnum(b) > 0 and _fnum(a) > _fnum(b)]
    if not ratios and ('병합' in t or '감자' in t):
        ratios = [[float(a), float(b)] for a, b in _RATIO2.findall(t) if float(b) > 0 and float(a) > float(b)]
    uniq = []
    for r in ratios:
        if r not in uniq:
            uniq.append(r)
    out['ratios'] = uniq
    out['split'] = '분할' in t
    paid = '유상' in t
    par_cut = '액면' in t and bool(re.search(r'액면[가액금]{0,2}[을를]?(감액|감소|인하)', t) or re.search(r'원으로(감액|감소|인하)', t) or re.search(r'원(에서|→)금?[\d,]+원', t))
    treasury = bool(re.search(r'자기주식(?!을?제외)', t)) and ('소각' in t or '무상감자' in t)
    free = '소각' in re.sub(r'자기주식[^,.]{0,14}소각|유상소각|이익소각', '', t) and not paid
    merge = '병합' in t or bool(uniq)
    out['kinds'] = [k for k, on in (('paid', paid), ('merge', merge), ('par_cut', par_cut), ('treasury', treasury), ('free_retire', free)) if on]
    if par_cut:
        g = re.search(r'([\d,]+)원으로(감액|감소|인하)', t) or re.search(r'원(?:에서|→)금?([\d,]+)원', t) or re.search(r'액면[가액금]{0,2}([\d,]+)원으로', t)
        if g:
            out['new_par'] = int(g.group(1).replace(',', ''))
    if paid:
        g = re.search(r'1주당([\d,]+)원', t)
        if g:
            out['pay'] = int(g.group(1).replace(',', ''))
    return out


def reduction_type(method, mf=None):
    """방법 칸의 글로 가른 방식(숫자와의 대조는 _refine_type)."""
    m = (method or '').replace(' ', '')
    if not m or m == '-':
        return 'empty'
    k = set((mf or method_facts(method))['kinds'])
    if 'paid' in k:
        return 'paid' if k == {'paid'} else 'mixed'
    if 'merge' in k:
        return 'merge' if k == {'merge'} else 'mixed'
    if len(k) > 1:
        return 'mixed'
    return next(iter(k)) if k else 'other'


def _refine_type(p):
    """J8: 글로 가른 방식을 표의 숫자(주식 수·자본금 전후)와 맞춰 본다. 맞지 않으면 숫자를 따르고 그 사실을 남긴다."""
    typ = p['type']
    S, SO, C = p['shares'], p['shares_other'], p['capital']
    sb, sa = S.get('before'), S.get('after')
    have = sb is not None and sa is not None
    tb = (sb or 0) + (SO.get('before') or 0); ta = (sa or 0) + (SO.get('after') or 0)
    if SO.get('before') is not None and SO.get('after') is not None and sb is None and sa is None:
        have = True
    cb, ca = C.get('before'), C.get('after')
    if typ == 'empty' or not have:
        return typ, None
    ds = tb - ta
    if ds == 0:
        if typ == 'par_cut':
            return typ, None
        if cb is not None and ca is not None and cb > ca:
            return 'par_cut', (None if typ == 'other' else f'방법 칸의 글은 「{RED_TYPE[typ]}」로 읽히지만 표에서는 주식 수가 그대로이고 자본금만 줄어듭니다 — 액면 감액으로 계산했습니다. 원문을 확인해 주세요.')
        return typ, None
    if typ == 'par_cut':
        return 'other', '방법 칸의 글은 「액면 감액」으로 읽히지만 표에서는 주식 수가 줄어듭니다 — 방식별 계산은 하지 않았습니다. 원문을 확인해 주세요.'
    rs = p['ratios']
    fits = bool(len(rs) == 1 and sb and sa is not None and abs(sa - sb * rs[0][1] / rs[0][0]) <= max(1.0, sb * rs[0][1] / rs[0][0] * 0.005))   # 단주 처리로 생기는 차이(0.5% 안)
    if typ == 'mixed' and set(p['kinds']) == {'merge', 'free_retire'} and fits and '차등' not in (p.get('method') or ''):
        return 'merge', None                                   # 앞 단계의 소각을 글로만 언급하고, 이 표의 주식은 모두 한 비율로 병합되는 경우
    if typ == 'merge':
        if len(rs) > 1 or '차등' in (p.get('method') or '') or (rs and sb and sa is not None and not fits):
            return 'merge_diff', None
    return typ, None


def _between(T, pa, pb, cap=12):
    """pa 칸 다음부터 pb 칸 앞까지를 이어 붙인 글(방법 칸이 여러 칸으로 나뉜 서식). 「-」만 있는 칸은 뺀다. pb 를 못 찾으면 첫 칸만."""
    ia = (_all(T, pa) or [-1])[-1]
    if ia < 0 or ia + 1 >= len(T):
        return None
    out = []
    for t in T[ia + 1:ia + 1 + cap]:
        if re.match(pb, t.replace(' ', '')):
            return ' '.join(out) or None
        if t.strip() not in ('-', ''):
            out.append(t.strip())
    return T[ia + 1].strip() if T[ia + 1].strip() not in ('-', '') else None


def parse_capital_reduction(doc):
    """주요사항보고서(감자결정) 본문 표. 정정 공시는 본문 서식의 칸을 읽는다."""
    T = tokens(doc)
    out = _correction_head(T)
    q, qo = _pair(T, r'^1\.감자주식의종류와수')
    out.update(qty=q, qty_other=qo, par=_one(T, r'^2\.1주당액면가액', _num))
    i = (_all(T, r'^3\.감자전후자본금') or [-1])[-1]
    out['capital'] = dict(zip(('before', 'after'), _two_after(T, i))) if i >= 0 else {}
    i = (_all(T, r'^4\.감자전후발행주식수') or [-1])[-1]
    out['shares'], out['shares_other'] = {}, {}
    if i >= 0:
        j = _find(T, r'^보통주식\(주\)$', i); k = _find(T, r'^(기타|종류)주식\(주\)$', i)
        if 0 <= j < i + 12:
            out['shares'] = dict(zip(('before', 'after'), _two_after(T, j, span=2)))
        if 0 <= k < i + 14:
            out['shares_other'] = dict(zip(('before', 'after'), _two_after(T, k, span=2)))
    out['ratio_text'] = [None, None]
    i = (_all(T, r'^5\.감자비율') or [-1])[-1]
    if i >= 0:
        seg = T[i + 1:i + 6]
        for n, t in enumerate(seg[:-1]):
            u = t.replace(' ', '')
            if u.startswith('보통주식') and out['ratio_text'][0] is None:
                out['ratio_text'][0] = seg[n + 1].strip()
            elif (u.startswith('기타주식') or u.startswith('종류주식')) and out['ratio_text'][1] is None:
                out['ratio_text'][1] = seg[n + 1].strip()
    out.update(base_date=_one(T, r'^6\.감자기준일', _date), method=_between(T, r'^7\.감자방법', r'^8\.감자사유'), reason=_one(T, r'^8\.감자사유'),
               agm=_one(T, r'^주주총회예정일$', _date), relist=_one(T, r'^신주상장예정일$', _date), halt=list(_span(T, r'^매매거래정지예정기간$')),
               decided=_one(T, r'^12\.이사회결의일', _date))
    mf = method_facts(out['method'])
    out.update(kinds=mf['kinds'], ratios=mf['ratios'], new_par=mf['new_par'], pay=mf['pay'], split=mf['split'])
    i = (_all(T, r'^14\.기타투자판단') or [-1])[-1]
    tail = [t.strip() for t in T[i + 1:i + 40]] if i >= 0 else []
    out['fraction_text'] = next((re.search(r'[^.。]*단주[^.。]*', t).group(0).strip()[:220] for t in tail if '단주' in t), None)
    if out['pay'] is None and 'paid' in mf['kinds']:
        g = next((re.search(r'1주당([\d,]+)원', t.replace(' ', '')) for t in tail if '유상' in t and re.search(r'1주당([\d,]+)원', t.replace(' ', ''))), None)
        out['pay'] = int(g.group(1).replace(',', '')) if g else None
    out['type'] = reduction_type(out['method'], mf) if (q is not None or qo is not None or out['capital'].get('before')) else 'empty'
    out['type_text'] = out['type']
    out['type'], out['type_conflict'] = _refine_type(out)
    return out


PARSERS2 = {'pl_change': parse_pl_change, 'capital_reduction': parse_capital_reduction}
EXTRA = {}                                                    # 다른 파일(filing3 등)이 등록하는 종류 → 계산 함수
ATTACH = {}                                                   # v0.39 T3-2: 종류별 정정 묶음 함수(없으면 아래 attach_history 그대로)


def _fy(p, rcept_dt):
    """같은 결산인지 가르는 열쇠: 결산 종료일(2026년 서식) 또는, 종료일 칸이 없는 서식이면 접수 연도. 재무제표 종류(연결·개별)도 함께."""
    e = (p.get('period') or {}).get('end')
    return (e[0] if e and e[0] else f'접수 {rcept_dt[:4]}년'), p.get('basis')


def _decision_key(p, rcept_dt):
    """같은 결정인지 가르는 열쇠: 정정 공시면 원래 공시의 제출일, 아니면 이 공시의 접수일."""
    return p.get('corrects') or rcept_dt


def attach_history(out, man, ticker, last, root, open_doc, own_exclude):
    """같은 회사·같은 결산기간·같은 재무제표 종류의 다른 손익구조 변경 공시(기준 날짜 안): 앞선 것은 history, 뒤의 것은 newer."""
    kind, no = out['kind'], out['rcept_no']
    if kind in ATTACH:                                        # v0.39 T3-2 공급계약·타법인: 계약상대 + 정정의 정정까지 잇는 묶음
        return ATTACH[kind](out, man, ticker, last, root, open_doc, own_exclude)
    keyf = _fy if kind == 'pl_change' else _decision_key
    key = keyf(out['parsed'], out['rcept_dt'])
    out['newer'] = []
    for n, x in sorted(man['docs'].items()):
        if n == no or x['ticker'] != ticker or x['kind'] != kind or x['rcept_dt'] > last or own_exclude.search(x.get('report_nm') or ''):
            continue
        files, _ = open_doc(n, root, man)
        p = PARSERS2[kind]('\n'.join(t for _, t in files))
        if keyf(p, x['rcept_dt']) != key:
            continue
        row = {'rcept_no': n, 'rcept_dt': x['rcept_dt'], 'url': x['url'], 'report_nm': x['report_nm']}
        if n < no:
            out['history'].append({**row, 'parsed': p}); out['docs'].append({'rcept_no': n, 'sha256': x['sha256']})
        else:
            out['newer'].append(row)


def _basis(t):
    t = (t or '').replace(' ', '')
    return '연결' if '연결' in t else '별도' if ('별도' in t or '개별' in t) else None


def attach_prelim(out, man, ticker, last, root, open_doc, own_exclude):
    """v0.38 T2-4f: 같은 회사·같은 결산기간(시작~끝)의 앞선 잠정실적(이 공시보다 먼저 접수, 기준 날짜 안). 정정이 있으면 가장 늦은 것.
    out['prelim'] = {rcept_no, rcept_dt, url, report_nm, basis, unit, rows{항목: 원}} 또는 None. 재무제표 종류가 달라 견주지 않은 것은 out['prelim_other']."""
    from .filing import parse as fl_parse
    out['prelim'] = out['prelim_other'] = None
    per = out['parsed'].get('period') or {}
    if not (per.get('start') and per.get('end') and per['start'][0] and per['end'][0]):
        return
    rng, mine = (per['start'][0], per['end'][0]), _basis(out['parsed'].get('basis'))
    for n, x in sorted(man['docs'].items()):
        if n >= out['rcept_no'] or x['ticker'] != ticker or x['kind'] != 'prelim' or x['rcept_dt'] > last or own_exclude.search(x.get('report_nm') or ''):
            continue
        files, _ = open_doc(n, root, man)
        try:
            p = fl_parse('prelim', '\n'.join(t for _, t in files))
        except (ValueError, KeyError, TypeError):
            continue
        pp = p.get('period') or {}
        col = 'ytd' if tuple(pp.get('ytd') or ()) == rng else 'cur' if tuple(pp.get('cur') or ()) == rng else None
        if not col:
            continue
        b = '연결' if '연결' in (x.get('report_nm') or '').replace(' ', '') else '별도'
        row = {'rcept_no': n, 'rcept_dt': x['rcept_dt'], 'url': x['url'], 'report_nm': x['report_nm'], 'basis': b, 'unit': p.get('unit'),
               'rows': {k: (r or {}).get(col) for k, r in (p.get('rows') or {}).items()}}
        if mine and b != mine:
            out['prelim_other'] = row
        else:
            out['prelim'] = row
    if out['prelim']:
        out['docs'].append({'rcept_no': out['prelim']['rcept_no'], 'sha256': man['docs'][out['prelim']['rcept_no']]['sha256']})


def _vs_prelim(f, rows, calc, notes, T, H):
    """v0.38 T2-4f(J25): 같은 결산의 앞선 잠정실적과 이 공시의 값을 견준다. 잠정실적 표 단위 안의 차이는 반올림으로 본다. 방향 판단 없음."""
    from .filing import MONEY_UNIT
    pr, po = f.get('prelim'), f.get('prelim_other')
    if not pr:
        if po:
            notes.append(f"앞서 낸 잠정실적({po['rcept_dt']}, {po['basis']} 기준)은 이 공시와 재무제표 종류가 달라 견주지 않았습니다.")
        return
    um = MONEY_UNIT.get(pr.get('unit') or '', 1)
    R = []
    for key, name in PL_NAME.items():
        a, b = (rows.get(key) or {}).get('cur'), pr['rows'].get(key)
        if a is None:
            continue
        if b is None:
            R.append([name, '잠정실적에 없음', H['won'](a), '—', '—']); continue
        d = a - b
        if d == 0:
            v = '같음'
        elif abs(d) <= 2 * um:                                           # J3와 같은 기준: 표 단위 2칸 안은 반올림·끝수 처리 차이
            v = f"같음(잠정실적 표 단위 {pr['unit']} 반올림 안)"
        else:
            pc = d / abs(b) * 100 if b else None
            v = f"{H['won'](d)} 다름" + ('' if pc is None else f" ({pc:+.2f}%)" if abs(pc) >= 0.01 else ' (0.01% 미만)')
        calc(f"{name} — 앞서 낸 잠정실적과 대조", f"잠정 {H['won'](b)} → 이 공시 {H['won'](a)} · {v}",
             f"이 공시 값 − 잠정실적({pr['rcept_dt']}, 접수번호 {pr['rcept_no']}) 값", d, '원')
        R.append([name, H['won'](b), H['won'](a), H['won'](d), v])
    if R:
        T.append({'title': f"앞서 낸 잠정실적과 대조 — {pr['rcept_dt']} 「{pr['report_nm']}」", 'cols': ['구분', '잠정실적', '이 공시', '차이', '판정'], 'rows': R,
                  'hint': '같은 결산기간·같은 재무제표 종류의 앞선 잠정실적(공정공시)과 견준 값입니다. 잠정실적은 표 단위(예: 억원)로 반올림돼 있어 표 단위 2칸 안의 차이는 같다고 봅니다. 좋다·나쁘다를 뜻하지 않습니다.'})


def _turn(cur, prev):
    if cur is None or prev is None:
        return None
    if prev < 0 <= cur:
        return '흑자전환'
    if prev >= 0 > cur:
        return '적자전환'
    if prev < 0 and cur < 0:
        return '적자지속(적자 축소)' if cur > prev else '적자지속(적자 확대)' if cur < prev else '적자지속'
    return None


def compute(k, f, mkt, fact, calc, held, T, notes, H):
    """H = filing.py 의 도우미(_won, _p, _pct, stated_check)."""
    if f.get('newer'):
        nw = f['newer'][-1]
        held.append(f"이 공시는 {nw['rcept_dt']}에 정정됐어요 — 최신본(접수번호 {nw['rcept_no']})으로 계산해 주세요. 이 공시의 값은 계산하지 않음")
        notes.append(f"이 공시 뒤에 정정 공시가 {len(f['newer'])}건 있습니다(가장 최근 {nw['rcept_dt']}, 접수번호 {nw['rcept_no']}).")
        return
    if k == 'pl_change':
        _pl_change(f, fact, calc, held, T, notes, H)
    elif k == 'capital_reduction':
        _capital_reduction(f, mkt, fact, calc, held, T, notes, H)
    elif k in EXTRA:
        EXTRA[k](k, f, mkt, fact, calc, held, T, notes, H)


def _ratio_check(mine, text):
    """공시의 비율 칸(글자 그대로)과 다시 계산한 값을 그 칸의 소수 자릿수로 견준다."""
    t = (text or '').replace(',', '').replace('%', '').strip()
    if not re.fullmatch(r'-?\d+(\.\d+)?', t) or mine is None:
        return ''
    dec = len(t.split('.')[1]) if '.' in t else 0
    st = float(t)
    if abs(round(mine, dec) - st) < 1e-9:
        return f' · 공시 값 {t}%와 같음' + (f'(공시는 소수 {dec}자리)' if dec < 2 else '')
    if abs(mine - st) <= 10 ** -dec:                             # 올림·버림으로 적은 경우
        return f' · 공시 값 {t}%와 같음(공시는 소수 {dec}자리에서 올림 또는 버림)'
    return f' · 공시 값 {t}%와 {mine - st:+.2f}%p 다름 — 원문 표를 직접 확인해 주세요'


def _generic_diff(f, calc, notes, H, fields):
    """결정 5: 바로 앞 공시와 달라진 칸(fields = [(이름, 꺼내는 함수, 보이는 함수)])을 숫자로, 이유는 원문 정정사유 그대로."""
    p = f['parsed']
    if p.get('corrects') or f.get('history'):
        notes.append(f"정정 공시입니다(원래 공시 {p.get('corrects') or '날짜 미기재'}). 이 공시의 본문 값을 썼습니다.")
    if not f.get('history'):
        return
    old = f['history'][-1]; q = old['parsed']; ch = []
    for name, get, show in fields:
        a, b = get(q), get(p)
        if a != b and not (a is None and b is None):
            d = ''
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
                d = f" ({b - a:+,}" + (f", {(b - a) / abs(a) * 100:+.2f}%" if a else '') + ')'
            ch.append(f"{name} {show(a)} → {show(b)}{d}")
    if ch:
        calc(f"앞선 공시({old['rcept_dt']}, 접수번호 {old['rcept_no']})와 달라진 곳 {len(ch)}곳", ' / '.join(ch), '이 공시의 값과 앞선 공시의 값을 견줌(두 원문 표)')
    else:
        notes.append(f"앞선 공시({old['rcept_dt']})와 이 화면이 읽는 칸의 값은 같습니다(다른 칸이 정정된 공시).")
    if p.get('correction_reason'):
        notes.append(f"회사가 적은 정정사유(원문 그대로): 「{p['correction_reason']}」")


def _capital_reduction(f, mkt, fact, calc, held, T, notes, H):
    from fractions import Fraction
    p = f['parsed']; typ = p.get('type') or 'other'
    n = lambda v, u='주': '—' if v is None else f'{v:,}{u}'
    won = H['won']
    if typ == 'empty':                                              # J5
        held.append('이 공시는 감자 주식 수·자본금 칸이 모두 비어 있어요(「-」) — 계산하지 않음. 앞선 감자 결정을 거둔 공시일 수 있으니 원문을 확인해 주세요')
        if p.get('corrects'):
            notes.append(f"정정 공시입니다(원래 공시 {p['corrects']}).")
        if f.get('history'):
            old = f['history'][-1]
            notes.append(f"앞선 공시({old['rcept_dt']}, 접수번호 {old['rcept_no']})에 적혀 있던 감자 주식 수·자본금이 이 공시에서는 모두 빈칸입니다.")
        if p.get('correction_reason'):
            notes.append(f"회사가 적은 정정사유(원문 그대로): 「{p['correction_reason']}」")
        return
    q, qo = p.get('qty'), p.get('qty_other'); S, SO, C = p.get('shares') or {}, p.get('shares_other') or {}, p.get('capital') or {}
    sb, sa, ob, oa = S.get('before'), S.get('after'), SO.get('before'), SO.get('after')
    cb, ca, par = C.get('before'), C.get('after'), p.get('par')
    merges = ('merge', 'merge_diff', 'mixed')
    fact('감자 방법(원문 그대로)', (p.get('method') or '—')[:500]); fact('감자 방식(방법 칸의 글로 가름)', RED_TYPE[typ])
    if p.get('type_conflict'):
        notes.append(p['type_conflict'])
    if p.get('reason'):
        fact('감자 사유(원문 그대로)', p['reason'][:300])
    if q is None and qo is None:
        held.append('감자 주식 수: 원문 표에서 읽지 못함 — 보류')
    else:
        fact('감자 주식 수', ' · '.join(([f'보통주 {q:,}주'] if q is not None else ['보통주 없음']) + ([f'기타주 {qo:,}주'] if qo else [])), q if q is not None else qo, '주')
    for lbl, qty, sh, rt in (('보통주', q, S, p['ratio_text'][0]), ('기타주', qo, SO, p['ratio_text'][1])):
        b, a = sh.get('before'), sh.get('after')
        if b is None or (not qty and (a is None or a == b)):
            continue
        fact(f'감자 전후 발행주식 수({lbl})', f'{b:,}주 → {n(a)}', b, '주')
        if typ == 'par_cut':                                        # 액면 감액: 주식 수는 그대로. 감자 주식 수 칸에는 액면이 줄어드는 주식(보통 전체)을 적는다
            if a is not None:
                calc(f'감자 후 주식 수 대조({lbl})', f"{a:,}주 · 감자 전과 같음(액면 감액은 주식 수가 바뀌지 않음)" if a == b else f"{a:,}주 · 감자 전 {b:,}주와 {a - b:+,}주 다름 — 원문을 직접 확인해 주세요",
                     '액면 감액은 주식 수를 바꾸지 않음(공시 표의 감자 전후 주식 수를 견줌)', a, '주')
            continue
        r = None
        if a is not None and typ in merges:                         # 병합: 줄어든 주식 수 = 전 − 후. 감자 주식 수 칸에 병합 대상 전체를 적는 회사도 있다
            d = b - a
            if qty == d:
                msg = ' · 감자 주식 수 칸과 같음'
            elif qty == b:
                msg = f' · 감자 주식 수 칸({qty:,}주)에는 병합 대상 주식 전체를 적은 공시'
            elif qty:
                msg = f' · 감자 주식 수 칸 {qty:,}주와 {d - qty:+,}주 다름' + ('(단주 처리 등 작은 차이)' if abs(d - qty) <= max(1, b // 1000) else ' — 원문을 직접 확인해 주세요')
            else:
                msg = ''
            calc(f'줄어드는 주식 수({lbl})', f"{d:,}주{msg}", '감자 전 발행주식 수 − 감자 후 발행주식 수', d, '주')
            r = round(d / b * 100, 4)
            chk = _ratio_check(r, rt)
            if '다름' in chk:                                      # 회사가 주식 수가 아니라 병합 비율(1 − 뒤 ÷ 앞)을 적은 경우
                for ra, rb in (p.get('ratios') or []):
                    nom = round((1 - rb / ra) * 100, 4)
                    if '같음' in _ratio_check(nom, rt):
                        chk = f" · 공시 값 {rt.strip()}%는 병합 비율({ra:g}주→{rb:g}주)로 계산한 값과 같음(주식 수로 계산한 값과는 {r - float(rt.replace(',', '').replace('%', '')):+.2f}%p 차이)"; break
            calc(f'감자비율({lbl})', f"{H['p'](r)}{chk}", '(감자 전 − 감자 후 발행주식 수) ÷ 감자 전 발행주식 수 × 100', r, '%')
            continue
        if not qty:
            continue
        if a is not None:
            ok = b - qty == a
            calc(f'감자 후 주식 수 대조({lbl})', f"{b - qty:,}주" + (' · 공시의 감자 후 값과 같음' if ok else f' · 공시의 감자 후 값 {a:,}주와 {a - (b - qty):+,}주 다름 — 원문을 직접 확인해 주세요'), '감자 전 주식 수 − 감자 주식 수', b - qty, '주')
        r = round(qty / b * 100, 4)
        calc(f'감자비율({lbl})', f"{H['p'](r)}{_ratio_check(r, rt)}", '감자 주식 수 ÷ 감자 전 발행주식 수 × 100', r, '%')
    tb = (sb or 0) + (ob or 0); ta = (sa or 0) + (oa or 0)
    full = (sb is None) == (sa is None) and (ob is None) == (oa is None) and tb > 0 and (sa is not None or oa is not None)
    ds = tb - ta if full else None
    d = None
    if cb is not None and ca is not None:
        fact('감자 전후 자본금', f"{won(cb)} → {won(ca)}", cb, '원')
        d = cb - ca
        if typ == 'par_cut':
            np_ = p.get('new_par')
            if np_ is None and ta and ca % ta == 0:
                np_ = ca // ta; src = '감자 후 자본금 ÷ 발행주식 수'
            else:
                src = '방법 칸의 글'
            if par and np_:
                fact('1주당 액면가', f'{par:,}원 → {np_:,}원', np_, '원', src)
                exp = tb * (par - np_)
                msg = (' · 발행주식 수 × 액면가 감소분과 같음' if exp == d
                       else ' · 감자 후 자본금이 발행주식 수 × 감액 후 액면가와 같음(감자 전 자본금은 주식 수 × 액면가보다 많았던 회사 — 이전에 이익으로 소각한 주식 등)' if ta and ca == ta * np_
                       else f" · 발행주식 수 × 액면가 감소분({won(exp)})과 {d - exp:+,}원 다름 — 원문을 직접 확인해 주세요")
                calc('줄어드는 자본금', f"{won(d)}{msg}", '감자 전 자본금 − 감자 후 자본금', d, '원')
                r2 = round((par - np_) / par * 100, 4)
            else:
                calc('줄어드는 자본금', won(d), '감자 전 자본금 − 감자 후 자본금', d, '원'); r2 = None
                held.append('감액 후 액면가: 방법 칸의 글과 표에서 읽지 못함 — 보류')
            r1 = round(d / cb * 100, 4) if cb else None
            rt = p['ratio_text'][0] or p['ratio_text'][1]
            if r1 is not None:
                calc('감자비율(자본금 기준)', f"{H['p'](r1)}{_ratio_check(r1, rt)}", '(감자 전 자본금 − 감자 후 자본금) ÷ 감자 전 자본금 × 100', r1, '%')
            if r2 is not None and r2 != r1:                         # 공시 값은 자본금 기준과 먼저 견주고, 거기서 맞지 않을 때만 액면가 기준과 견준다
                same1 = r1 is not None and '같음' in _ratio_check(r1, rt)
                calc('감자비율(액면가 기준)', f"{H['p'](r2)}{'' if same1 else _ratio_check(r2, rt)}", '(감액 전 액면가 − 감액 후 액면가) ÷ 감액 전 액면가 × 100', r2, '%')
        elif par and typ in merges and ds:
            exp = ds * par
            rs1 = (p.get('ratios') or [None])[0] if typ == 'merge' else None
            prop = cb - cb * Fraction(str(rs1[1])) / Fraction(str(rs1[0])) if rs1 else None       # 자본금을 병합 비율만큼 줄이는 회사(자본금 ≠ 주식 수 × 액면가)
            msg = (' · 줄어드는 주식 수 × 액면가와 같음' if exp == d
                   else f" · 줄어드는 주식 수 × 액면가({won(exp)})와 같음(단주 처리로 생기는 작은 차이 {d - exp:+,}원)" if abs(d - exp) <= 10 * par
                   else ' · 감자 전 자본금을 병합 비율만큼 줄인 값과 같음(자본금이 주식 수 × 액면가와 다른 회사 — 이전에 이익으로 소각한 주식 등)' if prop is not None and abs(d - prop) <= 10 * par
                   else f" · 줄어드는 주식 수 × 액면가({won(exp)})와 {d - exp:+,}원 다름 — 원문을 직접 확인해 주세요")
            calc('줄어드는 자본금', f"{won(d)}{msg}", '감자 전 자본금 − 감자 후 자본금', d, '원')
        elif par and (q is not None or qo is not None) and typ in ('treasury', 'paid', 'free_retire'):
            exp = ((q or 0) + (qo or 0)) * par
            calc('줄어드는 자본금', f"{won(d)}" + (' · 감자 주식 수 × 액면가와 같음' if exp == d else f" · 감자 주식 수 × 액면가({won(exp)})와 {d - exp:+,}원 다름 — 원문을 직접 확인해 주세요"), '감자 전 자본금 − 감자 후 자본금', d, '원')
        else:
            calc('줄어드는 자본금', won(d), '감자 전 자본금 − 감자 후 자본금', d, '원')
    close = mkt.get('close') if mkt else None
    when = f"{mkt['date']} 종가 {close:,.0f}원(공시 전 마지막 거래일)" if close else None
    if close and q and typ in ('treasury', 'paid', 'free_retire'):
        v = q * close
        calc('감자 주식의 시가 환산', f"{won(v)} — {mkt['date']} 종가 {close:,.0f}원 기준(공시 전 마지막 거래일)", '감자 보통주 수 × 공시 전 마지막 거래일 종가', v, '원')
        if mkt.get('market_cap'):
            r = H['pct'](v, mkt['market_cap']); calc('감자 주식 시가 환산 ÷ 시가총액', H['p'](r), '위 금액 ÷ 공시 전 마지막 거래일 시가총액 × 100', r, '%')
    # ── 방식별: 주주의 주식 수·1주 값·회사 밖으로 나가는 돈 (J9: 방향 판단 없이 산술만. 실제 거래 재개 가격은 다를 수 있음을 식에 적는다)
    if typ == 'merge':
        rs = p.get('ratios') or []
        if rs:
            ka, kb = Fraction(str(rs[0][0])), Fraction(str(rs[0][1])); k = ka / kb
            calc('병합 배수', f"{float(k):.6g}배 — {rs[0][0]:g}주를 {rs[0][1]:g}주로", '방법 칸의 병합 비율(병합 전 주식 수 ÷ 병합 뒤 주식 수)', round(float(k), 6), '배')
            if sb and sa is not None:
                exp = int(sb * kb / ka)
                calc('병합 뒤 주식 수 대조(보통주)', f"{exp:,}주" + (' · 공시의 감자 후 값과 같음' if exp == sa else f" · 공시의 감자 후 값 {sa:,}주와 {sa - exp:+,}주 차이(주주별 단주 처리·감자기준일까지의 주식 수 변동 등)"),
                     '감자 전 발행주식 수 ÷ 병합 배수 (1주 미만 버림)', exp, '주')
        elif sb and sa:
            k = Fraction(sb, sa)
            calc('병합 배수', f"{float(k):.6g}배 — 방법 칸에서 비율을 읽지 못해 주식 수로 계산", '감자 전 발행주식 수 ÷ 감자 후 발행주식 수', round(float(k), 6), '배')
        else:
            k = None; held.append('병합 배수: 방법 칸과 표에서 읽지 못함 — 보류')
        if k:
            new = Fraction(100) / k; whole = new.numerator // new.denominator; frac = new - whole
            calc('100주를 가진 주주의 병합 뒤 주식 수', f"{whole:,}주" + (f" + 1주에 못 미치는 단주 {float(frac):.4g}주" if frac else ' (단주 없음)'), '100주 ÷ 병합 배수 — 1주 미만은 단주로 따로 처리', whole, '주')
            if close:
                tp = close * float(k)
                calc('병합 뒤 1주의 산술 값', f"{tp:,.0f}원 — {when} × {float(k):.6g}", '종가 × 병합 배수. 주식 수만 줄고 회사 전체 값이 그대로일 때의 산술 값이며, 실제 거래 재개 가격은 다를 수 있음', round(tp, 2), '원')
        if p.get('split'):
            notes.append('방법 칸에 주식분할도 함께 적혀 있습니다. 위 숫자는 감자(병합) 부분만 계산한 것이고, 분할 뒤의 주식 수·액면가는 따로 확인해 주세요.')
        notes.append('주식 병합 방식의 무상감자입니다. 모든 주주의 주식이 같은 비율로 줄어 지분율은 그대로이고(단주 제외), 회사 밖으로 나가는 돈은 없습니다.')
    elif typ in ('merge_diff', 'mixed'):
        rs = p.get('ratios') or []
        if rs:
            fact('방법 칸에 적힌 병합 비율', ' · '.join(f"{a:g}주→{b:g}주" for a, b in rs))
        if ds and ta:
            calc('전체 발행주식 수 배수', f"{tb / ta:.6g}배 ({tb:,}주 → {ta:,}주)", '감자 전 발행주식 수 ÷ 감자 후 발행주식 수 (보통주 + 기타주)', round(tb / ta, 6), '배')
        if p.get('pay'):
            fact('1주당 유상소각대금', f"{p['pay']:,}원", p['pay'], '원', '방법 칸 또는 참고사항의 글')
            held.append('주주에게 지급되는 돈: 유상으로 소각되는 주식 수를 표에서 따로 가를 수 없어 계산하지 않음 — 방법 칸 원문을 확인해 주세요')
        held.append(('표의 주식 수가 방법 칸의 병합 비율 한 가지와 맞지 않는 감자(일부 주식만 병합·주주마다 다른 비율·여러 차례로 나눈 감자)' if typ == 'merge_diff' else '여러 방식을 함께 쓰는 감자')
                    + '라 1주의 산술 값·주주별 주식 수는 계산하지 않음 — 방법 칸 원문에서 내 주식이 어느 쪽인지 확인해 주세요')
    elif typ == 'par_cut':
        notes.append('액면 감액 방식의 무상감자입니다. 주식 수와 지분율이 그대로이고 회사 밖으로 나가는 돈이 없어, 주식 수로 나누는 1주의 산술 값도 바뀌지 않습니다. 자본금만 줄어듭니다.')
    elif typ == 'free_retire':
        if ds and ta:
            k = Fraction(tb, ta)
            calc('소각되지 않는 주식의 몫 배수', f"{float(k):.6f}배 ({tb:,}주 → {ta:,}주)", '감자 전 발행주식 수 ÷ 감자 후 발행주식 수 — 남는 주식 1주가 회사에서 차지하는 몫이 커지는 배수', round(float(k), 6), '배')
            if close:
                tp = close * float(k)
                calc('남는 주식 1주의 산술 값', f"{tp:,.0f}원 — {when} × {float(k):.6f}", '종가 × 위 배수. 회사 전체 값이 그대로일 때의 산술 값이며 실제 주가는 다를 수 있음. 소각되는 주식이 회사가 가진 자기주식이면 해당 없음(자기주식은 원래 주주 몫 계산에서 빠져 있음)', round(tp, 2), '원')
        notes.append('무상 소각 방식의 감자입니다. 돈을 주지 않고 일부 주식을 없애는 것이라 회사 밖으로 나가는 돈은 없습니다. 누구의 주식이 소각되는지는 방법 칸 원문을 확인해 주세요.')
    elif typ == 'paid':
        pay = p.get('pay'); qa = (q or 0) + (qo or 0)
        if not pay or not qa:
            held.append('1주당 유상소각대금: 방법 칸·참고사항에서 읽지 못함 — 주주에게 지급되는 돈은 계산하지 않음')
        else:
            tot = qa * pay
            fact('1주당 유상소각대금', f'{pay:,}원', pay, '원', '방법 칸 또는 참고사항의 글')
            calc('주주에게 지급되는 돈(회사 밖으로 나가는 돈)', won(tot), '감자 주식 수 × 1주당 유상소각대금', tot, '원')
            if par:
                g = qa * (par - pay)
                calc('감자차익 또는 감자차손', f"{'감자차익' if g > 0 else '감자차손' if g < 0 else '차이 없음'} {won(abs(g))}", '감자 주식 수 × (액면가 − 1주당 유상소각대금). 액면가보다 많이 주면 감자차손', g, '원')
            if close:
                r = round((pay / close - 1) * 100, 2)
                calc('유상소각대금 ÷ 종가', f"{H['p'](r)} — {when}", '(1주당 유상소각대금 ÷ 종가 − 1) × 100', r, '%')
                cap, ms = mkt.get('market_cap'), mkt.get('shares')
                if cap:
                    r = H['pct'](tot, cap); calc('지급되는 돈 ÷ 시가총액', H['p'](r), '지급 총액 ÷ 공시 전 마지막 거래일 시가총액 × 100', r, '%')
                if cap and ms and ms > qa and cap > tot:
                    tp = (cap - tot) / (ms - qa)
                    calc('감자 뒤 1주의 산술 값', f"{tp:,.0f}원", '(시가총액 − 지급 총액) ÷ (상장 주식 수 − 감자 주식 수). 회사 값이 나간 돈만큼만 줄 때의 산술 값이며 실제 주가는 다를 수 있음', round(tp, 2), '원')
        notes.append('유상 소각 방식의 감자입니다. 회사가 주주에게 돈을 주고 주식을 없애므로 회사의 자본총계가 지급한 돈만큼 줄어듭니다. 주주별 소각 비율은 방법 칸 원문을 확인해 주세요.')
    elif typ == 'treasury':
        notes.append('자기주식 소각 방식의 감자입니다. 회사가 이미 가진 자기주식을 없애는 것이라 회사 밖으로 나가는 돈이 없고, 주주가 가진 주식 수도 그대로입니다. 발행주식 총수와 자본금만 줄어듭니다(자기주식은 원래 주당 지표 계산에서 빠져 있음).')
    else:
        held.append('방법 칸의 글로 방식을 가르지 못해 방식별 계산은 하지 않음 — 주식 수·자본금 대조까지')
    # ── 무상감자 공통: 자본금만 줄고 자본총계는 그대로 → 자본잠식을 가르는 선이 내려간다(자본총계는 이 공시에 없어 잠식률 자체는 계산하지 않음)
    if typ in ('merge', 'merge_diff', 'mixed', 'par_cut', 'free_retire') and d and d > 0 and ca is not None and 'paid' not in (p.get('kinds') or []):
        calc('자본잠식을 가르는 선(자본총계가 이 값보다 작으면 자본잠식)', f"{won(cb)} → {won(ca)}", '자본잠식률 = (자본금 − 자본총계) ÷ 자본금 × 100. 무상감자는 자본총계를 바꾸지 않고 자본금만 줄임', ca, '원')
        calc('자본잠식률 50%가 되는 자본총계', f"{won(cb // 2)} → {won(ca // 2)}", '자본금 × 50% (감자 전 → 감자 후)', ca // 2, '원')
        notes.append(f"줄어드는 자본금 {won(d)}은 회사 밖으로 나가지 않고 감자차익(자본잉여금)이 되거나 결손금을 메우는 데 쓰입니다. 자본총계는 그대로입니다.")
        held.append('자본잠식률: 이 회사의 자본총계가 감자 결정 공시에 없어 계산하지 않음(정기보고서·손익구조 변경 공시의 자본총계와 견주는 것은 다음 단계)')
    if p.get('fraction_text') and typ in merges:
        fact('단주 처리(원문 그대로)', p['fraction_text'])
    for nm, key in (('감자기준일', 'base_date'), ('주주총회 예정일', 'agm'), ('신주(변경) 상장 예정일', 'relist'), ('이사회 결의일', 'decided')):
        if p.get(key):
            fact(nm, p[key])
    if p.get('halt') and p['halt'][0]:
        fact('매매거래 정지 예정 기간', f"{p['halt'][0]} ~ {p['halt'][1] or '미정'}")
    d8 = lambda v: v or '—'
    _generic_diff(f, calc, notes, H, [
        ('감자 주식 수(보통주)', lambda x: x.get('qty'), n), ('감자 주식 수(기타주)', lambda x: x.get('qty_other'), n),
        ('감자 전 주식 수(보통주)', lambda x: (x.get('shares') or {}).get('before'), n), ('감자 후 주식 수(보통주)', lambda x: (x.get('shares') or {}).get('after'), n),
        ('감자 후 자본금', lambda x: (x.get('capital') or {}).get('after'), lambda v: n(v, '원')),
        ('1주당 유상소각대금', lambda x: x.get('pay'), lambda v: n(v, '원')),
        ('감자비율(보통주, 공시)', lambda x: (x.get('ratio_text') or [None])[0], d8), ('감자기준일', lambda x: x.get('base_date'), d8),
        ('주주총회 예정일', lambda x: x.get('agm'), d8), ('신주(변경) 상장 예정일', lambda x: x.get('relist'), d8),
        ('매매거래 정지 시작일', lambda x: (x.get('halt') or [None])[0], d8), ('감자 방법', lambda x: x.get('method'), d8)])


def _pl_change(f, fact, calc, held, T, notes, H):
    p = f['parsed']; rows = p.get('rows') or {}; unit = p.get('unit')
    if not rows:
        held.append('손익구조 변동 표: 원문에서 읽지 못함 — 보류'); return
    per = p.get('period') or {}
    when = f"{per['start'][0]}~{per['end'][0]}" if per.get('start') and per.get('end') and per['start'][0] else '당해 사업연도'
    basis = p.get('basis') or '재무제표 종류 미기재'
    TR = []
    for key, name in PL_NAME.items():
        r = rows.get(key)
        if not r or r.get('cur') is None:
            held.append(f'{name}: 원문 칸에서 읽지 못함 — 보류'); continue
        fact(f"{name} ({when}, {basis})", H['won'](r['cur']), r['cur'], '원', f"공시 표 값 × 표 단위({unit})")
        prev = r.get('prev')
        if prev is not None:
            d = r['cur'] - prev
            ds = r.get('diff_stated')
            um = UNIT.get(unit or '', 1)                                   # J3: 표 단위 1~2칸 차이는 회사가 원 단위 값으로 뺀 뒤 반올림한 것으로 설명됨
            chk = ('' if ds is None else ' · 공시 값과 같음' if ds == d
                   else f" · 공시 값과 같음(표 단위 {unit} 반올림 차이)" if abs(ds - d) <= 2 * um
                   else f" · 공시에 적힌 증감금액은 {ds // um:,}{unit}, 다시 계산하면 {d // um:,}{unit} — {abs(d - ds) // um:,}{unit} 다름. 원문 표를 직접 확인해 주세요(반올림으로 설명되지 않음)")
            calc(f"{name} 증감금액", f"{H['won'](d)}{chk}", '당해 − 직전 (공시 표의 값으로 다시 계산)', d, '원')
            if prev > 0:                                                   # J1
                mine = round(d / prev * 100, 2)
                calc(f"{name} 증감률", f"{H['p'](mine)}{H['check'](r['cur'], prev, mine, r.get('rate_stated'), unit)}", '(당해 − 직전) ÷ 직전 × 100 (공시 표의 값으로 다시 계산)', mine, '%')
            else:
                st = r.get('rate_stated')
                held.append(f"{name} 증감률: 직전 값이 0 이하({H['won'](prev)})라 다시 계산하지 않음" + (f" — 공시에 적힌 값은 {st:g}%" if st is not None else ''))
            tn = _turn(r['cur'], prev)
            if tn:
                same = '' if not r.get('turn') else ' · 공시 표시와 같음' if r['turn'].replace(' ', '') in tn.replace(' ', '') else f" · 공시 표시는 「{r['turn']}」"
                calc(f"{name} 흑자·적자 전환", f"{tn}{same}", '당해와 직전 값의 부호로 봄', None, None)
            elif r.get('turn'):
                notes.append(f"{name}: 공시의 흑자·적자 전환 칸에 「{r['turn']}」이라고 적혀 있으나 표의 부호로는 전환이 아닙니다 — 원문을 확인해 주세요.")
        TR.append([name, H['won'](r['cur']), H['won'](prev), H['won'](r.get('diff_stated')),
                   H['p'](r['rate_stated'], 1) if r.get('rate_stated') is not None else (r.get('rate_text') or '—'), r.get('turn') or '—'])
    rv, op = rows.get('revenue') or {}, rows.get('op') or {}
    for lbl, kk in (('당해', 'cur'), ('직전', 'prev')):
        if rv.get(kk) and op.get(kk) is not None:
            m = H['pct'](op[kk], rv[kk])
            calc(f'영업이익률({lbl})', H['p'](m), '영업이익 ÷ 매출액 × 100 (공시 표 값)', m, '%')
    if TR:
        T.append({'title': f"매출액·손익구조 변동 — {basis}, 원문 표 단위 {unit}", 'cols': ['구분', '당해', '직전', '증감금액(공시)', '증감비율(공시)', '흑자·적자 전환(공시)'], 'rows': TR,
                  'hint': '회사가 감사 전에 알린 결산 값입니다. 감사보고서 제출 뒤 달라질 수 있습니다.'})
    _vs_prelim(f, rows, calc, notes, T, H)                            # v0.38 T2-4f
    bs = p.get('bs') or {}; bu = p.get('bs_unit')
    BR = []
    for key, name in BS_NAME.items():
        b = bs.get(key)
        if b and b.get('cur') is not None:
            fact(f"{name} (당해 말, {basis})", H['won'](b['cur']), b['cur'], '원', f"공시 표 값 × 표 단위({bu})")
            BR.append([name, H['won'](b['cur']), H['won'](b.get('prev'))])
    A, L, E, C = (bs.get(x) or {} for x in ('assets', 'liab', 'equity', 'capital'))
    for lbl, kk in (('당해 말', 'cur'), ('직전 말', 'prev')):
        a, l, e, c = A.get(kk), L.get(kk), E.get(kk), C.get(kk)
        if a is not None and l is not None and e is not None and a != l + e:
            gap = a - l - e
            tol = 2 * UNIT.get(bu or '', 1)
            if abs(gap) > tol:
                notes.append(f"{lbl} 자산총계가 부채총계 + 자본총계와 {H['won'](gap)} 다릅니다 — 원문 표를 직접 확인해 주세요.")
        if l is not None and e:
            if e > 0:
                r_ = H['pct'](l, e); calc(f'부채비율({lbl})', H['p'](r_), '부채총계 ÷ 자본총계 × 100 (공시 표 값)', r_, '%')
            else:
                held.append(f'부채비율({lbl}): 자본총계가 0 이하라 계산하지 않음')
        if e is not None and c:
            st = (bs.get('eq_cap_stated') or {}).get(kk)
            r_ = round(e / c * 100, 2)
            if st is not None:
                g = r_ - st
                chk = ' · 공시 값과 같음' if abs(g) <= 0.06 else f' · 공시 값 {st:,}%와 같음(공시는 소수 1자리로 반올림)' if abs(g) <= 0.06 + 0.05 else f' · 공시 값 {st:,}%와 {g:+.2f}%p 다름 — 원문 표를 직접 확인해 주세요'
                calc(f'자본총계 ÷ 자본금({lbl})', f"{H['p'](r_)}{chk}", '자본총계 ÷ 자본금 × 100 (공시 표 값)', r_, '%')
            if e < c:
                im = round((c - e) / c * 100, 2); st2 = (bs.get('impair_stated') or {}).get(kk)
                calc(f'자본잠식률({lbl})', f"{H['p'](im)}" + (f' · 공시 값 {st2:g}%' if st2 is not None else ''), '(자본금 − 자본총계) ÷ 자본금 × 100 (공시 표 값)', im, '%')
    if BR:
        T.append({'title': f"재무현황 — {basis}, 원문 표 단위 {bu}", 'cols': ['구분', '당해 말', '직전 말'], 'rows': BR})
    sr = p.get('separate_revenue') or {}
    if sr.get('cur') is not None:
        fact('별도 재무제표 매출액(당해)', H['won'](sr['cur']), sr['cur'], '원', '지배회사의 추가공시사항 표 값')
    if p.get('large'):
        fact('대규모법인 여부(공시 기준 15% 또는 30%)', p['large'])
    if p.get('reasons'):
        fact('회사가 적은 변동 주요원인(원문 그대로)', ' / '.join(p['reasons'])[:400])
    _correction_diff(f, calc, notes, H)
    notes.append('회사가 감사 전에 알린 결산 값입니다. ' + ('같은 결산기간의 앞선 잠정실적과 견준 값을 함께 보입니다.' if f.get('prelim') else
                 '같은 결산기간·같은 재무제표 종류의 앞선 잠정실적이 사본에 없어 견주지 않았습니다.'))      # v0.38 T2-4f


def _correction_diff(f, calc, notes, H):
    """결정 5·J2: 바로 앞 공시와 달라진 칸을 숫자로, 이유는 원문 정정사유 그대로."""
    p = f['parsed']
    if p.get('corrects') or f.get('history'):
        notes.append(f"정정 공시입니다(원래 공시 {p.get('corrects') or '날짜 미기재'}). 이 공시의 본문 값을 썼습니다.")
    if not f.get('history'):
        return
    old = f['history'][-1]; q = old['parsed']
    ch = []

    def show(a, b):                                    # 억 단위로 같아 보이는 작은 차이는 원 단위로 적는다
        return (H['won'](a), H['won'](b)) if H['won'](a) != H['won'](b) else (f'{a:,}원', f'{b:,}원')
    for key, name in PL_NAME.items():
        for kk, lbl in (('cur', '당해'), ('prev', '직전')):
            a, b = (q.get('rows') or {}).get(key, {}).get(kk), (p.get('rows') or {}).get(key, {}).get(kk)
            if a is not None and b is not None and a != b:
                sa, sb = show(a, b)
                ch.append(f"{name}({lbl}) {sa} → {sb} ({H['won'](b - a) if b - a < 0 else '+' + H['won'](b - a)}" + (f", {(b - a) / abs(a) * 100:+.2f}%" if a else '') + ')')
    for key, name in BS_NAME.items():
        a, b = (q.get('bs') or {}).get(key, {}).get('cur'), (p.get('bs') or {}).get(key, {}).get('cur')
        if a is not None and b is not None and a != b:
            sa, sb = show(a, b)
            ch.append(f"{name}(당해 말) {sa} → {sb} ({H['won'](b - a) if b - a < 0 else '+' + H['won'](b - a)})")
    why = p.get('correction_reason')
    if ch:
        calc(f"앞선 공시({old['rcept_dt']}, 접수번호 {old['rcept_no']})와 달라진 숫자 {len(ch)}곳", ' / '.join(ch), '이 공시의 값 − 앞선 공시의 값 (두 원문 표를 견줌)')
    else:
        notes.append(f"앞선 공시({old['rcept_dt']})와 매출·이익·재무현황 숫자는 같습니다(숫자 밖의 칸이 정정된 공시).")
    if why:
        notes.append(f"회사가 적은 정정사유(원문 그대로): 「{why}」")


from . import filing3  # noqa: E402,F401  — 유상증자 등 나머지 종류를 등록한다(이 파일의 함수가 모두 정의된 뒤에 불러야 함)
from . import filing4  # noqa: E402,F401  — v0.39 T3-2 공급계약·타법인 주식(2등급)을 등록한다
