"""Broker report forecast candidates (external forecasts, unapproved until a person approves).

Extraction is code-first: the yearly 매출액/영업이익 table in the PDF text is parsed by
rules, never chosen by a model. Every candidate keeps the PDF hash, page and the exact
text line it came from. Past-year columns in the same table are compared with the N01
official facts (a free "report reliability" check).

Nothing here merges several brokers into one number. Statistics are shown side by side
with the count and the list of reports.
"""
import hashlib
import json
import os
import re
from decimal import Decimal
from pathlib import Path
from statistics import median
from .util import now, digest

ROOT = Path(__file__).resolve().parents[1]
BASE_YEAR = 2025
UNIT_MULT = {'십억원': Decimal(1000), '조원': Decimal(1000000), '억원': Decimal(100), '백만원': Decimal(1)}
METRICS = {'매출액': 'revenue', '영업이익': 'operatingProfit'}
EXTRACTOR = 'v2'   # v2: 행 이름 정확 일치 우선 · 연도가 겹치는 비교표(변경 전/후·컨센서스) 제외 · 글자 추출 캐시
# 행 이름: 앞에 다른 한글이 붙지 않은 것만 '정확'. 예) '조정영업이익'은 정확 일치가 아니다.
EXACT_LABELS = {'revenue': ['매출액', '순매출액'], 'operatingProfit': ['영업이익']}
LABELS = {'revenue': '매출액', 'operatingProfit': '영업이익'}


def broker_dir():
    return Path(os.environ.get('MODU_NODES_BROKER_DIR') or ROOT.parent / '_sources' / 'broker_reports')


def load_manifest(d):
    p = d / 'manifest.json'
    if not p.exists():
        return {}
    m = json.loads(p.read_text(encoding='utf-8'))
    return {f['파일명']: f for f in m.get('files', [])}


def report_ticker(meta):
    """manifest 「종목」 칸(예: 삼성전자(005930)) → 6자리 종목코드."""
    m = re.search(r'\(([0-9][0-9A-Z]{5})\)', str((meta or {}).get('종목') or ''))   # 신규 상장 영문 혼합 코드(예: 0126Z0) 포함
    return m.group(1) if m else None


def _num(s):
    s = s.replace(',', '').strip()
    neg = s.startswith('(') and s.endswith(')')
    s = s.strip('()')
    try:
        v = Decimal(s)
    except Exception:
        return None
    return -v if neg else v


YEAR_SEQ = re.compile(r'((?:20\d\d[AEFP]?\s+){2,}20\d\d[AEFP]?)')
NUM = r'\(?-?[\d,]+(?:\.\d+)?\)?'


def _unit_near(text, pos):
    win = text[max(0, pos - 400): pos + 600]
    m = re.search(r'(십억\s?원|조\s?원|백만\s?원|억\s?원)', win)
    return m.group(1).replace(' ', '') if m else None


def _units_near(text, pos):
    win = text[max(0, pos - 300): pos + 400]
    found = [m.group(1).replace(' ', '') for m in re.finditer(r'(십억\s?원|조\s?원|백만\s?원|억\s?원)', win)]
    order = []
    for u in found + ['십억원', '조원', '억원', '백만원']:
        if u not in order:
            order.append(u)
    return order


def _row(after, labels, n_years, exact):
    """한 지표의 행을 찾는다. exact=True면 앞에 한글이 붙지 않은 행 이름만. (값, 인용, 실제 행 이름) 또는 None."""
    pre = r'(?<![가-힣])' if exact else r'([가-힣]*)'
    for kor in labels:
        rm = re.search(pre + '(' + kor + r')[^0-9\-\(]{0,20}((?:' + NUM + r'\s+){' + str(n_years - 1) + r',}' + NUM + ')', after)
        if rm:
            label = (rm.group(1) + rm.group(2)) if not exact else rm.group(1)
            return rm.group(rm.lastindex), rm.group(0), label
    return None


