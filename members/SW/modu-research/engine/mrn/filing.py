"""v0.38 T1 공시 1건을 숫자로 — 1등급 4종(주식 소각 · 자기주식 취득 · 현금배당 · 영업(잠정)실적).

원칙(PM 확정 2026-11-11)
- 원문은 mrn.dartdocs 의 해시 고정 사본에서만 읽는다(받은 그대로). AI 모델 호출 0회. 숫자는 원문 칸 값 그대로.
- 읽지 못한 칸은 지어내지 않고 None → 노드가 보류로 표시.
- 호재·악재 같은 방향 판단은 하지 않는다. 계산은 「무엇을 무엇으로 나눴는지」를 문장에 적는 기계적 계산뿐이다.
- 규칙 filing-calc-v1.
"""
import re
from .promise import tokens, _num, _date, _find, _all, _pair, _span, _one, _correction, parse_decision, parse_retire, UNIT

from . import filing2 as F2                                   # v0.38 T2-3 1등급 나머지 종류

RULE = 'filing-calc-v1'
MONEY_UNIT = {**UNIT, '조원': 1_000_000_000_000}
KINDS = ('retire', 'buyback_decision', 'dividend', 'prelim') + F2.KINDS2
KIND_LABEL = {'retire': '주식 소각 결정', 'buyback_decision': '자기주식 취득 결정', 'dividend': '현금·현물 배당 결정', 'prelim': '영업(잠정)실적', **F2.KIND_LABEL2}
_DEC = re.compile(r'^-?\d+(\.\d+)?$')


def _f(t):
    t = (t or '').replace(',', '').replace(' ', '')
    return float(t) if _DEC.match(t) else None


def _pairf(T, pat):
    """_pair 와 같되 소수도 읽는다(1,139.61원 같은 배당금)."""
    for i in _all(T, pat):
        seg = T[i + 1:i + 6]; a = b = None; shape = False
        for j, t in enumerate(seg[:-1]):
            u = t.replace(' ', '')
            if u.startswith('보통주식') and not shape:
                a = _f(seg[j + 1]); shape = True
            elif (u.startswith('종류주식') or u.startswith('기타주식')) and b is None:
                b = _f(seg[j + 1])
        if shape:
            return tuple(int(x) if x is not None and x == int(x) else x for x in (a, b))
    return None, None


def parse_dividend(doc):
    T = tokens(doc)
    dps, dps_o = _pairf(T, r'^3\.1주당배당금')
    yld = [None, None]
    for i in _all(T, r'^4\.시가배당(률|율)'):
        seg = T[i + 1:i + 6]
        for j, t in enumerate(seg[:-1]):
            s = t.replace(' ', '')
            if s.startswith('보통주식') and yld[0] is None:
                yld[0] = _f(seg[j + 1])
            elif (s.startswith('종류주식') or s.startswith('기타주식')) and yld[1] is None:
                yld[1] = _f(seg[j + 1])
        break
    return {'div_class': _one(T, r'^1\.배당구분'), 'div_type': _one(T, r'^2\.배당종류'), 'dps': dps, 'dps_other': dps_o,
            'yield': yld[0], 'yield_other': yld[1], 'total': _one(T, r'^5\.배당금총액', _num), 'record_date': _one(T, r'^6\.배당기준일', _date),
            'pay_date': _one(T, r'^7\.배당금지급예정일자', _date), 'decided': _one(T, r'^10\.이사회결의일', _date), 'corrects': correction_of(T)}


PRELIM_ROWS = (('revenue', '매출액'), ('op', '영업이익'), ('pretax', '법인세비용차감전계속사업이익'), ('net', '당기순이익'), ('net_owner', '지배기업소유주지분순이익'))


def correction_of(T):
    """정정 공시면 원래 공시의 제출일. 주요사항보고서 서식(최초제출일)과 거래소 공시 서식(정정관련 공시서류제출일) 둘 다."""
    for pat in (r'정정대상공시서류의최초제출일', r'정정관련공시서류제출일'):
        i = _find(T, pat)
        if i >= 0:
            return next((d for d in (_date(t) for t in T[i:i + 3]) if d), None)
    return None


