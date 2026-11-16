"""v0.37.8 (전태 축, 규칙 valueup-v1 · capalloc-v1): 기업가치제고계획 목표 문장 · 소각 목표 대조 · 자본배분 연표.
숫자는 DART 원문 칸·문장 그대로이고, 분류 이름은 규칙에 따른 것이다. 좋고 나쁨·약속을 지켰는지는 판단하지 않는다."""
import html
import re
from . import promise as P

VALUEUP_RULE, CAPALLOC_RULE = 'valueup-v1', 'capalloc-v1'
SINCE = '2023-01-01'
MAX_ITEM = 160
_UNIT = re.compile(r'(?:KRW|USD|\$)\s*[\d,]+(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s*(?:조\s*원|천억\s*원|억\s*원|만\s*원|조|천억|억|만\s*주|천\s*주|주|원|%\s*p|%p|%|배|bp)(?![가-힣A-Za-z])')
_END = re.compile(r'^\d\.\s*(결정일자|조세특례|관련\s*자료|기타\s*투자판단)')
_SELF = re.compile(r'이행|성과')
_TARGET = re.compile(r'목표|계획|추진|방안|정책')
_PAST = re.compile(r'시현|(달성|기록|완료|실시|집행|취득|소각)(했|하였)|하였습니다|했습니다|하였음')
_SKIP = re.compile(r'https?://|^※|결정일자|게재일시|관련\s*웹페이지')
_CAT = (('환원', re.compile(r'배당|소각|자사주|자기주식|환원|TSR|DPS', re.I)), ('수익성', re.compile(r'ROE|ROA|ROIC|이익률|마진|PBR|수익성', re.I)),
        ('성장', re.compile(r'매출|성장|CAGR', re.I)))
_RETIRE_T = re.compile(r'(\d[\d,]*(?:\.\d+)?)\s*(억|만|천)?\s*주\s*(?:\([^)]{0,12}\)\s*)?(?:의\s*)?(?:자기주식|자사주|보통주)?\s*(?:을|를)?\s*(?:추가\s*)?소각')
_PLANNED = re.compile(r'예정|목표|계획|추진')
_DONE = re.compile(r'완료|달성|이행|시현|실적')
_COMP = re.compile(r'임직원|직원|임원|이사\s*보수|성과급|성과보상|성과금|보상|인센티브|상여|RSU|PSU|Stock\s*Grant|주식매수선택권|스톡옵션|우리사주|단체교섭|단체협상|임금', re.I)
_BULLET = re.compile(r'^(□|■|◆|●|○|-|ㆍ|·|•|\*|※|[①-⑳]|\(\d+\)|\d+[\.\)]|\[|<|[가-하]\.)')
OWN_EXCLUDE = re.compile(r'자회사의\s*주요\s*경영사항|종속회사의\s*주요\s*경영사항')
LIST_KINDS = (('배당', '환원', re.compile(r'현금ㆍ현물배당결정|현금·현물배당결정|주식배당결정')),
              ('시설투자', '투자', re.compile(r'신규시설투자')),
              ('타법인 지분 취득', '투자', re.compile(r'타법인주식및출자증권취득')),
              ('타법인 지분 처분', '재편', re.compile(r'타법인주식및출자증권처분')),
              ('합병·분할', '재편', re.compile(r'회사합병결정|회사분할결정|분할합병')),
              ('자산·영업 양수도', '재편', re.compile(r'유형자산양수|유형자산양도|영업양수|영업양도')),
              ('증자', '조달', re.compile(r'유상증자결정|무상증자결정')))


def _q(num, mul):
    v = float(num.replace(',', ''))
    return int(round(v * {'억': 100_000_000, '만': 10_000, '천': 1_000}.get(mul or '', 1)))


def _cut(t):
    return t if len(t) <= MAX_ITEM else t[:MAX_ITEM - 1] + '…'


def _lines(T):
    """표 칸 안에서 줄이 바뀌어 잘린 문장을 다시 잇는다: 글머리(□·-·①·1. 등)로 시작하지 않는 조각은 앞 줄에 붙인다."""
    out = []
    for t in T:
        t = html.unescape(t).strip()
        if out and not _BULLET.match(t) and not _END.match(t):
            out[-1] = out[-1] + ' ' + t
        else:
            out.append(t)
    return out


def plan_items(doc):
    """기업가치제고계획 원문 → 숫자·단위가 있는 문장들. mode: target(목표·계획) / self(회사가 적은 이행·성과 — 검증 전) / mixed(제목에 둘 다 있어 구분 안 됨)."""
    T = P.tokens(doc)
    s = next((i for i, t in enumerate(T) if re.match(r'^2\.\s*주요\s*내용', t)), None)
    if s is None:
        return [], '「주요 내용」 칸을 찾지 못함'
    e = next((i for i in range(s + 1, len(T)) if _END.match(T[i])), len(T))
    items, mode = [], 'target'
    for t in _lines(T[s + 1:e]):
        if _SKIP.search(t):
            continue
        if not _UNIT.search(t):
            a, b = bool(_SELF.search(t)), bool(_TARGET.search(t))
            mode = 'mixed' if a and b else 'self' if a else 'target' if b else mode
            continue
        cat = next((c for c, r in _CAT if r.search(t)), '기타')
        m = 'self' if mode != 'self' and _PAST.search(t) else mode       # 문장이 지난 일을 말하면(시현·하였습니다 등) 이행·성과로
        items.append({'text': _cut(t), 'mode': m, 'category': cat})
    return items, None


