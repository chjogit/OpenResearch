"""v0.37 (전태 축, N13 확장): 약속–실행 — 자기주식 취득 결정 · 취득 결과보고서 · 주식 소각 결정을 DART 원문에서 읽어 짝짓는다.

- 원문은 mrn.dartdocs 의 해시 고정 사본에서만 읽는다. AI 모델 호출 0회, 숫자는 원문 칸 값 그대로.
- 읽지 못한 칸은 지어내지 않고 None 으로 둔다(노드가 보류로 표시).
- 규칙 promise-v1: 짝 = 결과보고서의 「주요사항보고서 제출일」 = 취득 결정 접수일. 이행률 = 실제 취득 총액 ÷ 결정 예정 금액.
  소각 연결 = 취득 결정 뒤에 나온 소각 결정 중 수량 차이가 1% 이내인 첫 공시.
"""
import re

RULE = 'promise-v1'
OK_RATE, PART_RATE = 95.0, 50.0        # 팀 합의 전 초안 기준(화면에 기준을 함께 보인다)
_TAG = re.compile(r'<(style|script)[^>]*>.*?</\1>|<[^>]+>', re.S | re.I)
_DATE = re.compile(r'(\d{4})\s*[년.\-]\s*(\d{1,2})\s*[월.\-]\s*(\d{1,2})')


def tokens(doc):
    """태그 사이의 글 조각 목록(빈 것 제외). 표의 칸 순서를 그대로 따른다."""
    out = []
    for t in _TAG.split(doc):
        if t is None or t.lower() in ('style', 'script'):
            continue
        t = re.sub(r'&nbsp;|&#160;', ' ', t); t = re.sub(r'\s+', ' ', t).strip()
        if t:
            out.append(t)
    return out


def _num(t):
    t = (t or '').replace(',', '').replace(' ', '')
    return int(t) if re.fullmatch(r'-?\d+', t) else None


def _date(t):
    m = _DATE.search(t or '')
    return f'{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}' if m else None


def _find(T, pat, start=0):
    r = re.compile(pat)
    for i in range(start, len(T)):
        if r.search(T[i].replace(' ', '')):
            return i
    return -1


def _all(T, pat):
    r = re.compile(pat)
    return [i for i, t in enumerate(T) if r.search(t.replace(' ', ''))]


def _pair(T, pat, kind='num'):
    """「라벨 | 보통주식 | 값 | 기타(종류)주식 | 값」 꼴에서 (보통, 기타). 정정 공시는 앞쪽 정정표를 건너뛰고 본문 서식의 칸을 읽는다."""
    f = _num if kind == 'num' else _date
    for i in _all(T, pat):
        seg = T[i + 1:i + 6]
        a = b = None; shape = False
        for j, t in enumerate(seg[:-1]):
            s = t.replace(' ', '')
            if s.startswith('보통주식') and not shape:
                a = f(seg[j + 1]); shape = True
            elif (s.startswith('기타주식') or s.startswith('종류주식')) and b is None:
                b = f(seg[j + 1])
        if shape:
            return a, b
    return None, None


def _span(T, pat):
    """「라벨 | 시작일 | 날짜 | 종료일 | 날짜」."""
    for i in _all(T, pat):
        seg = T[i + 1:i + 6]; a = b = None; shape = False
        for j, t in enumerate(seg[:-1]):
            if t.replace(' ', '') == '시작일':
                a = _date(seg[j + 1]); shape = True
            elif t.replace(' ', '') == '종료일':
                b = _date(seg[j + 1])
        if shape:
            return a, b
    return None, None


def _one(T, pat, f=None):
    """「라벨 | 값」 — 본문 서식(마지막에 나오는 것)을 읽는다."""
    idx = _all(T, pat)
    if not idx or idx[-1] + 1 >= len(T):
        return None
    v = T[idx[-1] + 1]
    return f(v) if f else v


def _correction(T):
    """정정 공시면 최초 제출일."""
    i = _find(T, r'정정대상공시서류의최초제출일')
    return next((d for d in (_date(t) for t in T[i:i + 3]) if d), None) if i >= 0 else None


def parse_decision(doc):
    T = tokens(doc)
    q, qo = _pair(T, r'^1\.취득예정주식'); a, ao = _pair(T, r'^2\.취득예정금액')
    s, e = _span(T, r'^3\.취득예상기간')
    return {'qty': q, 'qty_other': qo, 'amount': a, 'amount_other': ao, 'start': s, 'end': e,
            'purpose': _one(T, r'^5\.취득목적'), 'decided': _one(T, r'^9\.취득결정일', _date), 'corrects': _correction(T)}