def _money(t, mult):
    """표의 값(소수 가능) × 표의 단위 → 원 단위 정수. 「조원」 표는 소수 둘째 자리까지라 반올림된 값임을 단위와 함께 남긴다."""
    from decimal import Decimal, InvalidOperation
    t = (t or '').replace(',', '').replace(' ', '')
    if not mult or not re.fullmatch(r'-?\d+(\.\d+)?', t):
        return None
    try:
        return int(Decimal(t) * mult)
    except InvalidOperation:
        return None


def parse_prelim(doc):
    """연결(또는 별도) 영업(잠정)실적 표. 금액은 표의 단위를 곱해 원 단위 정수로. 정정 공시는 앞의 정정표가 아니라 본문 표를 읽는다."""
    T = tokens(doc)
    out = {'period': {}, 'unit': None, 'rows': {}, 'corrects': correction_of(T)}
    for key, lab in (('cur', '당기실적'), ('prev', '전기실적'), ('yoy', '전년동기실적'), ('ytd', '당기누계실적'), ('ytd_prev', '전년동기누적실적')):
        i = _find(T, '^' + lab + '$')
        if i >= 0 and i + 3 < len(T) and T[i + 2] == '~':
            out['period'][key] = (_date(T[i + 1]), _date(T[i + 3]))
    h = next((k for k in range(len(T) - 1) if T[k].replace(' ', '') == '구분' and T[k + 1].replace(' ', '') == '당기실적'), -1)   # 본문 표의 머리
    kq = False
    if h < 0:                                                   # 코스닥 서식: 「구분(단위 : 백만원, %)」 | 당기실적 | … | 전기대비증감액(증감율)
        h = next((k for k in range(len(T) - 1) if T[k].replace(' ', '').startswith('구분(단위') and T[k + 1].replace(' ', '') == '당기실적'), -1)
        kq = h >= 0
    if h < 0:
        return out
    m = next((re.search(r'단위:?([가-힣]*원)', T[k].replace(' ', '')) for k in range(h, max(h - 4, -1), -1) if '단위' in T[k].replace(' ', '')), None)
    mult = MONEY_UNIT.get(m.group(1)) if m else None
    out['unit'] = m.group(1) if m else None
    first = min([k for k in (_find(T, '^' + lab + '$', h) for _, lab in PRELIM_ROWS) if k > h] or [len(T)])
    wide = any(T[k].replace(' ', '') == '흑자적자전환여부' for k in range(h, first))       # 새 서식 7칸(흑자·적자 전환 칸 둘) / 옛 서식 5칸
    n = 7 if (wide or kq) else 5
    out['layout'] = 'kq' if kq else n
    labs = [T[k].strip()[1:-1].strip() for k in range(h, first) if T[k].strip().startswith('(') and T[k].strip().endswith(')')]
    labs = [None if x in ('-', '') else x.replace("'", '') for x in labs]
    if len(labs) >= 3:
        out['labels'] = {'cur': labs[0], 'prev': labs[1], 'yoy': labs[2]}
    joined = ' '.join(x for x in labs if x)
    per = out['period'].get('cur')
    days = None
    if per and per[0] and per[1]:
        from datetime import date
        days = (date.fromisoformat(per[1]) - date.fromisoformat(per[0])).days
    out['span'] = ('month' if (days is not None and days < 40) or (days is None and '월' in joined and not re.search(r'분기|Q', joined))
                   else 'quarter' if (days is not None and days < 100) or re.search(r'분기|Q', joined) else 'other')
    money = lambda t: _money(t, mult)
    for key, lab in PRELIM_ROWS:
        i = _find(T, '^' + lab + '$', h)
        if i < 0 or i + 1 >= len(T) or T[i + 1].replace(' ', '') != '당해실적':
            continue
        v = T[i + 2:i + 2 + n]
        if len(v) < n:
            continue
        if kq:                                                  # 당기 | 전기 | 증감액 | (증감율) | 전년동기 | 증감액 | (증감율)
            pc = lambda t: _f(re.sub(r'[()%+\s]', '', t or '')) if re.search(r'\d', t or '') else None
            row = {'cur': money(v[0]), 'prev': money(v[1]), 'qoq_stated': pc(v[3]), 'qoq_turn': None if pc(v[3]) is not None or v[3].strip() in ('-', '') else v[3].strip('()'),
                   'yoy_base': money(v[4]), 'yoy_stated': pc(v[6]), 'yoy_turn': None if pc(v[6]) is not None or v[6].strip() in ('-', '') else v[6].strip('()')}
        elif wide:
            row = {'cur': money(v[0]), 'prev': money(v[1]), 'qoq_stated': _f(v[2]), 'qoq_turn': v[3] if v[3] != '-' else None,
                   'yoy_base': money(v[4]), 'yoy_stated': _f(v[5]), 'yoy_turn': v[6] if v[6] != '-' else None}
        else:
            row = {'cur': money(v[0]), 'prev': money(v[1]), 'qoq_stated': _f(v[2]), 'qoq_turn': None, 'yoy_base': money(v[3]), 'yoy_stated': _f(v[4]), 'yoy_turn': None}
        j = i + 2 + n
        if j < len(T) and T[j].replace(' ', '') == '누계실적':
            w = T[j + 1:j + 1 + n]
            if kq and len(w) >= 6:                              # 누계: 당기 | - | - | 전년동기 | 증감액 | (증감율)
                row.update(ytd=money(w[0]), ytd_prev=money(w[3]), ytd_yoy_stated=_f(re.sub(r'[()%+\s]', '', w[5])) if re.search(r'\d', w[5]) else None)
            elif not kq and len(w) >= n:
                row.update(ytd=money(w[0]), ytd_prev=money(w[4 if wide else 3]), ytd_yoy_stated=_f(w[5 if wide else 4]))
        out['rows'][key] = row
    out['money_empty'] = bool(out['rows']) and all(r.get('cur') is None for r in out['rows'].values())   # 금액 칸이 모두 「-」(예: 월간 판매 대수만 알린 공시)
    out['units_table'] = any(t.replace(' ', '').startswith('구분(단위:대') for t in T)
    return out