def retire_targets(items):
    """「N만주 (자기주식) 소각」처럼 주식 수 바로 뒤에 소각이 오는 목표 문장만. 지난 일을 말하는 문장(완료·달성·이행 등)은 빼고, 예정·목표·계획·추진이 있어야 한다."""
    out = []
    for it in items:
        t = it['text']
        if it['mode'] != 'target' or not _PLANNED.search(t) or _DONE.search(t):
            continue
        m = _RETIRE_T.search(t)
        if m:
            out.append({'text': t, 'qty': _q(m.group(1), m.group(2))})
    return out


def own(docs):
    keep = [d for d in docs if not OWN_EXCLUDE.search(d.get('report_nm') or '')]
    return keep, len(docs) - len(keep)


def valueup(ticker, cutoff, retires, root=None):
    """retires: promise.build(...)['retires'] (자기 회사 소각 결정, 정정 반영)."""
    from . import dartdocs as D
    docs, n_sub = own(D.find(ticker, 'valueup', cutoff, root))
    out = {'rule': VALUEUP_RULE, 'plans': [], 'latest': None, 'held': [], 'docs': []}
    if n_sub:
        out['held'].append(f'자회사 기업가치제고계획 {n_sub}건은 이 회사 것이 아니어서 쓰지 않음')
    for d in docs:
        files, meta = D.open_doc(d['rcept_no'], root)
        out['docs'].append({'rcept_no': d['rcept_no'], 'sha256': meta['sha256']})
        out['plans'].append({'rcept_no': d['rcept_no'], 'date': d['rcept_dt'], 'report_nm': d['report_nm'], 'url': d['url'], 'doc': max(files, key=lambda f: len(f[1]))[1]})
    if not out['plans']:
        return out
    parsed = [(p, *plan_items(p.pop('doc'))) for p in out['plans']]
    pick = next((x for x in reversed(parsed) if any(i['mode'] == 'target' for i in x[1])), None) or next((x for x in reversed(parsed) if x[1]), None) or parsed[-1]
    last, items, err = pick
    if err:
        out['held'].append(f"{last['report_nm']} ({last['date']}): {err}")
    if last is not out['plans'][-1]:
        out['held'].append(f"가장 최근 계획 공시({out['plans'][-1]['date']})의 본문에는 숫자가 있는 목표 문장이 없어(세부는 첨부 자료) {last['date']} 공시의 문장을 보임")
    tg = []
    for t in retire_targets(items):
        hit = [r for r in retires if r['rcept_dt'] >= last['date'] and (r['qty'] or 0) + (r['qty_other'] or 0) > 0]
        done = sum((r['qty'] or 0) + (r['qty_other'] or 0) for r in hit)
        tg.append({**t, 'retired_qty': done, 'pct': round(done / t['qty'] * 100, 1) if t['qty'] else None,
                   'retires': [{'date': r['rcept_dt'], 'qty': (r['qty'] or 0) + (r['qty_other'] or 0), 'url': r['url'], 'rcept_no': r['rcept_no']} for r in hit]})
    out['latest'] = {**last, 'items': items, 'retire_targets': tg, 'newest_date': out['plans'][-1]['date']}
    return out


def _sale(doc):
    T = P.tokens(doc)
    q, qo = P._pair(T, r'^1\.처분예정주식'); a, ao = P._pair(T, r'^3\.처분예정금액')
    return {'qty': (q or 0) + (qo or 0) or None, 'amount': (a or 0) + (ao or 0) or None, 'purpose': P._one(T, r'^5\.처분목적'),
            'to': P._one(T, r'^\d+\.처분상대방'), 'corrects': P._correction(T)}


def _trust(doc, report_nm):
    T = P.tokens(doc)
    if '해지' in (report_nm or ''):
        i = P._find(T, r'^1\.계약금액')
        amt = next((P._num(t) for t in T[i + 1:i + 4] if P._num(t)), None) if i >= 0 else None
        return {'amount': amt, 'purpose': P._one(T, r'^3\.해지목적'), 'cancel': True, 'corrects': P._correction(T)}
    return {'amount': P._one(T, r'^1\.계약금액', P._num), 'purpose': P._one(T, r'^3\.계약목적'), 'cancel': False, 'corrects': P._correction(T)}


def _group_by_purpose(purpose, default):
    return '보상' if purpose and _COMP.search(purpose) else default


