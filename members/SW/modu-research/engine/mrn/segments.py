"""v0.37 (박상혁 P02 이식): 사업부별 분기 매출 — 정기보고서(사업·반기·분기)의 연결재무제표 주석 「부문별 보고」 표를 읽는다.

- 원문은 mrn.dartdocs 의 해시 고정 사본에서만 읽는다. AI 모델 호출 0회. 금액은 표의 칸 값 × 표에 적힌 단위, 원 단위 정수.
- 못 읽은 표·칸은 지어내지 않고 건너뛴 사유를 남긴다.
"""
import re

RULE = 'segment-v1'
UNIT = {'원': 1, '천원': 1_000, '백만원': 1_000_000, '억원': 100_000_000, '십억원': 1_000_000_000, '조원': 1_000_000_000_000}
_TAG = re.compile(r'<[^>]+>')
_CELL = re.compile(r'<(TH|TD|TE|TU)\b([^>]*)>(.*?)</\1>', re.S | re.I)
_ROW = re.compile(r'<TR\b[^>]*>(.*?)</TR>', re.S | re.I)


def _text(s):
    s = _TAG.sub(' ', s); s = re.sub(r'&nbsp;|&#160;', ' ', s).replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    return re.sub(r'\s+', ' ', s).strip()


def _span(attrs, name):
    m = re.search(name + r'="(\d+)"', attrs, re.I)
    return int(m.group(1)) if m else 1


def grid(table):
    """표 하나를 칸 병합(COLSPAN·ROWSPAN)을 풀어 사각 격자로. 반환: (머리 줄들, 몸통 줄들) — 각 줄은 글자 목록."""
    def rows_of(block):
        out, carry = [], {}                   # carry: 열 번호 → (남은 줄 수, 글)
        for rm in _ROW.finditer(block):
            row, c = [], 0
            cells = [(_span(a, 'COLSPAN'), _span(a, 'ROWSPAN'), _text(x)) for _t, a, x in _CELL.findall(rm.group(1))]
            k = 0
            while k < len(cells) or c in carry:
                if c in carry:
                    n, txt = carry[c]; row.append(txt)
                    if n > 1: carry[c] = (n - 1, txt)
                    else: del carry[c]
                    c += 1; continue
                cs, rs, txt = cells[k]; k += 1
                for _ in range(cs):
                    row.append(txt)
                    if rs > 1: carry[c] = (rs - 1, txt)
                    c += 1
            out.append(row)
        return out
    h = re.search(r'<THEAD\b[^>]*>(.*?)</THEAD>', table, re.S | re.I)
    b = re.search(r'<TBODY\b[^>]*>(.*?)</TBODY>', table, re.S | re.I)
    return rows_of(h.group(1)) if h else [], rows_of(b.group(1) if b else (table if not h else ''))


def num(t):
    """「1,234」「(1,234)」「-1,234」「△1,234」 → 정수. 숫자가 아니면 None."""
    s = (t or '').replace(',', '').replace(' ', '')
    neg = s.startswith('(') and s.endswith(')') or s[:1] in ('-', '△', '▲')
    s = s.strip('()').lstrip('-△▲')
    return (-int(s) if neg else int(s)) if re.fullmatch(r'\d+', s) else None


def sections(doc):
    """「부문」이 제목에 든 구역들: [(제목, 구역 원문)]. 연결 주석을 먼저."""
    out = []
    marks = [(m.start(), _text(m.group(0))) for m in re.finditer(r'<TITLE\b[^>]*>.*?</TITLE>', doc, re.S | re.I)]
    for k, (pos, title) in enumerate(marks):
        if '부문' in title:
            end = marks[k + 1][0] if k + 1 < len(marks) else len(doc)
            out.append((title, doc[pos:end]))
    return sorted(out, key=lambda x: 0 if '연결' in x[0] else 1)


def tables(section):
    return [t for t in re.split(r'(?=<TABLE\b)', section) if t.startswith('<TABLE') or t.startswith('<table')]