def _norm_shares(doc):
    """정정 공시 서식의 「/보통주식(주)」·「/종류주식(주)」를 본문 서식과 같게."""
    return doc.replace('/보통주식', '보통주식').replace('/종류주식', '종류주식').replace('/기타주식', '기타주식')


def _dash(T, pat):
    """라벨 다음 「보통주식 | -」처럼 칸이 「-」로 적혀 있으면 True(읽지 못한 것이 아니라 해당 없음)."""
    for i in _all(T, pat):
        seg = T[i + 1:i + 6]
        for j, t in enumerate(seg[:-1]):
            if t.replace(' ', '').startswith('보통주식'):
                return seg[j + 1].strip() == '-'
        if seg and seg[0].strip() == '-':
            return True
    return False


def parse_retire2(doc):
    doc = _norm_shares(doc); T = tokens(doc)
    out = parse_retire(doc)
    _, out['shares_total_other'] = _pair(T, r'^2\.발행주식총수')
    out['qty_dash'] = _dash(T, r'^1\.소각할주식의종류와수')
    return out


def parse_decision2(doc):
    doc = _norm_shares(doc); T = tokens(doc)
    out = parse_decision(doc)
    out['qty_dash'] = _dash(T, r'^1\.취득예정주식'); out['amount_dash'] = _dash(T, r'^2\.취득예정금액')
    return out


PARSERS = {'retire': parse_retire2, 'buyback_decision': parse_decision2, 'dividend': parse_dividend, 'prelim': parse_prelim, **F2.PARSERS2}


def parse(kind, doc):
    if kind not in PARSERS:
        raise ValueError(f'{kind}: 아직 계산하는 공시 종류가 아니에요.')
    return PARSERS[kind](doc)


# ---------------------------------------------------------------- 계산 (방향 판단 없음)
def _pct(a, b):
    return None if a is None or not b else round(a / b * 100, 10)


def stated_check(cur, base, mine, stated, unit):
    """다시 계산한 증감률(mine)과 공시 값(stated)을 견준 문구. 같음 / 반올림으로 설명됨 / 다름(원문 확인).
    반올림 한도 = 공시 값의 자릿수 반올림 + 표 값(cur·base)의 표시 단위 반올림이 증감률에 주는 최대 영향."""
    if stated is None or mine is None:
        return ''
    g = mine - stated
    dec = 0 if stated == round(stated) else 1 if round(stated * 10, 6) == round(stated * 10) else 2
    step = MONEY_UNIT.get(unit or '', 1) * (0.01 if unit == '조원' else 1)
    tab = (0.5 * step / abs(base) + (0.5 * step / abs(cur) if cur else 0)) * abs(cur / base) * 100 if base and cur else 0
    if abs(g) <= 0.06:
        return ' · 공시 값과 같음'
    if abs(g) <= 0.5 * 10 ** -dec + 0.01:
        return f' · 공시 값 {stated}%와 같음(공시는 소수 {dec}자리로 반올림)' if dec else f' · 공시 값 {stated:g}%와 같음(공시는 정수로 반올림)'
    if abs(g) <= 1.5 * tab + 0.5 * 10 ** -dec + 0.06:
        return f' · 공시 값 {stated}%와 {g:+.2f}%p 다름 — 표의 표시 단위({unit}) 반올림으로 설명되는 차이'
    return f' · 공시 값 {stated}%와 {g:+.2f}%p 다름 — 원문 표를 직접 확인해 주세요(반올림으로 설명되지 않음)'