def timeline(ticker, cutoff, pr, disclosures, root=None):
    """자본배분 연표. pr: promise.build 결과, disclosures: 사본 공시 목록(core.disclosure) 이 회사 행."""
    from . import dartdocs as D
    last = (cutoff or '9999')[:10]
    rows, held, src = [], [], []
    for r in pr['rows']:
        d = r['decision']
        if (r['filed'] or '') < SINCE:
            continue
        amt = r['planned_amount']
        rows.append({'date': r['filed'], 'kind': '자기주식 취득 결정', 'group': _group_by_purpose(d.get('purpose'), '환원'),
                     'content': f"{(d['qty'] or 0) + (d['qty_other'] or 0):,}주 · {amt / 1e8:,.0f}억원 예정" if amt else f"{(d['qty'] or 0) + (d['qty_other'] or 0):,}주",
                     'purpose': d.get('purpose') or '', 'url': d['url'], 'rcept_no': d['rcept_no'], 'corrected': bool(d.get('corrected')), 'from': 'original'})
    for t in pr['retires']:
        if t['rcept_dt'] < SINCE:
            continue
        q = (t['qty'] or 0) + (t['qty_other'] or 0)
        rows.append({'date': t['rcept_dt'], 'kind': '주식 소각 결정', 'group': '환원', 'content': f"{q:,}주" + (f" · {t['amount'] / 1e8:,.0f}억원" if t.get('amount') else ''),
                     'purpose': t.get('method') or '', 'url': t['url'], 'rcept_no': t['rcept_no'], 'corrected': bool(t.get('corrects')), 'from': 'original'})
    for kind, label, fn in (('treasury_sale', '자기주식 처분 결정', _sale), ('buyback_trust', '자기주식 신탁계약', None)):
        docs, n_sub = own(D.find(ticker, kind, cutoff, root))
        if n_sub:
            held.append(f'자회사 {label} {n_sub}건은 이 회사 것이 아니어서 쓰지 않음')
        byfirst = {}
        for d in docs:
            if d['rcept_dt'] < SINCE:
                continue
            files, meta = D.open_doc(d['rcept_no'], root)
            src.append({'rcept_no': d['rcept_no'], 'sha256': meta['sha256']})
            doc = max(files, key=lambda f: len(f[1]))[1]
            x = fn(doc) if fn else _trust(doc, d['report_nm'])
            key = x.get('corrects') or d['rcept_dt']
            if kind == 'treasury_sale':
                content = (f"{x['qty']:,}주" if x['qty'] else '수량 못 읽음') + (f" · {x['amount'] / 1e8:,.0f}억원" if x['amount'] else '')
                grp = _group_by_purpose((x.get('purpose') or '') + ' ' + (x.get('to') or ''), '재편')
                lab = label
            else:
                content = (f"{x['amount'] / 1e8:,.0f}억원" if x['amount'] else '금액 못 읽음') + (' 계약 종료' if x['cancel'] else ' 계약')
                grp = _group_by_purpose(x.get('purpose'), '환원'); lab = label + (' 해지' if x['cancel'] else ' 체결')
            row = {'date': key, 'kind': lab, 'group': grp, 'content': content, 'purpose': x.get('purpose') or '', 'url': d['url'], 'rcept_no': d['rcept_no'],
                   'corrected': key in byfirst, 'from': 'original'}
            if key in byfirst:
                rows.remove(byfirst[key])                    # 정정 공시는 최초 것을 덮는다(값은 정정 뒤)
            byfirst[key] = row; rows.append(row)
    # 원문을 받지 않은 종류: 사본 공시 목록의 제목만(금액은 원문 미수집)
    list_rows, n_sub, first = [], 0, None
    for d in sorted(disclosures, key=lambda r: r['rcept_no']):
        dt = str(d['rcept_dt'])[:10]
        if dt > last:
            continue
        first = min(first or dt, dt)
        nm = re.sub(r'\s+', '', d.get('report_nm') or '')
        hit = next(((k, g) for k, g, r in LIST_KINDS if r.search(nm)), None)
        if not hit:
            continue
        if OWN_EXCLUDE.search(d.get('report_nm') or '') or '자회사' in nm or '종속회사' in nm:
            n_sub += 1; continue
        if nm.startswith('[기재정정]') or nm.startswith('[첨부정정]'):
            prev = next((x for x in reversed(list_rows) if x['kind'] == hit[0]), None)
            if prev:
                prev['corrected'] = True
            continue
        list_rows.append({'date': dt, 'kind': hit[0], 'group': hit[1], 'content': '공시 목록 제목만(금액은 원문을 받지 않아 비움)', 'purpose': '', 'url': d.get('url'),
                          'rcept_no': d['rcept_no'], 'corrected': False, 'from': 'list'})
    rows += list_rows
    if n_sub:
        held.append(f'자회사·종속회사의 배당·투자·재편 공시 {n_sub}건은 이 회사 것이 아니어서 쓰지 않음')
    rows.sort(key=lambda r: (r['date'], r['rcept_no']))
    return {'rule': CAPALLOC_RULE, 'rows': rows, 'held': held, 'docs': src, 'list_from': first}