UNIT = {'원': 1, '천원': 1_000, '백만원': 1_000_000, '억원': 100_000_000}


def parse_result(doc):
    T = tokens(doc)
    i = _find(T, r'주요사항보고서제출일')
    filed = next((d for d in (_date(t) for t in T[i:i + 3]) if d), None) if i >= 0 else None
    k = _find(T, r'^나\.취득기간'); s = e = None
    if k >= 0:
        ds = [d for d in (_date(t) for t in T[k:k + 6]) if d]
        s, e = (ds + [None, None])[:2]
    # 3. 취득내용 표의 「계」 줄: 주문수량 · 취득수량 · 1주당 취득가액 · 취득가액 총액. 주식 종류별로 표가 여럿이면 「계」가 여러 번 나온다.
    qty = total = None; n_tot = 0; mult = None
    c = _find(T, r'^3\.취득내용'); h = _find(T, r'^4\.취득예정내용과실제취득내용')
    if c >= 0:
        m = re.search(r'단위:?([가-힣]*원)', ''.join(T[c:c + 3]).replace(' ', ''))
        mult = UNIT.get(m.group(1)) if m else None
        for x in range(c, h if h > c else len(T)):
            if T[x].replace(' ', '') in ('계', '합계'):
                nums = [n for n in (_num(t) for t in T[x + 1:x + 7]) if n is not None]
                n_tot += 1
                if len(nums) >= 4 and n_tot == 1:
                    qty, total = nums[1], nums[3] * mult if mult else None
    if n_tot != 1:
        qty = total = None                   # 종류별 표가 여럿이면 「계」 한 줄을 전체로 읽지 않는다
    # 4. 일치 여부 표: 2025년 이후 서식은 금액(예정·실제), 이전 서식은 주식 수(예정·실제). 값 4개 = 예정(보통·기타), 실제(보통·기타)
    basis = None; st = [None] * 4
    if h >= 0:
        head = ''.join(T[h + 1:h + 4]).replace(' ', '')
        basis = 'amount' if '취득예정금액' in head else 'qty' if '취득예정주식' in head else None
        m = _find(T, r'(미달|차이)발생시사유', h)
        if m >= 0:
            vals = [t for t in T[m + 1:m + 12] if t.replace(' ', '') not in ('보통주식', '기타주식', '종류주식')][:4]
            if len(vals) == 4:
                st = [_num(v) for v in vals]
    stated_total = (st[2] or 0) + (st[3] or 0) if basis == 'amount' and st[2] is not None else None
    stated_qty = (st[2] or 0) + (st[3] or 0) if basis == 'qty' and st[2] is not None else None
    return {'decision_filed': filed, 'start': s, 'end': e, 'qty': qty if qty is not None else stated_qty, 'total': stated_total if stated_total is not None else total,
            'table_total': total, 'stated_basis': basis, 'stated_planned': st[0], 'stated_planned_other': st[1], 'stated_actual': st[2], 'stated_actual_other': st[3], 'total_rows': n_tot}


def parse_retire(doc):
    T = tokens(doc)
    q, qo = _pair(T, r'^1\.소각할주식의종류와수'); tot, _ = _pair(T, r'^2\.발행주식총수')
    s, e = _span(T, r'^5\.소각을위한자기주식취득예정기간')
    return {'qty': q, 'qty_other': qo, 'shares_total': tot, 'amount': _one(T, r'^4\.소각예정금액', _num), 'retire_date': _one(T, r'^7\.소각예정일', _date),
            'method': _one(T, r'^6\.소각할주식의취득방법'), 'decided': _one(T, r'^9\.이사회결의일', _date), 'buy_start': s, 'buy_end': e, 'corrects': _correction(T)}


def judge(rate):
    return '이행' if rate >= OK_RATE else '부분 이행' if rate >= PART_RATE else '미달'