def find_tables(pages):
    """All yearly tables that have both 매출액 and 영업이익 rows and at least one forecast year.
    v2: 같은 연도가 두 번 이상 나오는 머리글(변경 전/후·컨센서스 비교표)은 쓰지 않는다. 행 이름은 정확 일치를 먼저 찾고,
    없을 때만 앞에 다른 말이 붙은 행('조정영업이익' 등)을 쓰되 label_exact=False로 표시한다."""
    out = []
    for pno, raw in enumerate(pages, 1):
        flat = re.sub(r'\s+', ' ', raw)
        for hm in YEAR_SEQ.finditer(flat):
            years = hm.group(1).split()
            if len({y[:4] for y in years}) != len(years):
                continue                                            # 비교표: 연도가 겹침
            after = flat[hm.end(): hm.end() + 2500]
            rows, quotes, labels = {}, {}, {}
            for key, cands in EXACT_LABELS.items():
                hit = _row(after, cands, len(years), True) or _row(after, [cands[-1] if key == 'operatingProfit' else cands[0]], len(years), False)
                if not hit:
                    continue
                numstr, q, label = hit
                vals = numstr.split()
                vals = vals[-len(years):] if len(vals) > len(years) else vals  # annual columns sit at the right
                parsed = {y: (_num(v), v) for y, v in zip(years, vals) if _num(v) is not None}
                if parsed:
                    rows[key] = parsed
                    quotes[key] = (hm.group(1).strip() + ' … ' + q.strip())[:240]
                    labels[key] = label
            if 'revenue' in rows and 'operatingProfit' in rows and any(
                    re.search(r'[EF]$', y) or int(y[:4]) > BASE_YEAR for y in years):
                out.append({'page': pno, 'years': years, 'units': _units_near(flat, hm.start()), 'rows': rows, 'quote': quotes,
                            'labels': labels, 'label_exact': all(labels[k] in EXACT_LABELS[k] for k in labels),
                            'scope': '연결' if re.search(r'(K-?IFRS|IFRS)\s?연결|연결\s?기준|\(연결\)', flat) else '연결(추정)'})
    return out


def _past_checks(table, unit, facts):
    mult = UNIT_MULT[unit]
    checks = []
    for metric, row in table['rows'].items():
        for ylabel, (val, raw) in row.items():
            fy = int(ylabel[:4])
            if re.search(r'[EF]$', ylabel) or fy > BASE_YEAR:
                continue
            f = (facts or {}).get(f'{table.get("ticker") or "005930"}:{fy}:{metric}')
            if f:
                fact = Decimal(f['value'])
                checks.append({'year': fy, 'metric': metric, 'broker_value_mn': format(val * mult, 'f'), 'fact_value_mn': f['value'],
                               'match': abs(val * mult - fact) <= mult / 2 + 1, 'fact_id': f['fact_id']})
    return checks


def choose_table(tables, facts):
    """Pick (table, unit, checks, how). Unit is the one whose past columns match N01; precision breaks ties."""
    best = None
    for t in tables:
        for rank, unit in enumerate(t['units']):
            checks = _past_checks(t, unit, facts)
            allok = bool(checks) and all(c['match'] for c in checks)
            score = (allok, bool(checks) and not allok is False, -UNIT_MULT[unit], -rank, -t['page'])
            # v1 순서(검증 통과: 앞쪽 본문 표 우선)를 그대로 두고, 행 이름 정확 일치만 둘째 기준으로 더한다.
            score = (1 if allok else 0, 1 if t.get('label_exact', True) else 0, 1 if not checks else 0, -int(UNIT_MULT[unit]), -rank, -t['page'])
            if best is None or score > best[0]:
                how = '과거 실적이 공식 원문과 맞는 단위로 확정' if allok else ('과거 실적 열이 없어 표 근처 단위 표기로 추정' if not checks else '과거 실적 불일치')
                best = (score, t, unit, checks, how)
    return best[1:] if best else (None, None, [], '')


def find_doc_unit(pages):
    for raw in pages[:3]:
        m = re.search(r'단위\s?[:：]?\s?(십억\s?원|조\s?원|백만\s?원|억\s?원)', raw)
        if m:
            return m.group(1).replace(' ', '')
    return None