def _chg(a, b):
    return None if a is None or b is None or b == 0 or b < 0 else round((a / b - 1) * 100, 2)


def market_before(prices, day):
    """공시일 전날까지 확정된 마지막 거래일의 시세 한 줄과 직전 20거래일 평균 거래대금."""
    rows = [r for r in prices if str(r['trade_date'])[:10] < day]
    if not rows:
        return None
    last = rows[-1]
    tv = [float(r['trade_value']) for r in rows[-20:] if r.get('trade_value') not in (None, '')]
    cap = float(last['market_cap']) if last.get('market_cap') not in (None, '') else None
    close = float(last['close']) if last.get('close') not in (None, '') else None
    return {'date': str(last['trade_date'])[:10], 'close': close, 'market_cap': cap, 'shares': round(cap / close) if cap and close else None,
            'avg_value_20': sum(tv) / len(tv) if len(tv) == 20 else None}


def weekdays(a, b):
    from datetime import date, timedelta
    d0, d1 = date.fromisoformat(a), date.fromisoformat(b)
    n = 0
    while d0 <= d1:
        n += d0.weekday() < 5; d0 += timedelta(days=1)
    return n


def trading_days(a, b):
    """v0.38 T2-5(J27): a~b(양끝 포함) 거래일 수(한국거래소 휴장일 반영)와, 휴장일 표가 없는 해가 끼었으면 그 알림(없으면 빈 글)."""
    from . import tradecal as C
    return C.count(a, b), C.note(a, b).strip().rstrip('.')


def _won(v):
    if v is None:
        return '—'
    a = abs(v)
    if a >= 1e12:
        return f"{v / 1e12:,.2f}조 원"
    if a >= 1e8:
        return f"{v / 1e8:,.0f}억 원"
    return f"{v:,.0f}원"


def _p(x, d=2):
    if x is None:
        return '—'
    if x != 0 and abs(x) < 0.5 * 10 ** -d:
        return f"{'-' if x < 0 else ''}0.{'0' * (d - 1)}1% 미만"
    return f"{x:,.{d}f}%"


