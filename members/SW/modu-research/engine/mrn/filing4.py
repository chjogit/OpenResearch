"""v0.39 T3-2(J31) 2등급 공시를 공시 숫자로만 — 단일판매·공급계약(체결·해지) · 타법인 주식(취득·처분 / 양수·양도 주요사항보고서).
filing2.py · filing3.py 와 같은 원칙·같은 틀이며, 끝에서 filing2 의 종류 목록에 스스로 등록한다. AI 모델 호출 0회.

판단 기록(번호는 NOTES.md 와 같음)
- J31: 공시에 적힌 비율(매출액·자기자본 대비)은 다시 계산하지 않는다(표본 28/28 일치 — 효과 없음). 대신
  ① 계약기간으로 나눈 1년치(1년 = 365일) ② 정정 공시의 원래 공시일·정정사항 표·새로 들어간 문장·같은 계약의 정정 묶음
  ③ 매출액·자기자본의 기준 연도 ④ 타법인: 취득 전 지분(이미 100% 가진 회사인지) · 풋옵션 등 계약 을 보인다.
- 사용자가 넣는 가정(이익률 등)은 받지 않는다(T4 이후). 시가총액 대비는 넣지 않는다.
- 정정 묶음: 같은 회사·같은 종류·같은 계약상대(타법인은 발행회사)이면서 「정정관련 공시서류제출일」이 다른 공시의 접수일과 이어지면
  한 묶음(정정의 정정도 따라감). 원래 공시가 사본에 없으면 정정사항 표가 바뀐 내용의 근거다.
"""
import re
from datetime import date
from . import filing2 as F2
from .promise import tokens, _num, _date, _all

KINDS = ('supply_contract', 'supply_cancel', 'equity_deal', 'equity_deal_major')
LABELS = {'supply_contract': '단일판매·공급계약 체결', 'supply_cancel': '단일판매·공급계약 해지',
          'equity_deal': '타법인 주식 취득·처분 결정', 'equity_deal_major': '타법인 주식 양수·양도 결정(주요사항보고서)'}
DAYS_PER_YEAR = 365
OLD_CONTRACT_DAYS = 365          # 계약일이 공시일보다 이만큼 앞서면 「이미 맺은 계약」으로 알림
STALE_BASIS_YEARS = 2            # 기준 연도가 공시 연도보다 이만큼 이상 앞서면 알림


def _s(t):
    return re.sub(r'\s+', '', t or '')


def _at(T, pat, start=0, stop=None, n=1):
    """start 이후 처음 나오는 라벨 다음 n칸."""
    for i in _all(T, pat):
        if i >= start and (stop is None or i < stop):
            v = T[i + 1:i + 1 + n]
            return (v[0] if v else None) if n == 1 else v
    return None


def _d(t):
    return None if t is None or _s(t) in ('', '-') else _date(t)


def _fl(t):
    s = _s(t).replace(',', '').replace('%', '')
    return float(s) if re.fullmatch(r'-?\d+(\.\d+)?', s) else None


def _amount(t):
    """금액 칸: 숫자면 int, 「-」면 'dash', 못 읽으면 None."""
    if t is None:
        return None
    return 'dash' if _s(t) == '-' else _num(t)


def _ym(a, b):
    """a~b 의 길이를 「N년 M개월」·「N개월」·「N일」로(a<=b, 날짜 문자열)."""
    x, y = date.fromisoformat(a), date.fromisoformat(b)
    m = (y.year - x.year) * 12 + (y.month - x.month) - (1 if y.day < x.day else 0)
    if m < 1:
        return f'{(y - x).days}일'
    return (f'{m // 12}년' if m >= 12 else '') + (f' {m % 12}개월' if m % 12 else '') if m >= 12 else f'{m}개월'