def find_target(pages, tp):
    """Quote for the target price stated in the manifest (already human-checked)."""
    if not tp:
        return None, None
    n = int(tp)
    pats = [f'{n:,}', str(n), f'{n // 10000}만']
    for pno, raw in enumerate(pages, 1):
        flat = re.sub(r'\s+', ' ', raw)
        for p in pats:
            for m in re.finditer(re.escape(p), flat):
                ctx = flat[max(0, m.start() - 60): m.end() + 20]
                if re.search(r'목표주가|TP|Target', ctx):
                    return pno, ctx.strip()
    return None, None


def find_prior_target(pages):
    for pno, raw in enumerate(pages[:2], 1):
        flat = re.sub(r'\s+', ' ', raw)
        m = re.search(r'목표주가[^.。]{0,40}?\(?기존\s?([\d,]+)\s?(만)?\s?원\)?', flat)
        if m:
            v = int(m.group(1).replace(',', '')) * (10000 if m.group(2) else 1)
            return v, pno, m.group(0)[:120]
    return None, None, None


def find_target_multiple(pages):
    for pno, raw in enumerate(pages[:3], 1):
        flat = re.sub(r'\s+', ' ', raw)
        m = re.search(r'(Target|목표|적용)[^0-9]{0,12}(P/E|P/B|PER|PBR|EV/EBITDA)[^0-9]{0,10}([\d.]+)\s?(배|x|X)', flat)
        if m:
            return f'{m.group(2)} {m.group(3)}배', pno, m.group(0)
    return None, None, None


def internal_mismatch(chosen, unit, tables, facts, tol=Decimal('0.01')):
    """같은 보고서의 다른 표(과거 열이 공시와 맞는 표)가 같은 전망 연도에 1% 넘게 다른 값을 적었는지.
    예) 본문 분기 표의 2027F 영업이익과 뒤쪽 요약 재무제표의 2027F가 다른 경우 — 증권사가 한쪽만 고친 것. 사람 확인으로 보낸다."""
    out = []
    base = {(m, int(y[:4])): v * UNIT_MULT[unit] for m, row in chosen['rows'].items() for y, (v, _) in row.items()
            if re.search(r'[EF]$', y) or int(y[:4]) > BASE_YEAR}
    for t in tables:
        if t is chosen:
            continue
        for u in t['units']:
            checks = _past_checks(t, u, facts)
            if not (checks and all(c['match'] for c in checks)):
                continue
            for m, row in t['rows'].items():
                for y, (v, raw) in row.items():
                    k = (m, int(y[:4]))
                    if k in base and base[k] and abs(v * UNIT_MULT[u] - base[k]) > abs(base[k]) * tol:
                        out.append({'metric': m, 'year': k[1], 'chosen_mn': format(base[k], 'f'), 'other_mn': format(v * UNIT_MULT[u], 'f'),
                                    'other_page': t['page']})
            break
    return out


def _pages(pdf, data, sha):
    """PDF 쪽별 글자. 같은 파일(sha256)은 한 번만 읽고 broker_dir/_textcache에 남긴다(이어 스캔)."""
    import gzip
    cp = pdf.parent / '_textcache' / sha[:2] / f'{sha}.json.gz'
    if cp.exists():
        try:
            return json.loads(gzip.decompress(cp.read_bytes()).decode('utf-8'))
        except Exception:
            pass
    import pymupdf
    doc = pymupdf.open(stream=data, filetype='pdf')
    pages = [p.get_text() for p in doc]
    cp.parent.mkdir(parents=True, exist_ok=True)
    tmp = cp.with_suffix('.tmp')
    tmp.write_bytes(gzip.compress(json.dumps(pages, ensure_ascii=False).encode('utf-8')))
    tmp.replace(cp)
    return pages