def load(ticker, rcept_no, cutoff, root=None):
    """사본에서 공시 1건을 찾아 읽는다(해시 대조). 배당은 같은 회사의 앞선 배당 결정도 함께 읽는다(비교용)."""
    from . import dartdocs as D
    man = D.load_manifest(root)
    d = man['docs'].get(rcept_no)
    if not d:
        raise D.DartDocsError('doc_missing', f'접수번호 {rcept_no} 원문이 사본에 없습니다. 「접수번호로 받기」를 먼저 해 주세요.')
    if d['ticker'] != ticker:
        raise D.DartDocsError('other_company', f"접수번호 {rcept_no}는 {d.get('name') or d['ticker']}의 공시예요.")
    if D.OWN_EXCLUDE.search(d.get('report_nm') or ''):
        raise D.DartDocsError('subsidiary', f"「{d['report_nm']}」은(는) 자회사의 공시라 이 회사의 숫자로 계산하지 않아요.")
    if d['kind'] not in KINDS:
        raise D.DartDocsError('unsupported_kind', f"「{d['report_nm']}」은(는) 아직 계산하는 공시 종류가 아니에요(지금은 {', '.join(KIND_LABEL.values())}).")
    last = (cutoff or '9999')[:10]
    if d['rcept_dt'] > last:
        raise D.DartDocsError('after_cutoff', f"이 공시는 {d['rcept_dt']}에 나왔어요. 기준 날짜({last}) 뒤의 공시라 쓰지 않아요.")
    files, meta = D.open_doc(rcept_no, root, man)
    doc = '\n'.join(t for _, t in files)
    out = {'rcept_no': rcept_no, 'kind': d['kind'], 'kind_label': KIND_LABEL[d['kind']], 'report_nm': d['report_nm'], 'rcept_dt': d['rcept_dt'],
           'url': d['url'], 'sha256': d['sha256'], 'fetched_at': d.get('fetched_at'), 'fetched_how': d.get('added_by') or 'bulk',   # v0.38 T2-4d 출처 표시
           'parsed': parse(d['kind'], doc), 'history': [], 'docs': [{'rcept_no': rcept_no, 'sha256': d['sha256']}]}
    if d['kind'] == 'dividend':
        for h in sorted(({'rcept_no': n, **x} for n, x in man['docs'].items() if x['ticker'] == ticker and x['kind'] == 'dividend' and x['rcept_dt'] <= last), key=lambda x: x['rcept_no']):
            if h['rcept_no'] >= rcept_no or D.OWN_EXCLUDE.search(h.get('report_nm') or ''):
                continue
            hf, _ = D.open_doc(h['rcept_no'], root, man)
            out['history'].append({'rcept_no': h['rcept_no'], 'rcept_dt': h['rcept_dt'], 'url': h['url'], 'report_nm': h['report_nm'], **parse_dividend('\n'.join(t for _, t in hf))})
            out['docs'].append({'rcept_no': h['rcept_no'], 'sha256': h['sha256']})
    if d['kind'] in F2.KINDS2:                                # v0.38 T2-3: 같은 결산의 앞선 공시(정정 전)와 뒤의 정정본
        F2.attach_history(out, man, ticker, last, root, D.open_doc, D.OWN_EXCLUDE)
    if d['kind'] == 'pl_change':                              # v0.38 T2-4f 같은 결산의 앞선 잠정실적과 대조
        F2.attach_prelim(out, man, ticker, last, root, D.open_doc, D.OWN_EXCLUDE)
    return out


def _latest_per_decision(rows):
    """정정 공시가 있으면 같은 결정(이사회결의일·배당기준일·구분)의 마지막 공시만."""
    by = {}
    for r in sorted(rows, key=lambda r: r['rcept_no']):
        by[(r.get('decided'), r.get('record_date'), r.get('div_class'))] = r
    return sorted(by.values(), key=lambda r: r['rcept_no'])