REV_ROWS = ('매출액', '순매출액', '영업수익', '매출', '수익(매출액)')
REGION_WORDS = ('국내', '한국', '본사', '미주', '북미', '유럽', '아시아', '중국', '일본', '해외', '기타지역', '아프리카', '중남미', '미국', '베트남', '인도')
_CUR = ('당분기', '당반기', '당기', '당3분기', '당1분기')
_PRI = ('전분기', '전반기', '전기', '전3분기', '전1분기')


def find_sections(doc):
    """서식 두 가지를 모두 찾는다: (가) 제목(TITLE)에 「부문」이 든 구역, (나) 문단 「NN. 부문별 보고」로 시작하는 구역. 연결 주석을 앞에."""
    out = sections(doc)
    if out:
        return out
    for m in re.finditer(r'<P\b[^>]*>\s*(\d{1,2})\.\s*부문별\s*보고', doc):
        n = int(m.group(1))
        nxt = re.search(r'<P\b[^>]*>\s*%d\.\s*[가-힣]' % (n + 1), doc[m.end():])
        end = m.end() + (nxt.start() if nxt else 200_000)
        sec = doc[m.start():end]
        out.append(('부문별 보고 (연결)' if '연결회사' in _text(sec[:3000]) else '부문별 보고', sec))
    return sorted(out, key=lambda x: 0 if '연결' in x[0] else 1)


def _col_info(path):
    """머리 칸 경로(위→아래) → (이름, 역할, 기간 구분). 역할: entity·adjust·total."""
    p = [x for x in path if x]
    span = None
    if p and p[-1].replace(' ', '') in ('3개월', '누적'):
        span = '3m' if p[-1].replace(' ', '') == '3개월' else 'cum'; p = p[:-1]
    uniq = [x for i, x in enumerate(p) if i == 0 or x != p[i - 1]]
    name = uniq[-1] if uniq else ''
    flat = name.replace(' ', '')
    if '조정후' in flat:
        role = 'total'                         # 「조정후금액」 = 조정을 반영한 연결 합계
    elif any(re.search(r'내부거래|조정', x.replace(' ', '')) for x in uniq):
        role = 'adjust'                        # 경로 어디든 「내부거래·조정」이 있으면 조정 칸
    elif re.search(r'합계|총계|^계(\(|$)|^소계', flat):
        role = 'total'
    else:
        role = 'entity'
    return re.sub(r'\(\*\d*\)|\(주\d*\)', '', name).strip(), role, span


_PERIOD = re.compile(r'(당|전)(1분기|3분기|분기|반기|기)(말)?')


def _ctx(text, ctx):
    """표 앞 글에서 기간(당·전), 3개월/누적, 단위, 표 제목을 읽는다."""
    t = text.replace(' ', '')
    m = re.search(r'단위:?([가-힣]+원)', t)
    if m and m.group(1) in UNIT:
        ctx['unit'] = UNIT[m.group(1)]
    ms = [x for x in _PERIOD.finditer(t) if not x.group(3)]
    if ms:
        last = ms[-1]
        ctx['period'] = 'current' if last.group(1) == '당' else 'prior'
        near = t[last.end():last.end() + 8]
        ctx['span'] = '3m' if '3개월' in near else 'cum' if '누적' in near else None
    if any(k in text for k in ('부문', '지역', '제품', '용역')) and len(text) < 400:
        ctx['label'] = text