def scan(facts=None):
    """Scan the broker folder. Returns (reports, candidates). Requires PyMuPDF."""
    import pymupdf  # imported lazily so the rest of the app runs without it
    d = broker_dir()
    man = load_manifest(d)
    reports, cands = [], []
    for pdf in sorted(d.glob('*.pdf')):
        data = pdf.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        meta = man.get(pdf.name, {})
        rep = {'file': pdf.name, 'sha256': sha, 'broker': meta.get('증권사', ''), 'analyst': meta.get('애널리스트', ''),
               'report_date': meta.get('보고서일', pdf.name[:8]), 'title': meta.get('제목', ''), 'opinion': meta.get('투자의견', ''),
               'target_price': meta.get('목표주가(원)', ''), 'source_url': meta.get('원문주소', ''), 'status': 'ok', 'notes': [],
               'manifest_sha_match': (meta.get('sha256') == sha) if meta else None, 'ticker': report_ticker(meta)}
        if meta and meta.get('sha256') != sha:
            rep['status'] = 'hash_mismatch'
            rep['notes'].append('manifest의 해시와 파일 해시가 다릅니다. 파일이 바뀌었을 수 있습니다.')
        pages = _pages(pdf, data, sha)
        rep['pages'] = len(pages)
        rep['tp_page'], rep['tp_quote'] = find_target(pages, rep['target_price'])
        rep['tp_prior'], rep['tp_prior_page'], rep['tp_prior_quote'] = find_prior_target(pages)
        rep['multiple'], rep['multiple_page'], rep['multiple_quote'] = find_target_multiple(pages)
        if not rep['target_price']:
            rep['notes'].append('목표주가가 본문 텍스트에 없습니다(이미지일 수 있음).')
        tables = find_tables(pages)
        for tb in tables:
            tb['ticker'] = rep['ticker']
        t, unit, checks, how = choose_table(tables, facts)
        rep['checks'] = checks
        if not t:
            rep['status'] = 'no_table' if rep['status'] == 'ok' else rep['status']
            rep['notes'].append('연도별 매출·영업이익 표를 본문 텍스트에서 찾지 못했습니다(표가 그림일 수 있음).')
            reports.append(rep)
            continue
        mult = UNIT_MULT[unit]
        rep['internal_mismatch'] = internal_mismatch(t, unit, tables, facts)
        rep.update(table_page=t['page'], table_years=t['years'], unit=unit, unit_basis=how, scope=t['scope'],
                   row_labels=t.get('labels', {}), label_exact=t.get('label_exact', True), extractor=EXTRACTOR)
        for metric, row in t['rows'].items():
            for ylabel, (val, raw) in row.items():
                fy = int(ylabel[:4])
                if not (re.search(r'[EF]$', ylabel) or fy > BASE_YEAR):
                    continue
                mn = val * mult
                cands.append({'id': f"{sha[:12]}:{metric}:{fy}", 'file': pdf.name, 'sha256': sha, 'broker': rep['broker'],
                              'report_date': rep['report_date'], 'metric': metric, 'metric_label': LABELS[metric], 'fiscal_year': fy,
                              'year_label': ylabel, 'value_mn': format(mn, 'f'), 'value_original': raw, 'unit_original': unit,
                              'scope': t['scope'], 'page': t['page'], 'quote': t['quote'][metric], 'extraction': 'code-table',
                              'row_label': t.get('labels', {}).get(metric, ''), 'extractor': EXTRACTOR})
        ok = [c['match'] for c in rep['checks']]
        rep['past_check'] = 'match' if ok and all(ok) else ('mismatch' if ok else 'not_available')
        if rep['past_check'] == 'mismatch':
            rep['notes'].append('표의 과거 실적이 공식 원문(N01)과 다릅니다. 단위나 열 위치를 확인하세요.')
        for c in cands:
            if c['file'] == pdf.name:
                c['confidence'] = 'high' if rep['past_check'] == 'match' else 'medium'
        reports.append(rep)
    return reports, cands


def stats(values):
    vs = sorted(Decimal(v) for v in values)
    if not vs:
        return None
    return {'count': len(vs), 'min': str(vs[0]), 'median': str(median(vs)), 'max': str(vs[-1])}


# ---------------------------------------------------------------- v0.18 T2: 받은 편지함 → 등록 도우미
BROKERS = ['미래에셋증권', '대신증권', '키움증권', '유진투자증권', '신한투자증권', 'SK증권', '교보증권', '한화투자증권', '하나증권', 'DS투자증권',
           'NH투자증권', 'KB증권', '삼성증권', '한국투자증권', '메리츠증권', '하이투자증권', 'iM증권', 'IBK투자증권', '현대차증권', '유안타증권',
           'DB금융투자', 'DB증권', '이베스트투자증권', 'LS증권', '신영증권', '부국증권', '상상인증권', 'BNK투자증권', '다올투자증권', '케이프투자증권',
           '한양증권', '흥국증권', '리딩투자증권', '카카오페이증권', '토스증권']