def compute(f, mkt, prices=None, ticker=None, snapshot=None):
    """f = load() 결과, mkt = market_before() 결과(없으면 None). 반환 (findings, held, tables, notes)."""
    k, p, F, held, T, notes = f['kind'], f['parsed'], [], [], [], []
    src = {'title': f"{f['report_nm']} ({f['rcept_dt']})", 'url': f['url']}

    def fact(name, claim, value=None, unit=None, formula=None):
        F.append({'name': name, 'claim': claim, 'kind': 'fact_official', 'value': value, 'unit': unit, 'formula': formula, 'source': src})

    def calc(name, claim, formula, value=None, unit=None):
        F.append({'name': name, 'claim': claim, 'kind': 'derived', 'formula': formula, 'value': value, 'unit': unit})

    def est(name, claim, formula, value=None, unit=None):          # v0.38 T2-3: 추정(시장 대비 확률 등) — 화면에서 「추정·가정」으로 보임
        F.append({'name': name, 'claim': claim, 'kind': 'forecast_model', 'formula': formula, 'value': value, 'unit': unit})

    cap_line = f"{mkt['date']} 시가총액 {_won(mkt['market_cap'])}(공시 전 마지막 거래일, 금융위 시세)" if mkt and mkt.get('market_cap') else None
    if p.get('corrects') and k not in F2.KINDS2:
        notes.append(f"정정 공시입니다(원래 공시 {p['corrects']}). 이 공시의 본문 값을 썼습니다.")

    if k == 'retire':
        q, qo, tot, toto = p.get('qty'), p.get('qty_other'), p.get('shares_total'), p.get('shares_total_other')
        if q is None and qo is None:
            held.append('소각할 주식 수: 원문 표에서 읽지 못함 — 보류')
        else:
            fact('소각할 주식 수', ' · '.join(([f"보통주 {q:,}주"] if q is not None else ['보통주 없음']) + ([f"종류주 {qo:,}주"] if qo else [])), q if q is not None else qo, '주')
        if tot:
            fact('발행주식 총수(보통주, 공시 기준)', f"{tot:,}주" + (f" · 종류주 {toto:,}주" if toto else ''), tot, '주')
        if q is not None and tot:
            r = _pct(q, tot)
            calc('발행주식 대비 소각 비율', f"{_p(r)}", '소각할 보통주 ÷ 공시의 발행주식 총수(보통주) × 100', r, '%')
        if qo and toto:
            r = _pct(qo, toto)
            calc('종류주 발행주식 대비 소각 비율', f"{_p(r)}", '소각할 종류주 ÷ 공시의 발행주식 총수(종류주) × 100', r, '%')
        if q is None and qo:
            notes.append('이 공시는 종류주(우선주 등)만 소각합니다. 시가총액은 보통주 시세라 소각 금액과 견주지 않았습니다.')
        if p.get('amount'):
            fact('소각 예정 금액', _won(p['amount']), p['amount'], '원')
            if cap_line and q:
                r = _pct(p['amount'], mkt['market_cap'])
                calc('소각 예정 금액 ÷ 시가총액', f"{_p(r)} — {cap_line}", '소각 예정 금액 ÷ 공시 전 마지막 거래일 시가총액 × 100', r, '%')
        m = p.get('method') or ''
        if m:
            fact('소각할 주식의 취득 방법', m)
            if re.search(r'기취득|보유|이미', m):
                notes.append('이미 가진 자기주식을 소각하는 경우, 소각 전후 유통 주식 수는 같습니다(자기주식은 원래 주당 지표 계산에서 빠져 있음). 발행주식 총수만 줄어듭니다.')
        if p.get('retire_date'):
            fact('소각 예정일', p['retire_date'])
    elif k == 'buyback_decision':
        q, a, s, e = p.get('qty'), p.get('amount'), p.get('start'), p.get('end')
        qo, ao = p.get('qty_other'), p.get('amount_other')
        if q is not None:
            fact('취득 예정 주식 수(보통주)', f"{q:,}주", q, '주')
        if qo:
            fact('취득 예정 주식 수(종류주)', f"{qo:,}주", qo, '주')
        if a is not None:
            fact('취득 예정 금액(보통주)', _won(a), a, '원')
        if ao:
            fact('취득 예정 금액(종류주)', _won(ao), ao, '원')
        if a is None and q is None and qo:
            notes.append('이 공시는 종류주(우선주 등)만 취득합니다. 시가총액·거래대금은 보통주 시세라 견주지 않았습니다.')
        elif a is None and p.get('amount_dash'):
            held.append('취득 예정 금액: 원문에 금액이 「-」로 적혀 있음(주식 수만 공시) — 금액으로 견주는 계산 없음')
        elif a is None:
            held.append('취득 예정 금액: 원문 표에서 읽지 못함 — 보류')
        td, tdn = trading_days(s, e) if (s and e and e >= s) else (0, '')          # v0.38 T2-5(J27) 거래일(휴장일 반영)
        if s and e:
            fact('취득 예상 기간', f"{s} ~ {e}" + (f" (거래일 {td}일" + (f' — {tdn}' if tdn else '') + ')' if e >= s else ' (원문 그대로 — 종료일이 시작일보다 앞섬)'))
        if p.get('purpose'):
            fact('취득 목적', p['purpose'])
        if cap_line and a is not None:
            r = _pct(a, mkt['market_cap'])
            calc('취득 예정 금액 ÷ 시가총액', f"{_p(r)} — {cap_line}", '취득 예정 금액 ÷ 공시 전 마지막 거래일 시가총액 × 100', r, '%')
        if mkt and mkt.get('shares') and q is not None:
            r = _pct(q, mkt['shares'])
            calc('취득 예정 주식 ÷ 상장 주식 수', f"{_p(r)} (상장 주식 수 {mkt['shares']:,}주 = 시가총액 ÷ 종가, {mkt['date']})",
                 '취득 예정 주식 ÷ (공시 전 마지막 거래일 시가총액 ÷ 종가) × 100', r, '%')
        if a is not None and s and e and td == 0:
            held.append(f'하루 평균 매입 필요 금액: 원문의 취득 기간({s} ~ {e})으로는 거래일 수를 셀 수 없음 — 보류')
        elif a is not None and s and e and mkt and mkt.get('avg_value_20'):
            n = td; per = a / n
            r = _pct(per, mkt['avg_value_20'])
            calc('하루 평균 매입 필요 금액 ÷ 하루 평균 거래대금', f"{_won(per)} ÷ {_won(mkt['avg_value_20'])} = {_p(r)}",
                 '취득 예정 금액 ÷ 취득 기간 거래일 수(한국거래소 휴장일 반영) ÷ 공시 전 20거래일 평균 거래대금 × 100' + (f' — {tdn}' if tdn else ''), r, '%')
        elif a is not None and mkt and not mkt.get('avg_value_20'):
            held.append('하루 평균 거래대금 대비: 공시 전 20거래일 거래대금이 사본에 모자람 — 보류')
    elif k == 'dividend':
        if p.get('dps') is None and p.get('dps_other'):
            fact('1주당 배당금', f"보통주 없음 · 종류주 {p['dps_other']:,}원", p['dps_other'], '원')
            notes.append('이 공시는 종류주(우선주 등)에만 배당합니다. 앞선 배당과의 비교는 보통주끼리만 하므로 하지 않았습니다.')
        elif p.get('dps') is None:
            held.append('1주당 배당금: 원문 표에서 읽지 못함 — 보류')
        else:
            fact('1주당 배당금(보통주)', f"{p['dps']:,}원" + (f" · 종류주 {p['dps_other']:,}원" if p.get('dps_other') else ''), p['dps'], '원')
        if p.get('div_class') or p.get('div_type'):
            fact('배당 구분', ' · '.join(x for x in (p.get('div_class'), p.get('div_type')) if x))
        if p.get('yield') is not None:
            fact('시가배당률(공시)', f"{p['yield']}%", p['yield'], '%', '회사가 공시에 적은 값(기준 가격은 공시 11항의 설명대로)')
        if p.get('total'):
            fact('배당금 총액', _won(p['total']), p['total'], '원')
            if cap_line:
                r = _pct(p['total'], mkt['market_cap'])
                calc('배당금 총액 ÷ 시가총액', f"{_p(r)} — {cap_line}", '배당금 총액 ÷ 공시 전 마지막 거래일 시가총액 × 100 (종류주 배당 포함, 시가배당률과 기준이 다름)', r, '%')
        if p.get('record_date'):
            fact('배당 기준일', p['record_date'])
        hist = _latest_per_decision([h for h in f.get('history') or [] if h.get('dps') is not None
                                     and not (h.get('decided') == p.get('decided') and h.get('record_date') == p.get('record_date'))])
        same = [h for h in hist if h.get('div_class') == p.get('div_class')]
        yr = [x for x in hist if x.get('record_date') and p.get('record_date') and x['record_date'][5:7] == p['record_date'][5:7]
              and int(p['record_date'][:4]) - int(x['record_date'][:4]) == 1]
        if p.get('dps') is not None and same:
            h = same[-1]; c = _chg(p['dps'], h['dps'])
            calc('직전 같은 구분 배당 대비', f"{h['dps']:,}원 → {p['dps']:,}원 ({_p(c)}) — 직전 {p.get('div_class') or ''} 기준일 {h.get('record_date')}",
                 '이번 1주당 배당금 ÷ 직전 같은 구분 배당 결정의 1주당 배당금 − 1 (정정 공시는 마지막 것)', c, '%')
        if p.get('dps') is not None and yr:
            x = yr[-1]; c = _chg(p['dps'], x['dps'])
            other = '' if x.get('div_class') == p.get('div_class') else f" · 구분이 다름({x.get('div_class')} → {p.get('div_class')})"
            calc('1년 전 같은 시기 배당 대비', f"{x['dps']:,}원 → {p['dps']:,}원 ({_p(c)}) — 기준일 {x['record_date']}{other}",
                 '이번 1주당 배당금 ÷ 1년 전 같은 달 기준일 배당 결정의 1주당 배당금 − 1 (구분이 다르면 함께 적음)', c, '%')
        if p.get('dps') is not None and not same and not yr:   # (종류주만 배당이면 비교하지 않음 — 위 안내문)
            held.append('앞선 배당과의 비교: 같은 구분이나 1년 전 같은 시기의 배당 결정이 사본에 없음 — 보류')
        if hist:
            cur = {**p, 'rcept_no': f['rcept_no'], 'url': f['url']}
            T.append({'title': '이 회사의 배당 결정 (사본, 최근 순)', 'cols': ['이사회 결의일', '구분', '기준일', '1주당 배당금(보통주)', '배당금 총액', '원문'],
                      'rows': [[h.get('decided') or '', h.get('div_class') or '', h.get('record_date') or '', (f"{h['dps']:,}원" if h.get('dps') is not None else (f"종류주 {h['dps_other']:,}원" if h.get('dps_other') else '—')), _won(h.get('total')),
                                {'text': h['rcept_no'], 'url': h['url']}] for h in reversed(hist + [cur])],
                      'hint': '정정 공시는 같은 결정의 마지막 공시만 보입니다. 사본에 받은 공시만 셉니다.'})
    elif k == 'prelim':
        rows = p.get('rows') or {}
        if p.get('money_empty'):
            held.append('이 공시는 매출·이익 금액 칸이 모두 비어 있어요' + ('(판매 대수를 알린 공시 — 대수는 아직 계산하지 않음)' if p.get('units_table') else '') + ' — 금액 계산 없음')
        elif not rows:
            held.append('잠정실적 표: 원문에서 읽지 못함 — 보류')
        pc = (p.get('period') or {}).get('cur')
        L = p.get('labels') or {}
        when = f"{pc[0]}~{pc[1]}" if pc and pc[0] else (L.get('cur') or '당기')
        prev_name = {'month': '직전 달', 'quarter': '직전 분기'}.get(p.get('span'), '전기')
        basis = '연결' if '연결' in (f.get('report_nm') or '') else '회사 기준(별도 등 — 원문 4항 확인)'
        lab = {'revenue': '매출액', 'op': '영업이익', 'pretax': '법인세차감전 계속사업이익', 'net': '당기순이익', 'net_owner': '지배기업 소유주 순이익'}
        TR = []
        for key, name in lab.items():
            r = rows.get(key)
            if not r or r.get('cur') is None:
                continue
            fact(f"{name} ({when}, {basis})", _won(r['cur']), r['cur'], '원', f"공시 표 값 × 표 단위({p.get('unit')})")
            for lbl, base, stated in (('전년 동기 대비', r.get('yoy_base'), r.get('yoy_stated')), (f'{prev_name} 대비', r.get('prev'), r.get('qoq_stated'))):
                mine = _chg(r['cur'], base)
                if mine is None:
                    continue
                chk = stated_check(r['cur'], base, mine, stated, p.get('unit'))
                calc(f"{name} {lbl}", f"{_p(mine)}{chk}", f"당기 ÷ {'전년 동기' if lbl.startswith('전년') else prev_name} − 1 (공시 표의 값으로 다시 계산)", mine, '%')
            TR.append([name, _won(r['cur']), _won(r.get('prev')),
                       _p(r['qoq_stated'], 1) if r.get('qoq_stated') is not None else (r.get('qoq_turn') or '—'),
                       _won(r.get('yoy_base')),
                       _p(r['yoy_stated'], 1) if r.get('yoy_stated') is not None else (r.get('yoy_turn') or '—')])
        rv, op = (rows.get('revenue') or {}).get('cur'), (rows.get('op') or {}).get('cur')
        if rv and op is not None:
            m = _pct(op, rv)
            calc('영업이익률(당기)', _p(m), '영업이익 ÷ 매출액 × 100 (공시 표 값)', m, '%')
        if TR:
            hd = lambda k, d: f"{d} ({L[k]})" if L.get(k) else d
            T.append({'title': f"영업(잠정)실적 — {basis}, 원문 표 단위 {p.get('unit')}", 'cols': ['구분', hd('cur', '당기'), hd('prev', prev_name), f'{prev_name} 대비(공시)', hd('yoy', '전년 동기'), '전년 동기 대비(공시)'],
                      'rows': TR, 'hint': '잠정치이며 확정치와 다를 수 있습니다. 「조원」 표는 소수 둘째 자리에서 반올림된 값입니다.'})
        notes.append('잠정실적은 회사가 감사 전에 알린 값입니다. 증권사 전망과의 비교는 다음 단계(v0.38 T2)에서 더합니다.')
    elif k in F2.KINDS2:
        F2.compute(k, f, mkt, fact, calc, held, T, notes, {'won': _won, 'p': _p, 'pct': _pct, 'check': stated_check, 'est': est, 'prices': prices, 'ticker': ticker or f.get('company'), 'snapshot': snapshot})
    return F, held, T, notes