def build(ticker, cutoff, root=None):
    """기준시점까지의 공시로 약속–실행 표를 만든다. 반환: {'rows': [...], 'retires': [...], 'held': [...], 'source': {...}}"""
    from . import dartdocs as D
    last = (cutoff or '9999')[:10]
    held, src = [], []

    def load(kind, fn):
        out = []
        from .capital import own as _own                 # v0.37.8: 자회사 공시(「자회사의 주요경영사항」)는 이 회사의 약속이 아니므로 뺀다
        docs, n_sub = _own(D.find(ticker, kind, cutoff, root))
        if n_sub:
            held.append(f"자회사 {({'buyback_decision': '자기주식 취득 결정', 'buyback_result': '취득 결과보고서', 'retire': '주식 소각 결정'})[kind]} {n_sub}건은 이 회사 것이 아니어서 쓰지 않음")
        for d in docs:
            files, meta = D.open_doc(d['rcept_no'], root)
            out.append({**fn(files[0][1]), 'rcept_no': d['rcept_no'], 'rcept_dt': d['rcept_dt'], 'report_nm': d['report_nm'], 'url': d['url'], 'sha256': meta['sha256']})
            src.append({'rcept_no': d['rcept_no'], 'sha256': meta['sha256']})
        return out
    dec, res, ret = load('buyback_decision', parse_decision), load('buyback_result', parse_result), load('retire', parse_retire)
    D_ = {}                                  # 최초 제출일 → 결정(정정이 있으면 가장 늦은 정정의 값)
    for d in sorted(dec, key=lambda x: x['rcept_no']):
        key = d.get('corrects') or d['rcept_dt']
        if key in D_:
            d = {**d, 'first_rcept_no': D_[key].get('first_rcept_no') or D_[key]['rcept_no'], 'corrected': True}
        D_[key] = {**d, 'filed': key}
    R_ = {}
    for r in sorted(res, key=lambda x: x['rcept_no']):
        if r['decision_filed']:
            R_[r['decision_filed']] = r      # 같은 결정의 정정 결과보고서는 뒤의 것이 덮는다
        else:
            held.append(f"취득 결과보고서 {r['rcept_no']}: 어느 결정의 결과인지(주요사항보고서 제출일) 읽지 못함")
    for k in [k for k in R_ if k not in D_]:
        r = R_.pop(k)                         # 제출일이 맞는 결정이 없으면: 결과가 아직 없는 결정 중 취득 기간이 들어맞는 하나로
        cand = [dk for dk, d in D_.items() if dk not in R_ and r['start'] and r['end'] and dk <= r['start'] and d['end'] and r['end'] <= d['end']]
        if len(cand) == 1:
            R_[cand[0]] = {**r, 'matched_by': 'period'}
            held.append(f"취득 결과보고서 {r['rcept_no']}: 적힌 「주요사항보고서 제출일」({k})과 맞는 결정이 없어, 취득 기간이 들어맞는 {cand[0]} 결정과 짝지음(규칙)")
        else:
            held.append(f"취득 결과보고서 {r['rcept_no']}: 짝이 되는 취득 결정({k} 제출)을 찾지 못함")
    # 정정 소각 결정은 최초 것을 덮는다
    T_ = {}
    for t in sorted(ret, key=lambda x: x['rcept_no']):
        T_[t.get('corrects') or t['rcept_dt']] = t
    free = sorted(T_.values(), key=lambda x: x['rcept_no'])
    rows = []
    for key in sorted(D_):
        d = D_[key]; r = R_.get(key)
        plan = (d['amount'] or 0) + (d['amount_other'] or 0)
        row = {'filed': key, 'decision': d, 'result': r, 'planned_amount': plan or None, 'actual_amount': r['total'] if r else None, 'rate': None, 'verdict': None, 'retire': None}
        if r and plan and r['total'] is not None:
            row['rate'] = round(r['total'] / plan * 100, 1); row['verdict'] = judge(row['rate'])
        elif r:
            held.append(f"{key} 취득 결정: 예정 금액 또는 실제 취득 총액을 읽지 못해 이행률 보류")
        else:
            row['verdict'] = '진행 중' if (d['end'] or '') > last else '결과 미확인'
        rows.append(row)
    link_notes = []
    for t in sorted(T_.values(), key=lambda x: x['rcept_no']):
        tq = (t['qty'] or 0) + (t['qty_other'] or 0)
        if not tq:
            continue
        best = None
        for row in rows:                      # 소각 결정 이전(같은 날 포함)에 나온 결정 중, 수량 차이 1% 이내이고 가장 가까운 것
            if row['retire'] or row['filed'] > t['rcept_dt']:
                continue
            base = (row['result'] or {}).get('qty') or ((row['decision']['qty'] or 0) + (row['decision']['qty_other'] or 0))
            if base and abs(tq - base) / base <= 0.01 and (best is None or row['filed'] > best['filed']):
                best = row
        if best:
            best['retire'] = t; free.remove(t)
    return {'rows': rows, 'retires': sorted(T_.values(), key=lambda x: x['rcept_no']), 'unlinked_retires': free, 'held': held, 'docs': src, 'rule': RULE}