def inbox_dir():
    return broker_dir() / 'inbox'


def _manifest_raw(d):
    p = d / 'manifest.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'subject': '증권사 보고서', 'files': []}


def _first_text(data, pages=2):
    import pymupdf
    doc = pymupdf.open(stream=data, filetype='pdf')
    return '\n'.join(doc[i].get_text() for i in range(min(pages, len(doc)))), len(doc)


def guess(text, filename=''):
    """첫 쪽 글자에서 등록 칸을 추정한다(사람이 확인·고친 뒤 등록). 틀릴 수 있다."""
    g = {}
    m = re.search(r'(20\d{2})(\d{2})(\d{2})', filename) or re.search(r'(20\d{2})[.\-/]\s?(\d{1,2})[.\-/]\s?(\d{1,2})', text)
    if m:
        g['report_date'] = f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
    for b in sorted(BROKERS, key=len, reverse=True):
        if b in text or b in filename:
            g['broker'] = b
            break
    m = re.search(r'[A(（]?(\d{6})[)）]?\s', text) or re.search(r'\((\d{6})\)|A(\d{6})', text)
    code = next((x for x in (m.groups() if m else []) if x), None)
    if not code:
        try:
            from .market import name_index
            idx = name_index()
            flat = text[:1500]
            for nm in sorted(idx, key=len, reverse=True):
                if len(nm) >= 2 and nm in flat:
                    code = idx[nm]; break
        except Exception:
            pass
    if code:
        g['ticker'] = code
    m = re.search(r'(매수|BUY|Buy|Strong Buy|Outperform|중립|HOLD|Hold|Neutral|Trading Buy|Not Rated)', text)
    if m:
        g['opinion'] = m.group(1)
    m = re.search(r'목표주가[^0-9]{0,12}([\d,]{5,})\s?원', text)
    if m:
        g['target_price'] = m.group(1).replace(',', '')
    bad = r'\d{4}[.\-]\s?\d|www|\.com|\d{6}|연구원|Analyst|Analysis|Company|Memo|목표|투자의견|\d+월\s?\d+일|^[\d(]|Research|리서치'
    lines = [l.strip() for l in text.splitlines() if 6 <= len(l.strip()) <= 60 and not re.search(bad, l.strip()) and '증권' not in l]
    if lines:
        g['title'] = lines[0]
    return g


def inbox_items():
    d, ib = broker_dir(), inbox_dir()
    if not ib.exists():
        return []
    have = {f.get('sha256') for f in _manifest_raw(d).get('files', [])}
    out = []
    for pdf in sorted(ib.glob('*.pdf')):
        data = pdf.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        item = {'file': pdf.name, 'sha256': sha, 'bytes': len(data), 'registered': sha in have}
        if not item['registered']:
            try:
                text, n = _first_text(data)
                item.update(pages=n, guess=guess(text, pdf.name))
            except Exception as e:                       # 글자가 없는(그림) PDF 등
                item.update(pages=None, guess=guess('', pdf.name), note=f'본문 글자를 읽지 못했어요({type(e).__name__}). 칸을 직접 채워 주세요.')
        out.append(item)
    return out


def _clean(s):
    return re.sub(r'[^0-9A-Za-z가-힣]', '', str(s or ''))


def current_name(name):
    """예전 파일 이름(v0.22 이름 바꾸기 전)을 지금 이름으로. 저장된 워크플로가 옛 이름을 가리켜도 그대로 돌게 한다."""
    for f in _manifest_raw(broker_dir()).get('files', []):
        if f.get('이전 파일명') == name:
            return f['파일명']
    return name


def report_filename(report_date, ticker, company, broker, sha):
    """v0.22 보관 파일 이름: 날짜_종목코드_회사명_증권사_해시8.pdf. 종목코드·해시가 기준이고 회사명은 사람이 읽는 표시다."""
    nm = _clean(company) if company and company != ticker else ''
    parts = [report_date.replace('-', ''), ticker] + ([nm] if nm else []) + [_clean(broker), sha[:8]]
    return '_'.join(parts) + '.pdf'