def extract(doc, consolidated=True):
    """부문별 보고 구역의 매출 표를 관측값으로. 반환: (관측 목록, 건너뛴 사유 목록).
    관측 = {table, axis, period(current·prior), span(3m·cum·None), name, role(entity·adjust·subtotal·total), value(원), unit, row}"""
    allsec = find_sections(doc)
    secs = [s for s in allsec if ('연결' in s[0]) == consolidated]
    if not secs:
        return [], ['부문별 보고 구역을 찾지 못함']
    sec = secs[0][1]
    obs, skipped = [], []
    ctx = {'period': None, 'span': None, 'unit': None, 'label': ''}
    last = None
    parts = re.split(r'(?=<TABLE\b)', sec)
    for ti, part in enumerate(parts):
        if not part.upper().startswith('<TABLE'):
            _ctx(_text(part), ctx); continue
        end = part.upper().find('</TABLE>')
        table, tail = (part[:end + 8], part[end + 8:]) if end >= 0 else (part, '')
        head, body = grid(table)
        rev = [r for r in body if r and r[0].replace(' ', '') in REV_ROWS]
        if not rev:
            _ctx(' '.join(' '.join(r) for r in head + body)[:400], ctx); _ctx(_text(tail), ctx); continue
        hdr = head if head else body[:1]
        r = rev[0]
        width = max(len(x) for x in hdr + [r])
        cols = [_col_info([x[c] if c < len(x) else '' for x in hdr]) for c in range(width)]
        names = [n.replace(' ', '') for n, role, _ in cols[1:] if role == 'entity']
        top = ' '.join(x for row in hdr for x in row) + ' ' + ctx['label']
        if sum(1 for n in names if n.endswith('부문')) >= 2:
            axis = 'segment'
        elif names and sum(1 for n in names if any(w in n for w in REGION_WORDS)) >= max(2, (len(set(names)) + 1) // 2):
            axis = 'region'
        elif '제품' in ' '.join(x for row in hdr for x in row) or '용역' in ' '.join(x for row in hdr for x in row):
            axis = 'product'
        else:
            lab = ctx['label']
            axis = 'region' if '지역' in lab else 'product' if ('제품' in lab or '용역' in lab) else 'segment' if '부문' in lab else 'product'
        if ctx['period'] is not None and ctx['span'] is None and last and last[0] == ctx['period'] and last[1] and axis == 'product' and last[2] == 'segment':
            ctx['span'] = last[1]              # 부문 표 바로 뒤의 제품 표가 「(누적)」 표시 없이 이어질 때: 앞 표의 기간 구분을 따른다(합계 일치로 다시 확인)
        if ctx['unit'] is None or ctx['period'] is None:
            skipped.append(f"표 {ti}({axis}): {'단위' if ctx['unit'] is None else '기간(당기·전기)'}를 읽지 못해 건너뜀")
        else:
            row = []
            note = _text(table) + ' ' + _text(tail) + ' ' + (_text(parts[ti + 1])[:300] if ti + 1 < len(parts) else '')
            partial = bool(re.search(r'별도로\s*표시하지\s*않', note))     # 「기타는 별도로 표시하지 않았습니다」 = 일부 항목만 공시된 표
            for c in range(1, min(width, len(r))):
                v = num(r[c]); name, role, span = cols[c]
                if v is None or not name:
                    continue
                row.append({'table': ti, 'axis': axis, 'period': ctx['period'], 'span': span or ctx['span'], 'name': name, 'role': role, 'value': v * ctx['unit'], 'unit': ctx['unit'], 'row': r[0], 'partial': partial})
            # 합계 칸 뒤에 조정 칸이 있으면 그 합계는 「부문 소계」
            for i, o in enumerate(row):
                if o['role'] == 'total' and any(x['role'] == 'adjust' and x['span'] == o['span'] for x in row[i + 1:]):
                    o['role'] = 'subtotal'
            obs += row
            last = (ctx['period'], row[0]['span'] if row else None, axis)
        ctx['period'] = None; ctx['span'] = None
        _ctx(_text(tail), ctx)
    return obs, skipped


ALIASES = {'005930': {'Haman': 'Harman'}}      # PM 등록 연결(원문 오기). 그 밖의 이름 변경은 자동으로 잇지 않는다
_KIND = (('사업보고서', 'FY'), ('반기보고서', 'H1'), ('분기보고서', 'Q'))


def report_period(report_nm):
    """「분기보고서 (2025.09)」 → (2025, 'Q3'). 12월 결산이 아니면 None."""
    m = re.search(r'\((\d{4})\.(\d{2})\)', report_nm or '')
    if not m:
        return None
    y, mo = int(m.group(1)), int(m.group(2))
    kind = next((k for w, k in _KIND if w in report_nm), None)
    if kind == 'FY':
        return (y, 'FY') if mo == 12 else None
    if kind == 'H1':
        return (y, 'H1') if mo == 6 else None
    if kind == 'Q':
        return (y, 'Q1') if mo == 3 else (y, 'Q3') if mo == 9 else None
    return None


def key_of(ticker, name):
    k = re.sub(r'\s+', '', name)
    k = re.sub(r'(?<=.)(사업)?부문$', '', k)              # v0.37.5: 「DS 부문」「DS부문」「DS」는 같은 사업(꼬리말만 다름)
    return ALIASES.get(ticker, {}).get(k, k)


def _slot(rp, period, span):
    """(보고서 기간, 당기·전기, 3개월·누적) → (연도, 구간). 구간: Q1·Q2·Q3(3개월) · H1·9M(누적) · FY."""
    y, k = rp
    if period == 'prior':
        y -= 1
    if k == 'FY':
        return (y, 'FY') if span in (None, 'cum') else None
    if k == 'Q1':
        return (y, 'Q1')
    if span == '3m':
        return (y, 'Q2' if k == 'H1' else 'Q3')
    if span in ('cum', None):      # v0.37.5: 반기·3분기 보고서 표에 3개월·누적 표시가 없으면 누적으로 본다(틀리면 관문 ②의 분기 대조에서 걸러짐)
        return (y, 'H1' if k == 'H1' else '9M')
    return None


def collect(ticker, cutoff, root=None):
    """기준시점까지의 정기보고서에서 관측값을 모은다. 반환: {'facts': [...], 'tables': [...], 'held': [...], 'docs': [...]}"""
    from . import dartdocs as D
    facts, tabs, held, docs = [], [], [], []
    for d in D.find(ticker, 'periodic', cutoff, root):
        if '정정' in d['report_nm']:
            held.append(f"{d['report_nm']} ({d['rcept_no']}): 정정 보고서는 쓰지 않음 — 최초 정기보고 값을 기준으로 함"); continue
        rp = report_period(d['report_nm'])
        if not rp:
            held.append(f"{d['report_nm']} ({d['rcept_no']}): 12월 결산 정기보고서가 아니라 기간을 정하지 못함"); continue
        files, meta = D.open_doc(d['rcept_no'], root)
        obs, skipped = extract(max(files, key=lambda f: len(f[1]))[1])
        held += [f"{d['report_nm']} ({d['rcept_no']}) {x}" for x in skipped]
        docs.append({'rcept_no': d['rcept_no'], 'sha256': meta['sha256'], 'report_nm': d['report_nm']})
        groups = {}
        for o in obs:
            groups.setdefault((o['table'], o['span']), []).append(o)
        for (ti, span), row in groups.items():
            slot = _slot(rp, row[0]['period'], span)
            if not slot:
                held.append(f"{d['report_nm']} ({d['rcept_no']}) 표 {ti}: 3개월·누적 구분을 읽지 못해 쓰지 않음"); continue
            ents = [o for o in row if o['role'] == 'entity']; adj = [o for o in row if o['role'] == 'adjust']; tot = [o for o in row if o['role'] == 'total']
            unit = row[0]['unit']; n = len(ents) + len(adj)
            t = {'rcept_no': d['rcept_no'], 'report': d['report_nm'], 'url': d['url'], 'table': ti, 'axis': row[0]['axis'], 'slot': slot, 'role_in_report': row[0]['period'],
                 'names': tuple(sorted(key_of(ticker, o['name']) for o in ents)), 'sum': sum(o['value'] for o in ents) + sum(o['value'] for o in adj),
                 'total': tot[-1]['value'] if tot else None, 'tolerance': unit * n // 2, 'unit': unit}
            res = (t['sum'] - t['total']) if tot else None
            if res is not None and abs(res) <= t['tolerance']:
                t['contract'], t['residual'] = ('B' if adj else 'A'), res          # 항목 합(+조정) = 합계 확인
            elif res is None or row[0].get('partial'):
                t['contract'], t['residual'] = 'C', None                           # 일부 항목만 공시된 표 — 합계 일치를 주장하지 않음
            else:
                t['contract'], t['residual'] = 'X', res                            # 표시가 없는데 합이 안 맞음 → 보류
                held.append(f"{d['report_nm']} ({d['rcept_no']}) 표 {ti}({row[0]['axis']}, {slot[0]}{slot[1]}): 항목 합과 합계가 {res:,}원 달라 이 표의 값은 「확인 필요」")
            tabs.append(t)
            for o in ents:
                facts.append({'axis': o['axis'], 'key': key_of(ticker, o['name']), 'name': o['name'], 'slot': slot, 'value': o['value'], 'unit': unit, 'rcept_no': d['rcept_no'], 'report': d['report_nm'],
                              'url': d['url'], 'role_in_report': o['period'], 'version': t['names'], 'table': ti})
            if tot:
                facts.append({'axis': o['axis'], 'key': '(연결 합계)', 'name': '연결 합계', 'slot': slot, 'value': tot[-1]['value'], 'unit': unit, 'rcept_no': d['rcept_no'], 'report': d['report_nm'],
                              'url': d['url'], 'role_in_report': row[0]['period'], 'version': t['names'], 'table': ti})
    return {'facts': facts, 'tables': tabs, 'held': held, 'docs': docs}


def growth_pct(cur, prev):
    """전년 동기 증감률(%) — Decimal, 소수 둘째 자리 반올림(ROUND_HALF_UP). 전년 값이 양수일 때만."""
    from decimal import Decimal, ROUND_HALF_UP
    if prev is None or cur is None or prev <= 0:
        return None
    return float(((Decimal(cur) / Decimal(prev) - 1) * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def quarters(col):
    """관측값 → 단독분기 매출. 원문에 3개월 값이 있으면 그 값(reported_3m), 없을 때만 누적 차감(derived).
    반환: {'cells': {(axis, key): {(연도, 'Qn'): {...}}}, 'held': [...]}"""
    idx = {}
    for f in col['facts']:
        idx.setdefault((f['axis'], f['key'], f['slot']), []).append(f)
    for v in idx.values():
        v.sort(key=lambda f: (0 if f['role_in_report'] == 'current' else 1, f['rcept_no']))
    cells, held = {}, list(col['held'])
    keys = sorted({(a, k) for a, k, _ in idx})
    years = sorted({s[0] for _, _, s in idx})

    def src(f):
        return {'rcept_no': f['rcept_no'], 'report': f['report'], 'url': f['url'], 'value': f['value'], 'role': f['role_in_report']}
    for a, k in keys:
        out = cells.setdefault((a, k), {})
        for y in years:
            for q in ('Q1', 'Q2', 'Q3'):
                fs = idx.get((a, k, (y, q)))
                if fs:
                    f = fs[0]
                    out[(y, q)] = {'value': f['value'], 'method': 'reported_3m', 'name': f['name'], 'unit': f['unit'], 'sources': [src(f)], 'version': f['version']}
                    # 누적 차감 값과 대조 (Q2 = 반기누적 − Q1, Q3 = 9개월누적 − 반기누적)
                    hi, lo = idx.get((a, k, (y, 'H1' if q == 'Q2' else '9M'))), idx.get((a, k, (y, 'Q1' if q == 'Q2' else 'H1')))
                    if q != 'Q1' and hi and lo and hi[0]['version'] == lo[0]['version'] == f['version']:
                        d = hi[0]['value'] - lo[0]['value']
                        out[(y, q)]['derived_check'] = d
                        if abs(d - f['value']) > f['unit'] * 3 // 2:
                            held.append(f"{a} {f['name']} {y}{q}: 원문 3개월 값과 누적 차감 값이 {d - f['value']:,}원 다름(확인 필요)")
                elif q != 'Q1':                              # v0.37.5: 3개월 값이 없고 누적만 있는 회사 — 같은 사업 구성일 때만 누적끼리 뺀다
                    hi, lo = idx.get((a, k, (y, 'H1' if q == 'Q2' else '9M'))), idx.get((a, k, (y, 'Q1' if q == 'Q2' else 'H1')))
                    pair = next(((x, z) for x in (hi or []) for z in (lo or []) if x['version'] == z['version']), None)
                    if pair:
                        x, z = pair
                        out[(y, q)] = {'value': x['value'] - z['value'], 'method': 'derived', 'name': hi[0]['name'], 'unit': x['unit'], 'sources': [src(x), src(z)], 'version': x['version'],
                                       'formula': f"{'반기' if q == 'Q2' else '9개월'} 누적 {x['value']:,} − {'1분기' if q == 'Q2' else '반기 누적'} {z['value']:,}"}
            fy, m9 = idx.get((a, k, (y, 'FY'))), idx.get((a, k, (y, '9M')))
            if fy and m9:
                pair = next(((x, z) for x in fy for z in m9 if x['version'] == z['version']), None)
                if pair:
                    x, z = pair
                    out[(y, 'Q4')] = {'value': x['value'] - z['value'], 'method': 'derived', 'name': x['name'], 'unit': x['unit'], 'sources': [src(x), src(z)], 'version': x['version'],
                                      'formula': f"연간 {x['value']:,} − 9개월 누적 {z['value']:,}"}
                else:
                    held.append(f"{a} {fy[0]['name']} {y}Q4: 연간 표와 9개월 누적 표의 사업 구성이 달라 빼지 않음(정의 변경)")
            elif fy and not m9 and y > years[0]:
                held.append(f"{a} {fy[0]['name']} {y}Q4: 9개월 누적 값이 없어 계산하지 않음")
    return {'cells': cells, 'held': held, 'index': idx}


def yoy(col, qs, axis, key, y, q):
    """전년 동기 대비. 같은 보고서의 당기·전기 칸(같은 정의)을 먼저 쓰고, Q4는 연간·3분기 보고서의 전기 칸으로 전년 Q4를 다시 만든다."""
    idx = qs['index']; cur = qs['cells'].get((axis, key), {}).get((y, q))
    if not cur:
        return None
    if q != 'Q4':
        c = [f for f in idx.get((axis, key, (y, q)), []) if f['role_in_report'] == 'current']
        p = [f for f in idx.get((axis, key, (y - 1, q)), []) if f['role_in_report'] == 'prior' and c and f['rcept_no'] == c[0]['rcept_no']]
        if c and p:
            g = growth_pct(c[0]['value'], p[0]['value'])
            return None if g is None else {'pct': g, 'cur': c[0]['value'], 'prev': p[0]['value'], 'basis': '같은 보고서의 당기·전기 칸', 'rcept_no': c[0]['rcept_no']}
        return None
    fy = [f for f in idx.get((axis, key, (y - 1, 'FY')), []) if f['role_in_report'] == 'prior']
    m9 = [f for f in idx.get((axis, key, (y - 1, '9M')), []) if f['role_in_report'] == 'prior']
    pair = next(((x, z) for x in fy for z in m9 if x['version'] == z['version'] == cur['version']), None)
    if not pair:
        return None
    prev = pair[0]['value'] - pair[1]['value']
    g = growth_pct(cur['value'], prev)
    return None if g is None else {'pct': g, 'cur': cur['value'], 'prev': prev, 'basis': '연간·3분기 보고서의 전기 칸으로 다시 만든 전년 4분기', 'rcept_no': pair[0]['rcept_no']}


# ---------------------------------------------------------------- v0.37.5 관문 세 번째 조건: 줄 이름 점검 · 대조 자료
_BAD_ROW = re.compile(r'내부\s*매출|총\s*매출|부문\s*간|제거|조정|연결\s*실체|합\s*계|소\s*계|^계$|고객|한\s*시점|기간에\s*걸쳐|외부\s*고객|보고\s*부문|^영업부문$|^매출액?$|^수익$|구성요소|^기업\s*전체|미배분|공시\s*금액|^[A-Za-z가-힣]\s*사$')
_CORP = re.compile(r'㈜|\(주\)|주식회사|유한회사|Co\.|Ltd|LTD|GmbH|Inc\.?$|Corp|LLC|S\.A\.|Sdn|Pte|종속기업|관계기업')
_REGION_MORE = ('국가', '지역', '외국', '국외', '대한민국', '아메리카', '오세아니아', '중동', '대만', '캐나다', '호주', '독일', '영국', '프랑스', '러시아', '브라질', '멕시코', '인도네시아', '싱가포르', '홍콩', '태국', '말레이시아', '폴란드', '헝가리', '터키', '튀르키예', '수출', '내수')


def name_issues(axis, names, company_name='', dup=False):
    """한 축(사업부·제품·지역)의 줄 이름이 그 축답게 읽혔는지. 문제가 있으면 이유 목록(없으면 []). 합계가 맞아도 줄을 잘못 읽을 수 있어 따로 본다."""
    names = [n for n in names if n]
    out = []
    if dup:
        out.append('같은 표 안에 같은 이름의 줄이 두 번 있음')
    if len(set(re.sub(r'\s+', '', n) for n in names)) < 2:
        out.append('구분이 1개뿐임')
    bad = sorted({n for n in names if _BAD_ROW.search(n)})
    if bad:
        out.append('합계·조정·고객 같은 줄이 구분으로 읽힘: ' + ', '.join(bad[:3]))
    corp = sorted({n for n in names if _CORP.search(n) or (company_name and re.sub(r'\s+', '', n) == re.sub(r'\s+', '', company_name))})
    if corp:
        out.append('회사 이름이 구분으로 읽힘: ' + ', '.join(corp[:3]))
    if axis == 'region' and names:
        odd = sorted(n for n in set(names) if not (any(w in n for w in REGION_WORDS + _REGION_MORE) or n.strip().startswith('기타')))
        if odd:
            out.append('지역 이름으로 보이지 않는 줄이 있음: ' + ', '.join(odd[:3]))
    return out


def revenue_from_facts(rows):
    """공시 재무(financial_fact) → {'YYYY-MM-DD': 단독분기 연결 매출}. 1~3분기는 보고서의 3개월 값, 4분기는 연간 − 3분기 누적(둘 다 있을 때만)."""
    R = {}
    for r in rows:
        if r.get('account_id') == 'ifrs-full_Revenue' and r.get('fs_div') == 'CFS' and r.get('amount') not in (None, ''):
            ytd = r.get('amount_ytd')
            R[(int(r['fiscal_year']), str(r['report_code']))] = (int(float(r['amount'])), int(float(ytd)) if ytd not in (None, '') else None)
    out = {}
    for (y, rc), (a, ytd) in R.items():
        if rc == '11013': out[f'{y}-03-31'] = a
        elif rc == '11012': out[f'{y}-06-30'] = a
        elif rc == '11014': out[f'{y}-09-30'] = a
        elif rc == '11011' and R.get((y, '11014'), (None, None))[1] is not None: out[f'{y}-12-31'] = a - R[(y, '11014')][1]
    return out


MIN_MATCH = 4          # 자격 관문: 독립 자료(분기 연결 매출)와 맞아야 하는 최소 분기 수


def qualified(ticker, cutoff, revenue_by_period_end, root=None, company_name=''):
    """자격 관문을 거친 결과(직렬화 가능한 묶음). 통과 조건 — 둘 다:
    ① 설명 안 되는 합계 불일치(계약 X) 0건  ② 분기 연결 합계가 독립 자료의 분기 매출과 MIN_MATCH개 이상 대조되고 모두 일치.
    revenue_by_period_end: {'2025-09-30': 원 단위 매출, …} (Neon 분기 재무 사본)"""
    col = collect(ticker, cutoff, root)
    out = {'company': ticker, 'rule': RULE, 'qualified': False, 'reasons': [], 'docs': col['docs'], 'held': []}
    if not col['docs']:
        out['reasons'].append('기준 날짜 이전의 정기보고서가 DART 원문 사본에 없음'); return out
    if not col['tables']:
        out['reasons'].append('정기보고서 주석에서 부문별 매출 표를 찾지 못함'); return out
    qs = quarters(col)
    con = {}
    for t in col['tables']:
        con[t['contract']] = con.get(t['contract'], 0) + 1
    out['tables'] = {'count': len(col['tables']), 'A': con.get('A', 0), 'B': con.get('B', 0), 'C': con.get('C', 0), 'X': con.get('X', 0),
                     'exact': sum(1 for t in col['tables'] if t['residual'] == 0)}
    if con.get('X'):
        out['reasons'].append(f"항목 합과 합계가 맞지 않는 표가 {con['X']}개 있음(일부 공시 표시도 없음)")
    end = {'Q1': '03-31', 'Q2': '06-30', 'Q3': '09-30', 'Q4': '12-31'}
    tot = next((qs['cells'][(a, '(연결 합계)')] for a in ('segment', 'product', 'region') if (a, '(연결 합계)') in qs['cells']), {})
    n = ok = 0; bad = []
    for (y, q), v in sorted(tot.items()):
        ref = revenue_by_period_end.get(f'{y}-{end[q]}')
        if ref is None:
            continue
        n += 1
        if abs(ref - v['value']) <= max(1, v['unit'] // 2):
            ok += 1
        else:
            bad.append(f'{y}{q}')
    out['independent'] = {'compared': n, 'matched': ok, 'mismatched': bad}
    if n < MIN_MATCH:
        out['reasons'].append(f'분기 연결 합계를 독립 자료(분기 재무)와 대조할 수 있는 분기가 {n}개뿐임(최소 {MIN_MATCH}개 필요)')
    elif ok < n:
        out['reasons'].append(f"분기 연결 합계가 독립 자료(분기 재무)와 다른 분기가 있음: {', '.join(bad[:6])}")
    if out['reasons']:
        return out
    # 관문 ③ 줄 이름 점검 — 축마다 따로. 문제가 있는 축은 값을 넘기지 않는다
    out['axes_held'] = []; drop = set()
    for axis in sorted({a for a, k in qs['cells'] if k != '(연결 합계)'}):
        nm = [c['name'] for (a, k), cells in qs['cells'].items() if a == axis and k != '(연결 합계)' for c in cells.values()]
        dup = any(t['axis'] == axis and len(set(t['names'])) < len(t['names']) for t in col['tables'])
        why = name_issues(axis, nm, company_name, dup)
        if why:
            drop.add(axis); out['axes_held'].append({'axis': axis, 'reasons': why})
    if not {a for a, k in qs['cells'] if k != '(연결 합계)'} - drop:
        out['reasons'].append('줄 이름 점검을 통과한 구분이 없음 — ' + ' / '.join(f"{x['axis']}: {'; '.join(x['reasons'])}" for x in out['axes_held'])); return out
    # 관문 ④ 최신성 — 가장 최근 정기보고서보다 두 분기 이상 뒤처지면 값을 넘기지 않는다
    qi = lambda y, q: y * 4 + {'Q1': 0, 'Q2': 1, 'H1': 1, 'Q3': 2, 'Q4': 3, 'FY': 3}[q]
    newest = max((qi(*rp) for rp in (report_period(d['report_nm']) for d in col['docs']) if rp), default=None)
    last = max((qi(y, q) for (a, k), cells in qs['cells'].items() if k != '(연결 합계)' and a not in drop for (y, q) in cells), default=None)
    if newest is not None and last is not None and newest - last >= 2:
        out['reasons'].append(f'가장 최근 정기보고서보다 {newest - last}개 분기 뒤의 값까지만 읽힘(최근 보고서의 표를 읽지 못함)'); return out
    out['lag_quarters'] = (newest - last) if newest is not None and last is not None else None
    out['qualified'] = True
    rows = []
    for (axis, key), cells in sorted(qs['cells'].items()):
        if key == '(연결 합계)' or axis in drop:
            continue
        for (y, q), c in sorted(cells.items()):
            g = yoy(col, qs, axis, key, y, q)
            rows.append({'axis': axis, 'key': key, 'name': c['name'], 'year': y, 'q': q, 'value': c['value'], 'method': c['method'], 'formula': c.get('formula'),
                         'sources': [{k: s[k] for k in ('rcept_no', 'report', 'url')} for s in c['sources']], 'yoy': g})
    out['quarters'] = rows
    out['totals'] = [{'year': y, 'q': q, 'value': v['value']} for (y, q), v in sorted(tot.items())]
    dc = [1 for cells in qs['cells'].values() for c in cells.values() if 'derived_check' in c]
    out['checks'] = {'reported_vs_derived': len(dc)}
    out['held'] = qs['held']
    return out