def _days(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


# ---------------------------------------------------------------- 정정사항 표
def _title_like(t):
    s = _s(t)
    return s.startswith('단일판매') or s.startswith('타법인주식') or s in ('-',)


def _is_label(t):
    s = _s(t)
    if not s or s.startswith('-') or ':' in s or len(s) > 40 or _date(t) or re.fullmatch(r'[\d,.%()\-]+', s):
        return False
    if re.match(r'^[가-하]\.', s) or '상기' in s or re.search(r'(임|함|음|다|예정)\.?$', s):     # 「라. 상기 …임」 같은 문장은 항목이 아님
        return False
    return bool(re.match(r"^'?\d+\.", s) or re.search(r'\(원\)|\(%\)|\(주\)|종료일$|시작일$|일자$|기한$|사유$|여부$|계약명$|세부내용$|계약상대$|구분$|조건등$', s))


def correction_rows(T, b):
    """정정사항 표(본문 앞)를 줄로: [{'item', 'before', 'after', 'reason', 'vals', 'text'}]. 거래소 공시(항목|정정전|정정후)와
    주요사항보고서(항목|정정사유|정정전|정정후) 둘 다. 칸 값은 원문 글자 그대로."""
    h = next((i for i in range(1, b) if _s(T[i]) == '정정후' and _s(T[i - 1]) == '정정전'), -1)
    if h < 0:
        return []
    four = h >= 2 and _s(T[h - 2]) == '정정사유'
    seg = list(T[h + 1:b])
    cut = next((i for i, t in enumerate(seg) if re.match(r'^(주요사항보고서|금융위원회|회사명:)', _s(t))), None)
    if cut is not None:                                       # 주요사항보고서: 정정표 뒤의 표지(회사명·대표이사 …)는 표가 아님
        seg = seg[:cut]
    while seg and _title_like(seg[-1]):
        seg.pop()
    rows, cur = [], None
    for t in seg:
        lab = bool(re.match(r'^\d{1,2}\.\D', _s(t))) and len(_s(t)) <= 40 and ':' not in t if four else _is_label(t)
        if lab:
            cur = {'item': t.strip(), 'vals': []}; rows.append(cur)
        elif cur:
            cur['vals'].append(t.strip())
    out = []
    for r in rows:
        v = r['vals']
        if not v or all(_s(x) == '-' for x in v):
            continue                                          # 「2. 계약내역 | - | -」 같은 묶음 머리
        row = {'item': r['item'], 'vals': v, 'reason': None, 'before': None, 'after': None, 'text': False}
        etc_item = bool(re.search(r'기타투자판단|기타사항', _s(r['item'])))          # 「기타 투자판단 …」은 늘 문구 항목
        if four and (etc_item or len(v) > 4 or any(len(x) > 150 for x in v)):     # 사유·전·후가 여러 줄로 갈라진 문구 항목
            row['reason'] = v[0] if len(v[0]) <= 80 else '(문구)'; row['text'] = True     # 첫 칸이 짧으면 그것이 정정사유
        elif four:
            if len(v) >= 3:
                row['reason'], row['before'], row['after'] = ' '.join(v[:-2]), v[-2], v[-1]
            else:
                row['reason'] = ' '.join(v); row['text'] = True
        elif etc_item or len(v[0]) > 60 or (len(v) > 1 and len(v[1]) > 60):
            row['text'] = True
        else:
            short = [x for x in v[1:] if len(x) <= 60]             # 칸 뒤에 붙은 긴 설명 줄은 값이 아님
            row['before'], row['after'] = v[0], ' · '.join(short) if short else None
        out.append(row)
    return out


def new_sentences(row, body_text):
    """문구 항목에서 새로 들어간 문장: 정정사항 칸에 한 번만 나오고(정정 전후 둘 다에 있으면 두 번) 본문에도 있는 줄."""
    v = [x for x in row['vals'] if len(_s(x)) >= 8]
    body = _s(body_text)
    return [x for x in v if sum(_s(y) == _s(x) for y in v) == 1 and _s(x) in body
            and not any(_s(x) != _s(y) and _s(x) in _s(y) for y in v)]      # 늘어난 문장의 옛 버전은 빼고 새 버전만


# ---------------------------------------------------------------- 기타 사항 · 기준 연도
def _etc(T, b):
    i = next((k for k in _all(T, r'^\d+\.기타투자판단') if k >= b), -1)
    if i < 0:
        return []
    out = []
    for t in T[i + 1:]:
        s = _s(t)
        if s.startswith('※관련공시') or s.startswith('【') or s.startswith('구분') and len(s) < 6:
            break
        out.append(t)
    return out


def basis_of(lines, word):
    """「최근매출액은 2025년 연결재무제표 기준」 같은 문장에서 기준 연도·재무제표 종류. 없으면 None."""
    for l in lines:
        s = _s(l)
        j = s.find(word)
        if j < 0 or '기준' not in s[j:]:
            continue
        rest = s[j:]
        m = re.search(r"(\d{4})년", rest) or re.search(r"'(\d{2})년", rest)
        if not m:
            continue
        y = int(m.group(1)); y = y + 2000 if y < 100 else y
        fs = next((w for w in ('연결', '별도', '개별') if w in rest), None)
        part = re.findall(r'(\d{4}[.\-]\d{1,2}[.\-]\d{1,2})', rest)
        return {'year': y, 'fs': fs, 'partial': part[:2] if len(part) >= 2 and ('부터' in rest or '~' in rest) else None, 'text': l.strip()[:200]}
    return None


def _related(T):
    i = next(iter(_all(T, r'^※관련공시')), -1)
    if i < 0:
        return []
    return [t for t in T[i + 1:i + 6] if _date(t) and not _s(t).startswith('【')]


# ---------------------------------------------------------------- 읽기
def parse_supply(doc):
    T = tokens(doc)
    idx = _all(T, r'^1\.판매[ㆍ·]공급계약(해지)?구분')
    b = idx[-1] if idx else len(T)
    head = F2._correction_head(T[:b] if idx else T)
    cancel = bool(re.search(r'해지', _s(T[b]) if idx else ''))
    cp = []
    ci = next((k for k in _all(T, r'^3\.계약상대') if k >= b), -1)
    if ci >= 0:
        for t in T[ci + 1:ci + 6]:
            if _s(t).startswith('-회사와의관계'):
                break
            cp.append(t.strip().lstrip('- ').strip())
    etc = _etc(T, b)
    return {
        **head, 'cancel': cancel, 'body_found': bool(idx),
        'kind_text': T[b + 1] if idx and b + 1 < len(T) else None,
        'name': _at(T, r'^-(체결계약명|세부내용|해지계약명)$', b),
        'amount': _amount(_at(T, r'^(계약금액|해지금액)\(원\)$', b)),
        'revenue': _amount(_at(T, r'^최근매출액\(원\)$', b)),
        'ratio_text': _at(T, r'^매출액대비\(%\)$', b),
        'large': _at(T, r'^대규모법인여부$', b),
        'counterparty': ' '.join(cp) or None, 'relation': _at(T, r'^-회사와의관계$', b),
        'start': _d(_at(T, r'^시작일$', b)), 'end': _d(_at(T, r'^종료일$', b)),
        'start_dash': _s(_at(T, r'^시작일$', b)) == '-', 'end_dash': _s(_at(T, r'^종료일$', b)) == '-',
        'advance': _at(T, r'^계약금ㆍ선급금유무$|^계약금·선급금유무$', b),
        'contract_date': _d(_at(T, r'^\d\.계약\(수주\)일(자)?$', b)),
        'cancel_reason': _at(T, r'^\d\.해지주요사유$', b), 'cancel_date': _d(_at(T, r'^\d\.해지일자$', b)),
        'hold_reason': _at(T, r'^유보사유$', b), 'hold_until': _at(T, r'^유보기한$', b),
        'etc': etc, 'basis': basis_of(etc, '매출'), 'related': _related(T),
        'corr_rows': correction_rows(T, b) if idx else [], 'body_text': ' '.join(T[b:]),
    }


def parse_equity(doc):
    T = tokens(doc)
    idx = _all(T, r'^1\.발행회사$')
    b = idx[-1] if idx else len(T)
    title = ' '.join(T[:3])
    near = {_s(t) for t in T[b:b + 40]}
    w = next((x for x in ('취득', '처분', '양수', '양도') if f'2.{x}내역' in near), '취득')
    put_i = next((k for k in _all(T, r'풋옵션등계약(의)?체결여부') if k >= b), -1)
    put = T[put_i + 1] if put_i >= 0 and put_i + 1 < len(T) else None
    ki = next((k for k in _all(T, r'^-?계약내용$') if k >= b), -1)
    put_txt = None
    if ki >= 0:
        seg = []
        for t in T[ki + 1:ki + 12]:
            if re.match(r'^\d+\.', _s(t)):
                break
            seg.append(t.strip())
        put_txt = ' '.join(seg) or None
    etc = _etc(T, b)
    cp_i = next((k for k in _all(T, r'^\d+\.거래상대방$') if k >= b), -1)
    return {
        **F2._correction_head(T[:b] if idx else T), 'body_found': bool(idx), 'deal': w,
        'disposal': w in ('처분', '양도'), 'major': '주요사항보고서' in title or bool(_all(T[:b] if idx else T, r'^주요사항보고서')),
        'target': _at(T, r'^회사명$', b), 'relation': _at(T, r'^회사와(의)?관계$', b),
        'target_shares': _num(_at(T, r'^발행주식총수\(주\)$', b) or ''),
        'qty': _num(_at(T, rf'^{w}주식수\(주\)$', b) or ''),
        'amount': _amount(_at(T, rf'^{w}금액\(원\)(\(A\))?$', b)),
        'assets': _amount(_at(T, r'^총자산\(원\)(\(B\))?$', b)), 'assets_ratio_text': _at(T, r'^총자산대비\(%\)(\(A/B\))?$', b),
        'equity': _amount(_at(T, r'^자기자본\(원\)(\(C\))?$', b)), 'equity_ratio_text': _at(T, r'^자기자본대비\(%\)(\(A/C\))?$', b),
        'large': _at(T, r'^대규모법인여부$', b),
        'after_qty': _num(_at(T, r'^소유주식수\(주\)$', b) or ''), 'after_pct': _fl(_at(T, r'^지분비율\(%\)$', b)),
        'after_dash': _s(_at(T, r'^소유주식수\(주\)$', b)) == '-',
        'method': _at(T, r'^\d\.취득방법$', b), 'purpose': _at(T, rf'^\d\.{w}목적$', b),
        'when': _d(_at(T, rf'^\d\.{w}예정일자$', b)), 'when_text': _at(T, rf'^\d\.{w}예정일자$', b),
        'decided': _d(_at(T, r'^\d+\.이사회결의일', b)),
        'counterparty': T[cp_i + 2] if cp_i >= 0 and cp_i + 2 < len(T) and _s(T[cp_i + 1]).startswith('회사명') else None,
        'put': put, 'put_text': put_txt if put_txt and _s(put_txt) != '-' else None,
        'etc': etc, 'basis': basis_of(etc, '자기자본'), 'related': _related(T),
        'corr_rows': correction_rows(T, b) if idx else [], 'body_text': ' '.join(T[b:]),
    }


# ---------------------------------------------------------------- 정정 묶음
def _party(k, p):
    return _s(p.get('target') if k.startswith('equity') else p.get('counterparty'))[:40]


def chain(items):
    """items = [(rcept_no, rcept_dt, parsed)] 같은 계약상대끼리. 「정정관련 공시서류제출일」로 이어진 묶음(정정의 정정 포함)을 rcept_no 목록들로."""
    parent = {n: n for n, _, _ in items}

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for n, d, p in items:
        o = p.get('corrects')
        if not o:
            continue
        for m, d2, p2 in items:
            if m != n and (d2 == o or p2.get('corrects') == o) and m < n:
                parent[root(n)] = root(m)
    groups = {}
    for n, _, _ in items:
        groups.setdefault(root(n), []).append(n)
    return [sorted(g) for g in groups.values()]


def attach(out, man, ticker, last, root, open_doc, own_exclude):
    kind, no = out['kind'], out['rcept_no']
    me = out['parsed']; party = _party(kind, me)
    out['newer'] = []
    items = [(no, out['rcept_dt'], me)]
    meta = {}
    for n, x in sorted(man['docs'].items()):
        if n == no or x['ticker'] != ticker or x['kind'] != kind or x['rcept_dt'] > last or own_exclude.search(x.get('report_nm') or ''):
            continue
        files, _ = open_doc(n, root, man)
        p = PARSERS[kind]('\n'.join(t for _, t in files))
        if not party or _party(kind, p) != party:
            continue
        items.append((n, x['rcept_dt'], p)); meta[n] = x
    grp = next(g for g in chain(items) if no in g)
    for n, d, p in sorted(items, key=lambda z: z[0]):
        if n == no or n not in grp:
            continue
        x = meta[n]
        row = {'rcept_no': n, 'rcept_dt': d, 'url': x['url'], 'report_nm': x['report_nm']}
        if n < no:
            out['history'].append({**row, 'parsed': p}); out['docs'].append({'rcept_no': n, 'sha256': x['sha256']})
        else:
            out['newer'].append(row)


# ---------------------------------------------------------------- 계산 (방향 판단 없음)
def _correction_block(f, fact, calc, T, notes, H, amount_label):
    p = f['parsed']
    if not p.get('corrects') and not p.get('corr_rows'):
        return
    o = p.get('corrects')
    gap = (' — 원래 공시와 같은 날' if o == f['rcept_dt'] else f" — 원래 공시 뒤 {_ym(o, f['rcept_dt'])}") if o and o <= f['rcept_dt'] else ''
    fact('정정 공시', f"원래 공시 {o or '날짜 미기재'} · 이 정정 {f['rcept_dt']}{gap}", None, None, '정정 공시 머리의 「정정관련 공시서류제출일」(또는 「최초제출일」) 그대로')
    if p.get('correction_reason'):
        fact('회사가 적은 정정사유(원문 그대로)', f"「{p['correction_reason']}」")
    rows = []
    for r in p.get('corr_rows') or []:
        if r['text']:
            ns = new_sentences(r, p.get('body_text') or '') if not r.get('reason') else []
            after = ('새로 들어가거나 바뀐 문장: ' + ' / '.join(f"「{x[:200]}」" for x in ns[:3]) + (f' 외 {len(ns) - 3}개' if len(ns) > 3 else '')) if ns else '문구가 바뀜(원문 정정사항 표 참고)'
            rows.append([r['item'], r.get('reason') or '', '(문구)', after])
        else:
            cut = lambda x: (x[:300] + '…') if x and len(x) > 300 else (x or '')
            rows.append([r['item'], cut(r.get('reason')), cut(r['before']), cut(r['after'])])
        if r['before'] and _s(r['before']) == '-' and r['after'] and re.search(amount_label, _s(r['item'])) and _num(r['after']) is not None:
            notes.append(f"계약금액이 이 정정에서 처음 공개됐어요(앞선 공시에는 「-」, 이번 {H['won'](_num(r['after']))}).")
    if rows:
        four = any(r[1] for r in rows)
        T.append({'title': '정정사항 — 원문 표 그대로', 'cols': ['항목'] + (['정정사유'] if four else []) + ['정정 전', '정정 후'],
                  'rows': [r if four else [r[0], r[2], r[3]] for r in rows],
                  'hint': '회사가 정정 공시에 적은 표입니다. 문구 항목은 새로 들어가거나 바뀐 문장만 보입니다(본문에서 확인됨). 긴 칸은 300자까지.'})


def _chain_block(f, calc, T, H, fields):
    """같은 계약의 앞선 공시(사본에 있는 것)와 달라진 칸, 그리고 묶음 표."""
    hist = f.get('history') or []
    if not hist:
        return
    p = f['parsed']; old = hist[-1]; q = old['parsed']; ch = []
    for name, get, show in fields:
        a, b = get(q), get(p)
        if a != b and not (a is None and b is None):
            d = ''
            if isinstance(a, int) and isinstance(b, int) and not isinstance(a, bool):
                d = f" ({b - a:+,}{'원' if '금액' in name or '매출액' in name else '주' if '주식' in name else ''}" + (f", {(b - a) / abs(a) * 100:+.2f}%" if a else '') + ')'
            ch.append(f"{name} {show(a)} → {show(b)}{d}")
    if ch:
        calc(f"바로 앞 공시({old['rcept_dt']}, 접수번호 {old['rcept_no']})와 달라진 곳 {len(ch)}곳", ' / '.join(ch), '이 공시 본문의 값과 같은 계약 바로 앞 공시 본문의 값을 견줌(두 원문)')
    rows = []
    for h in hist + [{'rcept_no': f['rcept_no'], 'rcept_dt': f['rcept_dt'], 'url': f['url'], 'parsed': p, 'me': True}]:
        x = h['parsed']
        rows.append([h['rcept_dt'] + (' (이 공시)' if h.get('me') else ''), '정정' if x.get('corrects') else '처음 공시'] +
                    [show(get(x)) for _, get, show in fields[:3]] + [{'text': h['rcept_no'], 'url': h['url']}])
    T.append({'title': '같은 계약의 공시 묶음 (사본, 오래된 순)', 'cols': ['접수일', '구분'] + [n for n, _, _ in fields[:3]] + ['원문'], 'rows': rows,
              'hint': '같은 회사·같은 상대이면서 정정관련 공시서류제출일로 이어진 공시입니다. 사본에 받은 공시만 셉니다.'})


def _basis_note(f, notes, word):
    p = f['parsed']; bs = p.get('basis')
    if not bs:
        notes.append(f'{word} 기준 연도: 원문 기타 사항에 적혀 있지 않아요.')
        return
    y = int(f['rcept_dt'][:4])
    line = f"{word} 기준: {bs['year']}년{' ' + bs['fs'] if bs['fs'] else ''} 재무제표(원문 기타 사항)"
    if bs.get('partial'):
        line += f" — 한 해 전체가 아닌 기간({bs['partial'][0]} ~ {bs['partial'][1]})"
    notes.append(line + '.')
    if y - bs['year'] >= STALE_BASIS_YEARS:
        notes.append(f"{word} 기준({bs['year']}년)이 이 공시({f['rcept_dt']})보다 {y - bs['year']}년 앞서요" +
                     (' — 정정 공시는 원래 공시 때의 숫자를 그대로 쓰는 경우가 많아요' if p.get('corrects') else '') +
                     f". 공시의 비율은 그 해 {word} 기준이라 최근 {word}과 견준 비율과 다를 수 있어요.")


def _supply(k, f, mkt, fact, calc, held, T, notes, H):
    p = f['parsed']; won, pc = H['won'], H['p']
    if not p.get('body_found'):
        held.append('공시 본문 표(1. 판매ㆍ공급계약 구분)를 원문에서 찾지 못함 — 보류'); return
    _correction_block(f, fact, calc, T, notes, H, r'(계약|해지)금액')
    cd, rd = p.get('contract_date'), f['rcept_dt']
    if k == 'supply_contract' and cd and _days(cd, rd) > OLD_CONTRACT_DAYS:
        fact('계약(수주)일', f"{cd} — 이 공시보다 {_ym(cd, rd)} 앞서요(새로 맺은 계약이 아니라 이미 맺은 계약에 관한 공시)", None, None, '공시 7항 계약(수주)일자 그대로')
    elif cd:
        fact('계약(수주)일', cd)
    nm = ' · '.join(x for x in (p.get('kind_text'), p.get('name')) if x)
    if nm:
        fact('해지한 계약' if p['cancel'] else '계약', nm)
    if p.get('counterparty'):
        fact('계약상대', p['counterparty'] + (f" (회사와의 관계: {p['relation']})" if p.get('relation') and _s(p['relation']) != '-' else ''))
    amt, rev = p.get('amount'), p.get('revenue')
    lab = '해지금액' if p['cancel'] else '계약금액'
    if amt == 'dash':
        held.append(f'{lab}: 원문에 「-」로 적혀 있음(공개하지 않았거나 정해지지 않음) — 금액 계산 없음')
    elif amt is None:
        held.append(f'{lab}: 원문 표에서 읽지 못함 — 보류')
    else:
        fact(lab, won(amt), amt, '원', '공시 2항 그대로(부가세 포함 여부 등은 원문 기타 사항대로)')
    if isinstance(rev, int):
        fact('최근 매출액(공시)', won(rev), rev, '원')
    if p.get('ratio_text') and _s(p['ratio_text']) != '-':
        fact('매출액 대비(공시)', f"{p['ratio_text']}%", _fl(p['ratio_text']), '%', '회사가 공시에 적은 값 그대로')
    if p.get('hold_reason') and _s(p['hold_reason']) not in ('-', ''):
        notes.append(f"회사가 계약 내용 일부의 공시를 미루고 있어요(유보사유: {p['hold_reason']}" + (f", 유보기한: {p['hold_until']}" if p.get('hold_until') and _s(p['hold_until']) != '-' else '') + ').')
    s, e = p.get('start'), p.get('end')
    if p['cancel']:
        if p.get('cancel_reason'):
            fact('해지 주요사유(원문 그대로)', p['cancel_reason'])
        if p.get('cancel_date'):
            fact('해지일자', p['cancel_date'])
        notes.append('해지 공시는 원래 계약 공시와 따로 나와요. 원래 계약의 금액·기간은 그 공시에서 확인해 주세요.')
    elif s and e and e >= s:
        n = _days(s, e) + 1
        fact('계약기간', f"{s} ~ {e} ({n:,}일, 약 {n / DAYS_PER_YEAR:.1f}년)", n, '일', '종료일 − 시작일 + 1')
        if s > rd:
            notes.append(f"계약 시작일({s})이 공시일보다 {_ym(rd, s)} 뒤예요.")
        if n > DAYS_PER_YEAR + 1 and isinstance(amt, int):
            per = amt * DAYS_PER_YEAR / n
            calc('계약금액의 1년치', f"{won(per)} (계약금액 ÷ {n:,}일 × {DAYS_PER_YEAR}일)", f'계약금액 ÷ 계약기간 일수 × {DAYS_PER_YEAR} — 해마다 같은 금액이라고 놓은 평균', per, '원')
            if isinstance(rev, int) and rev:
                r = per / rev * 100
                calc('1년치 ÷ 최근 매출액', f"{pc(r)} (공시의 「매출액 대비」 {p.get('ratio_text') or '—'}%는 계약 전체 금액 기준)",
                     f'계약금액 ÷ 계약기간 일수 × {DAYS_PER_YEAR} ÷ 공시의 최근 매출액 × 100', r, '%')
        elif n <= DAYS_PER_YEAR + 1:
            notes.append('계약기간이 1년 이하라 1년치로 나누지 않았어요(공시의 매출액 대비가 곧 1년 안의 비율).')
    elif s and e:
        held.append(f'계약기간: 원문의 종료일({e})이 시작일({s})보다 앞섬 — 1년치 계산 없음')
    elif p.get('end_dash') or p.get('start_dash'):
        held.append('계약기간: 원문에 시작일 또는 종료일이 「-」(정해지지 않음) — 1년치 계산 없음')
    _basis_note(f, notes, '매출액')
    _chain_block(f, calc, T, H, [
        ('해지금액' if p['cancel'] else '계약금액', lambda x: x.get('amount') if isinstance(x.get('amount'), int) else None, won),
        ('매출액 대비(공시)', lambda x: x.get('ratio_text'), lambda v: f'{v}%' if v and _s(v) != '-' else '—'),
        ('종료일', lambda x: x.get('end'), lambda v: v or '—'),
        ('시작일', lambda x: x.get('start'), lambda v: v or '—'),
        ('최근 매출액(공시)', lambda x: x.get('revenue') if isinstance(x.get('revenue'), int) else None, won)])


def _equity(k, f, mkt, fact, calc, held, T, notes, H):
    p = f['parsed']; won, pc = H['won'], H['p']; w = p['deal']
    if not p.get('body_found'):
        held.append('공시 본문 표(1. 발행회사)를 원문에서 찾지 못함 — 보류'); return
    _correction_block(f, fact, calc, T, notes, H, r'금액')
    if p.get('target'):
        tg = p['target'] if len(p['target']) <= 80 else p['target'][:80] + '…(원문 1항 참고)'
        fact(f'{w}하는 회사(발행회사)', tg + (f" (회사와 관계: {p['relation']})" if p.get('relation') and _s(p['relation']) != '-' else ''))
    if p.get('counterparty'):
        fact('거래상대방', p['counterparty'])
    q, amt = p.get('qty'), p.get('amount')
    if q is not None:
        fact(f'{w} 주식 수', f'{q:,}주', q, '주')
    if amt == 'dash':
        held.append(f'{w} 금액: 원문에 「-」 — 금액 없음')
    elif amt is None:
        held.append(f'{w} 금액: 원문 표에서 읽지 못함 — 보류')
    else:
        fact(f'{w} 금액', won(amt), amt, '원', '공시 2항 그대로')
    if isinstance(p.get('equity'), int):
        fact('자기자본(공시)', won(p['equity']), p['equity'], '원')
    if p.get('equity_ratio_text') and _s(p['equity_ratio_text']) != '-':
        fact('자기자본 대비(공시)', f"{p['equity_ratio_text']}%", _fl(p['equity_ratio_text']), '%', '회사가 공시에 적은 값 그대로')
    if p.get('assets_ratio_text') and _s(p['assets_ratio_text']) != '-':
        fact('총자산 대비(공시)', f"{p['assets_ratio_text']}%", _fl(p['assets_ratio_text']), '%', '회사가 공시에 적은 값 그대로')
    aq, ap, tot = p.get('after_qty'), p.get('after_pct'), p.get('target_shares')
    if aq is not None and ap is not None:
        fact(f'{w} 후 소유 주식·지분', f'{aq:,}주 · {ap:g}%', ap, '%')
    elif p.get('after_dash'):
        fact(f'{w} 후 소유 주식·지분', '없음(원문 「-」)')
    before = None
    if aq is not None and q is not None:
        before = aq + q if p['disposal'] else aq - q
    elif p.get('after_dash') and q is not None and p['disposal']:
        before = q
    if before is not None and before >= 0 and tot:
        r = before / tot * 100
        calc(f'{w} 전 보유 주식·지분', f"{before:,}주 · {pc(r)} (발행주식총수 {tot:,}주 기준)",
             f"{'처분 후 소유주식수 + 처분 주식 수' if p['disposal'] else '취득 후 소유주식수 − 취득 주식 수'} ÷ 공시 1항 발행주식총수 × 100 (발행주식총수는 회사가 적은 기준일)", r, '%')
        if not p['disposal'] and before > 0 and before == tot and ap == 100:
            notes.append('이 회사가 이미 지분 100%를 가진 회사(발행주식 전부 보유)에 더 넣는 돈이에요 — 회사 밖으로 나가는 투자가 아니라 그룹 안에서 돈이 옮겨 가는 거래예요.')
        elif not p['disposal'] and before == 0 and ap == 100:
            notes.append('이 거래로 발행회사 지분 100%를 새로 가져요(앞서 가진 주식 없음).')
    if p.get('method'):
        fact('취득 방법', p['method'])
    if p.get('purpose'):
        fact(f'{w} 목적', p['purpose'])
    if p.get('when'):
        fact(f'{w} 예정일자', p['when'])
    elif p.get('when_text') and _s(p['when_text']) == '-':
        notes.append(f'{w} 예정일자가 원문에 「-」(아직 정해지지 않음)예요.')
    if p.get('put_text') or (p.get('put') and _s(p['put']) in ('예', '해당', '유')):
        fact('풋옵션 등 계약', '있음' + (f" — 원문: 「{p['put_text'][:300]}{'…' if len(p['put_text']) > 300 else ''}」" if p.get('put_text') else ''),
             None, None, '공시의 「풋옵션 등 계약 체결여부·계약내용」 그대로 — 나중에 주식을 사거나 팔아야 할 수 있는 조건')
    _basis_note(f, notes, '자기자본')
    _chain_block(f, calc, T, H, [
        (f'{w} 금액', lambda x: x.get('amount') if isinstance(x.get('amount'), int) else None, won),
        ('자기자본 대비(공시)', lambda x: x.get('equity_ratio_text'), lambda v: f'{v}%' if v and _s(v) != '-' else '—'),
        (f'{w} 예정일자', lambda x: x.get('when') or x.get('when_text'), lambda v: v or '—'),
        (f'{w} 주식 수', lambda x: x.get('qty'), lambda v: f'{v:,}주' if v is not None else '—'),
        (f'{w} 후 지분(%)', lambda x: x.get('after_pct'), lambda v: f'{v:g}%' if v is not None else '—')])


def compute(k, f, mkt, fact, calc, held, T, notes, H):
    (_supply if k.startswith('supply') else _equity)(k, f, mkt, fact, calc, held, T, notes, H)


PARSERS = {'supply_contract': parse_supply, 'supply_cancel': parse_supply, 'equity_deal': parse_equity, 'equity_deal_major': parse_equity}

F2.KINDS2 = tuple(dict.fromkeys(F2.KINDS2 + KINDS))
F2.KIND_LABEL2.update(LABELS)
F2.PARSERS2.update(PARSERS)
F2.EXTRA.update({k: compute for k in KINDS})
F2.ATTACH.update({k: attach for k in KINDS})