def register(form):
    """inbox의 PDF를 보고서 폴더에 복사하고 manifest.json에 한 줄 더한다(원래 manifest는 처음 한 번 백업). 지우지 않는다."""
    import shutil
    from datetime import datetime, timezone
    d, ib = broker_dir(), inbox_dir()
    src = ib / Path(form['file']).name
    if not src.exists():
        raise ValueError('받은 편지함(inbox)에 그 파일이 없어요.')
    if not re.fullmatch(r'[0-9][0-9A-Z]{5}', form.get('ticker') or ''):
        raise ValueError('종목코드 6자리를 적어 주세요.')
    if not re.fullmatch(r'20\d{2}-\d{2}-\d{2}', form.get('report_date') or ''):
        raise ValueError('보고서 날짜를 YYYY-MM-DD로 적어 주세요.')
    if not (form.get('broker') or '').strip():
        raise ValueError('증권사 이름을 적어 주세요.')
    data = src.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    man = _manifest_raw(d)
    if any(f.get('sha256') == sha for f in man.get('files', [])):
        raise ValueError('이미 등록된 보고서예요(같은 파일 해시).')
    try:
        from .market import company_name
        nm = company_name(form['ticker'])
    except Exception:
        nm = form['ticker']
    broker = form['broker'].strip()
    name = report_filename(form['report_date'], form['ticker'], nm, broker, sha)
    shutil.copy2(src, d / name)
    if hashlib.sha256((d / name).read_bytes()).hexdigest() != sha:
        raise ValueError('복사한 파일의 해시가 다릅니다. 다시 시도해 주세요.')
    mp = d / 'manifest.json'
    if mp.exists() and not list(d.glob('manifest.json.bak-before-inbox*')):
        shutil.copy2(mp, d / f"manifest.json.bak-before-inbox-{datetime.now().strftime('%Y%m%d%H%M%S')}")
    rec = {'no': max([int(f.get('no') or 0) for f in man.get('files', [])] + [0]) + 1, '보고서일': form['report_date'], '증권사': broker,
           '애널리스트': '', '제목': (form.get('title') or '').strip(), '투자의견': (form.get('opinion') or '').strip(),
           '목표주가(원)': re.sub(r'\D', '', form.get('target_price') or ''), '목표주가 변화': '', '종목': f"{nm}({form['ticker']})",
           '파일명': name, 'sha256': sha, '쪽수': None, '원문주소': (form.get('source_url') or '').strip(),
           '확인 근거': (form.get('basis') or '').strip() or '사용자 등록(받은 편지함)',
           '저장 확인 시각(UTC)': datetime.now(timezone.utc).replace(microsecond=0).isoformat(), '원래 파일명': src.name}
    man.setdefault('files', []).append(rec)
    man['count'] = len(man['files'])
    tmp = d / 'manifest.json.tmp'
    tmp.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(mp)
    return rec


def filing_facts(exclude=('005930', '000660')):
    """manifest에 있는 다른 회사의 공시 API 연간 매출·영업이익(백만원) — 보고서 표의 과거 열 대조용.
    exclude: 저장 공식 원문(N01)으로 따로 대조하는 회사(앱 화면 기본값). 일괄 자동 승인은 exclude=()로 전부 공시 API를 쓴다."""
    from datetime import datetime, timezone, timedelta
    out = {}
    tickers = {report_ticker(f) for f in load_manifest(broker_dir()).values()} - {None, *exclude}
    if not tickers:
        return out
    try:
        from .market import company_filings
    except Exception:
        return out
    cut = datetime.now(timezone(timedelta(hours=9))).replace(microsecond=0).isoformat()
    for t in tickers:
        try:
            cf = company_filings(t, cut)
        except Exception:
            continue
        for f in cf['facts']:
            if f['metric'] in METRICS.values() and f.get('amount') not in (None, ''):
                out[f"{t}:{f['year']}:{f['metric']}"] = {'value': format(Decimal(str(f['amount'])) / Decimal(1000000), 'f'),
                                                         'fact_id': f"{t}:{f['year']}:{f['metric']}:api:{f.get('rcept_no')}"}
    return out
