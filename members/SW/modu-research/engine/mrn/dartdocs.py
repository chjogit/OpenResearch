"""v0.37 준비(D3): DART 공시 원문 근거층 — 한 경로로 받아 해시로 고정한다. AI 모델 호출 0회.

받기 (PC에서: _tools\\dart_docs\\run-dart-docs.cmd → python -m mrn.dartdocs fetch)
- 금융감독원 OpenDART 공식 API만 쓴다: 공시 목록 list.json → 원문 묶음 document.xml(ZIP).
- 키는 환경 변수 DART_API_KEY(또는 MODU_NODES_DART_KEY)에서만 읽는다. 화면·로그·저장 파일·오류 문장에 남기지 않는다.
- 결과: _sources\\dart_docs\\<접수번호>.zip(받은 그대로) + manifest.json(접수번호별 회사·보고서명·접수일·종류·크기·sha256·안의 파일 목록) + manifest.sha256.
- 다시 실행하면 이미 받은 것은 건너뛴다(같은 호출을 반복하지 않음). 하루 호출 한도(020)에 걸리면 멈추고 알려 준다.

읽기 (엔진)
- load_manifest() 가 manifest 해시를, open_doc() 이 원문 ZIP 해시를 매번 다시 대조한다. 다르면 쓰지 않는다(DartDocsError).
- find() 는 기준시점 이전에 접수된 공시만 돌려준다. 원문을 고치거나 채우지 않는다.
"""
import hashlib
import io
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIST_API = 'https://opendart.fss.or.kr/api/list.json'
DOC_API = 'https://opendart.fss.or.kr/api/document.xml'
TOOL_VERSION = 1
DEFAULT_FROM = '2023-01-01'
# 종류 → (공시 유형 pblntf_ty, 보고서명에 들어가야 하는 말, 들어가면 안 되는 말)
KINDS = {
    'periodic':         ('A', ('사업보고서', '반기보고서', '분기보고서'), ()),
    'buyback_decision': ('B', ('자기주식취득결정',), ('신탁',)),
    'buyback_trust':    ('B', ('자기주식취득신탁계약',), ()),
    'treasury_sale':    ('B', ('자기주식처분결정',), ()),
    'buyback_result':   ('E', ('자기주식취득결과보고서',), ()),
    'retire':           ('I', ('주식소각결정',), ()),
    'valueup':          ('I', ('기업가치제고계획',), ('예고',)),
    'dividend':         ('I', ('현금ㆍ현물배당결정', '현금·현물배당결정', '현금배당결정'), ()),     # v0.38 T1 (주식배당결정은 계산이 달라 따로)
    'prelim':           ('I', ('영업(잠정)실적',), ()),                                         # v0.38 T1 잠정실적(공정공시)
    'rights_issue':     ('B', ('유상증자결정',), ('자회사의주요경영사항', '종속회사의주요경영사항')),                                        # v0.38 T2-3 (무상증자는 계산이 달라 따로)
    'capital_reduction': ('B', ('감자결정',), ('자회사의주요경영사항', '종속회사의주요경영사항')),
    'convertible':      ('B', ('전환사채권발행결정', '신주인수권부사채권발행결정', '교환사채권발행결정'), ('자회사의주요경영사항', '종속회사의주요경영사항')),
    'pl_change':        ('I', ('매출액또는손익구조',), ('자회사의주요경영사항', '종속회사의주요경영사항')),
    'cv_adjust':        ('I', ('전환가액의조정', '행사가액의조정', '교환가액의조정'), ('자회사의주요경영사항', '종속회사의주요경영사항')),   # v0.38 T2-4b 리픽싱 대조용(계산하지 않음)
    'supply_contract':  ('I', ('단일판매ㆍ공급계약체결', '단일판매·공급계약체결'), ('자회사의주요경영사항', '종속회사의주요경영사항')),        # v0.39 T3-2(J31) 2등급 — 공시 숫자로만 계산
    'supply_cancel':    ('I', ('단일판매ㆍ공급계약해지', '단일판매·공급계약해지'), ('자회사의주요경영사항', '종속회사의주요경영사항')),
    'equity_deal':      ('I', ('타법인주식및출자증권취득결정', '타법인주식및출자증권처분결정'), ('자회사의주요경영사항', '종속회사의주요경영사항')),
    'equity_deal_major': ('B', ('타법인주식및출자증권양수결정', '타법인주식및출자증권양도결정'), ('자회사의주요경영사항', '종속회사의주요경영사항')),
}
KIND_LABEL = {'periodic': '정기보고서(사업·반기·분기)', 'buyback_decision': '자기주식 취득 결정', 'buyback_trust': '자기주식 신탁계약', 'treasury_sale': '자기주식 처분 결정',
              'buyback_result': '자기주식 취득 결과보고서', 'retire': '주식 소각 결정', 'valueup': '기업가치제고계획',
              'dividend': '현금·현물 배당 결정', 'prelim': '영업(잠정)실적',
              'rights_issue': '유상증자 결정', 'capital_reduction': '감자 결정', 'convertible': '전환사채·신주인수권부사채·교환사채 발행 결정',
              'pl_change': '매출액·손익구조 변경', 'cv_adjust': '전환가액·행사가액·교환가액의 조정',
              'supply_contract': '단일판매·공급계약 체결', 'supply_cancel': '단일판매·공급계약 해지',                   # v0.39 T3-2
              'equity_deal': '타법인 주식 취득·처분 결정', 'equity_deal_major': '타법인 주식 양수·양도 결정(주요사항보고서)'}
STATUS = {'010': '등록되지 않은 키', '011': '사용할 수 없는 키', '012': '접근할 수 없는 IP', '013': '조회된 데이터 없음', '014': '파일이 존재하지 않음',
          '020': '요청 제한 초과(하루 한도) — 내일 다시 실행하면 이어서 받습니다', '100': '필드의 부적절한 값', '800': '시스템 점검', '900': '정의되지 않은 오류'}


class DartDocsError(RuntimeError):
    def __init__(self, code, msg):
        super().__init__(msg); self.code = code


def docs_dir():
    return Path(os.environ.get('MODU_NODES_DART_DOCS') or ROOT.parent / '_sources' / 'dart_docs')


def api_key(env=None):
    env = os.environ if env is None else env
    return env.get('DART_API_KEY') or env.get('MODU_NODES_DART_KEY') or ''


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def http_get(url, timeout=60):
    """키가 든 주소는 오류 문장에 넣지 않는다."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'modu-research-nodes'}), timeout=timeout) as r:
            return r.read()
    except Exception as e:
        raise DartDocsError('network', f'DART 연결 실패({type(e).__name__})') from None


def classify(report_nm):
    nm = re.sub(r'\s+', '', report_nm or '')
    for k, (_ty, inc, exc) in KINDS.items():
        if any(w in nm for w in inc) and not any(w in nm for w in exc):
            return k
    return None


def _save_manifest(root, man):
    man['updated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    b = json.dumps(man, ensure_ascii=False, indent=1, sort_keys=True).encode('utf-8')
    tmp = root / 'manifest.json.tmp'
    tmp.write_bytes(b)
    for _try in range(40):                                  # v0.37.3: 다른 프로그램이 읽는 중이면 Windows가 막는다 → 0.25초씩 최대 10초 다시 시도
        try:
            os.replace(tmp, root / 'manifest.json'); break
        except PermissionError:
            if _try == 39:
                raise
            time.sleep(0.25)
    st = root / 'manifest.sha256.tmp'                          # v0.38: 해시 파일도 통째로 바꾼다(쓰는 도중의 빈 파일을 남이 읽지 않게)
    st.write_text(_sha(b) + '  manifest.json\n', encoding='utf-8')
    for _try in range(40):
        try:
            os.replace(st, root / 'manifest.sha256'); break
        except PermissionError:
            if _try == 39:
                raise
            time.sleep(0.25)


def load_manifest(root=None, verify=True):
    root = Path(root or docs_dir())
    p = root / 'manifest.json'
    if not p.exists():
        raise DartDocsError('no_docs', 'DART 원문 사본이 아직 없습니다. _tools\\dart_docs\\run-dart-docs.cmd 로 먼저 받아 주세요.')
    b = p.read_bytes()
    if verify:
        s = root / 'manifest.sha256'
        import time as _t

        def _want():                                       # v0.38: 받는 중에 해시 파일이 비어 있거나 잠겨 있으면 「아직 안 맞음」으로 보고 다시 읽는다(오류로 멈추지 않음)
            try:
                w = s.read_text(encoding='utf-8').split()
                return w[0] if w else None
            except OSError:
                return None
        for _try in range(10):                             # v0.37: 원문을 받는 중에는 목록과 해시 파일이 잠깐 어긋날 수 있어 잠시 뒤 다시 읽는다
            if _want() == _sha(b):
                break
            _t.sleep(0.3)
            try:
                b = p.read_bytes()
            except OSError:
                pass
        if _want() != _sha(b):
            raise DartDocsError('manifest_mismatch', 'DART 원문 사본의 목록(manifest)이 해시와 다릅니다. 사본이 바뀌었을 수 있어 쓰지 않습니다.')
    man = json.loads(b.decode('utf-8')); man['_manifest_sha256'] = _sha(b); man['_root'] = str(root)
    return man


def list_filings(key, corp_code, ty, start, end, get=http_get):
    out, page = [], 1
    while True:
        q = urllib.parse.urlencode({k: v for k, v in {'crtfc_key': key, 'corp_code': corp_code, 'bgn_de': start.replace('-', ''), 'end_de': end.replace('-', ''),
                                    'pblntf_ty': ty, 'page_no': page, 'page_count': 100}.items() if v is not None})     # ty=None: 모든 공시 유형
        b = get(f'{LIST_API}?{q}')
        try:                                                  # v0.38 T2-1b(F5): 점검 화면 등 JSON이 아닌 응답은 「응답을 읽지 못함」으로 멈춤 사유에 넣음(해석만 감쌈 — 다른 오류는 가리지 않음)
            d = json.loads(b.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            raise DartDocsError('dart_bad_response', 'DART 응답을 읽지 못했어요(점검 중이거나 일시 오류일 수 있어요).') from None
        if not isinstance(d, dict):
            raise DartDocsError('dart_bad_response', 'DART 응답을 읽지 못했어요(점검 중이거나 일시 오류일 수 있어요).')
        st = str(d.get('status'))
        if st == '013':
            return out
        if st != '000':
            raise DartDocsError('dart_' + st, f"DART 목록 조회 실패: {STATUS.get(st, d.get('message') or st)}")
        out += d.get('list') or []
        try:
            last = int(d.get('total_page') or 1)
        except (TypeError, ValueError):
            raise DartDocsError('dart_bad_response', 'DART 응답을 읽지 못했어요(점검 중이거나 일시 오류일 수 있어요).') from None
        if page >= last:
            return out
        page += 1


def fetch_doc(key, rcept_no, get=http_get):
    b = get(f"{DOC_API}?{urllib.parse.urlencode({'crtfc_key': key, 'rcept_no': rcept_no})}")
    if b[:2] != b'PK':
        m = re.search(rb'<status>(\d+)</status>', b) or re.search(rb'"status"\s*:\s*"(\d+)"', b)
        st = m.group(1).decode() if m else '900'
        raise DartDocsError('dart_' + st, f"원문 받기 실패({rcept_no}): {STATUS.get(st, st)}")
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        members = [{'name': i.filename, 'bytes': i.file_size} for i in z.infolist()]
    return b, members


def fetch(companies, kinds=None, start=DEFAULT_FROM, end=None, out_root=None, get=http_get, env=None, sleep=0.25, log=print, limit=None):
    """companies: [{'ticker','corp_code','name'}]. 받은 원문 수를 돌려준다."""
    key = api_key(env)
    if not key:
        raise DartDocsError('no_key', 'DART 키가 없습니다. modu-research-nodes\\local-env.cmd 에 DART_API_KEY 를 넣어 주세요.')
    kinds = list(kinds or KINDS); end = end or datetime.now().date().isoformat()
    root = Path(out_root or docs_dir()); root.mkdir(parents=True, exist_ok=True)
    try:
        man = load_manifest(root)
        man = {k: v for k, v in man.items() if not k.startswith('_')}
    except DartDocsError as e:
        if e.code != 'no_docs':
            raise
        man = {'tool': 'mrn.dartdocs', 'tool_version': TOOL_VERSION, 'origin': '금융감독원 OpenDART document.xml (받은 그대로, 고치지 않음)', 'docs': {}, 'listed': {}, 'failed': {}}
    docs, got = man['docs'], 0
    try:
        for c in companies:
            if not c.get('corp_code'):
                log(f"  {c['ticker']} {c.get('name', '')}: DART 고유번호(corp_code)가 없어 건너뜀"); continue
            want = []
            for ty in sorted({KINDS[k][0] for k in kinds}):
                for r in list_filings(key, c['corp_code'], ty, start, end, get):
                    k = classify(r.get('report_nm'))
                    if k in kinds:
                        want.append((r, k))
                time.sleep(sleep)
            old = man['listed'].get(c['ticker']) or {}            # v0.38: 종류를 나눠 받아도 앞서 받은 종류 기록을 지우지 않는다
            man['listed'][c['ticker']] = {**old, 'name': c.get('name'), 'from': min(old.get('from') or start, start), 'to': max(old.get('to') or end, end),
                                          'kinds': sorted(set(old.get('kinds') or []) | set(kinds)), 'count': len(want) if set(kinds) >= set(old.get('kinds') or []) else (old.get('count') or 0) + len(want),   # 대략값(표시용)
                                          'listed_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
            new = 0
            for r, k in sorted(want, key=lambda x: x[0]['rcept_no']):
                no = r['rcept_no']
                if no in docs and (root / docs[no]['file']).exists():
                    continue
                if limit is not None and got >= limit:
                    break
                try:
                    b, members = fetch_doc(key, no, get)
                except DartDocsError as e:
                    if e.code in ('dart_020', 'dart_010', 'dart_011', 'dart_012', 'network'):
                        raise
                    man['failed'][no] = {'ticker': c['ticker'], 'report_nm': r.get('report_nm'), 'code': e.code, 'reason': str(e)}; continue
                (root / f'{no}.zip').write_bytes(b)
                docs[no] = {'ticker': c['ticker'], 'corp_code': c['corp_code'], 'name': c.get('name'), 'report_nm': ' '.join((r.get('report_nm') or '').split()), 'rcept_dt': f"{r['rcept_dt'][:4]}-{r['rcept_dt'][4:6]}-{r['rcept_dt'][6:8]}",
                            'kind': k, 'filer': r.get('flr_nm'), 'remark': r.get('rm') or '', 'file': f'{no}.zip', 'bytes': len(b), 'sha256': _sha(b), 'members': members,
                            'fetched_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'url': f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={no}'}
                man['failed'].pop(no, None); got += 1; new += 1
                if got % 20 == 0:
                    _save_manifest(root, man)
                time.sleep(sleep)
            log(f"  {c['ticker']} {c.get('name', '')}: 대상 {len(want)}건 · 새로 받음 {new}건")
    finally:
        _save_manifest(root, man)
    return got


OWN_EXCLUDE = re.compile(r'자회사의\s*주요\s*경영사항|종속회사의\s*주요\s*경영사항')


def fetch_one(ticker, rcept_no, out_root=None, get=http_get, env=None, company=None):
    """v0.38 T1 접수번호 하나 받기(사용자가 직접 넣음). 그날의 DART 목록에서 이 접수번호를 찾아 보고서 이름·회사를 확인한 뒤에만 받는다.
    받은 원문은 대량 받기와 똑같이 받은 그대로·해시 고정으로 사본에 넣는다. 반환: (manifest 항목, 새로 받았는지)."""
    rcept_no = (rcept_no or '').strip()
    if not re.fullmatch(r'\d{14}', rcept_no):
        raise DartDocsError('bad_rcept_no', '접수번호는 숫자 14자리예요(예: 20260211800925).')
    root = Path(out_root or docs_dir()); root.mkdir(parents=True, exist_ok=True)
    try:
        man = load_manifest(root)
        man = {k: v for k, v in man.items() if not k.startswith('_')}
    except DartDocsError as e:
        if e.code != 'no_docs':
            raise
        man = {'tool': 'mrn.dartdocs', 'tool_version': TOOL_VERSION, 'origin': '금융감독원 OpenDART document.xml (받은 그대로, 고치지 않음)', 'docs': {}, 'listed': {}, 'failed': {}}
    d = man['docs'].get(rcept_no)
    if d and (root / d['file']).exists():
        if d['ticker'] != ticker:
            raise DartDocsError('other_company', f"접수번호 {rcept_no}는 {d.get('name') or d['ticker']}의 공시예요.")
        return d, False
    key = api_key(env)
    if not key:
        raise DartDocsError('no_key', 'DART 키가 없습니다. modu-research-nodes\\local-env.cmd 에 DART_API_KEY 를 넣어 주세요.')
    c = company or next(iter(_companies([ticker])), None)
    if not c or not c.get('corp_code'):
        raise DartDocsError('no_corp_code', f'{ticker}: DART 고유번호(corp_code)가 사본에 없어 받을 수 없어요.')
    day = f'{rcept_no[:4]}-{rcept_no[4:6]}-{rcept_no[6:8]}'
    row = None
    for ty in sorted({v[0] for v in KINDS.values()}) + [None]:     # 받는 종류의 유형 먼저, 없으면 모든 유형에서 한 번 더(지원하지 않는 종류라고 정확히 알리기 위해)
        row = next((r for r in list_filings(key, c['corp_code'], ty, day, day, get) if r.get('rcept_no') == rcept_no), None)
        if row:
            break
    if not row:
        raise DartDocsError('not_listed', f'{c.get("name") or ticker}의 {day} DART 공시 목록에서 접수번호 {rcept_no}를 찾지 못했어요. 회사·접수번호를 확인해 주세요.')
    nm = ' '.join((row.get('report_nm') or '').split())
    if OWN_EXCLUDE.search(nm):
        raise DartDocsError('subsidiary', f'「{nm}」은(는) 자회사의 공시라 이 회사의 숫자로 계산하지 않아요.')
    k = classify(nm)
    if k is None:
        raise DartDocsError('unsupported_kind', f'「{nm}」은(는) 아직 계산하는 공시 종류가 아니에요(지금은 소각·자기주식·배당·잠정실적·손익구조 변경·유상증자·감자·전환사채류 등).')
    b, members = fetch_doc(key, rcept_no, get)
    (root / f'{rcept_no}.zip').write_bytes(b)
    d = {'ticker': ticker, 'corp_code': c['corp_code'], 'name': c.get('name'), 'report_nm': nm, 'rcept_dt': f"{row['rcept_dt'][:4]}-{row['rcept_dt'][4:6]}-{row['rcept_dt'][6:8]}",
         'kind': k, 'filer': row.get('flr_nm'), 'remark': row.get('rm') or '', 'file': f'{rcept_no}.zip', 'bytes': len(b), 'sha256': _sha(b), 'members': members,
         'fetched_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'url': f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}', 'added_by': 'manual'}
    man['docs'][rcept_no] = d
    man['failed'].pop(rcept_no, None)
    _save_manifest(root, man)
    return d, True


MAN_LOCK = threading.RLock()                    # v0.38 T2-4e: 자동 받기와 접수번호로 받기가 사본 목록(manifest)을 동시에 쓰지 않게


def fetch_listed(ticker, corp_code, name, rcept_no, report_nm, rcept_dt, filer=None, remark='', out_root=None, get=http_get, env=None, added_by='auto'):
    """v0.38 T2-4e 자동 확인이 DART 목록에서 이미 본 공시의 원문만 받는다(목록을 다시 부르지 않음). 받은 그대로·해시 고정은 접수번호로 받기와 같다.
    rcept_dt: YYYY-MM-DD. 반환: (manifest 항목, 새로 받았는지). 이미 사본에 있으면 DART를 부르지 않는다."""
    rcept_no = (rcept_no or '').strip()
    if not re.fullmatch(r'\d{14}', rcept_no):
        raise DartDocsError('bad_rcept_no', '접수번호는 숫자 14자리예요(예: 20260211800925).')
    nm = ' '.join((report_nm or '').split())
    if OWN_EXCLUDE.search(nm):
        raise DartDocsError('subsidiary', f'「{nm}」은(는) 자회사의 공시라 이 회사의 숫자로 계산하지 않아요.')
    k = classify(nm)
    if k is None:
        raise DartDocsError('unsupported_kind', f'「{nm}」은(는) 아직 계산하는 공시 종류가 아니에요.')
    if not corp_code:
        raise DartDocsError('no_corp_code', f'{ticker}: DART 고유번호(corp_code)가 없어 받을 수 없어요.')
    root = Path(out_root or docs_dir())
    with MAN_LOCK:
        try:
            man = load_manifest(root)
            man = {kk: v for kk, v in man.items() if not kk.startswith('_')}
        except DartDocsError as e:
            if e.code != 'no_docs':
                raise
            man = {'tool': 'mrn.dartdocs', 'tool_version': TOOL_VERSION, 'origin': '금융감독원 OpenDART document.xml (받은 그대로, 고치지 않음)', 'docs': {}, 'listed': {}, 'failed': {}}
        d = man['docs'].get(rcept_no)
        if d and (root / d['file']).exists():
            if d['ticker'] != ticker:
                raise DartDocsError('other_company', f"접수번호 {rcept_no}는 {d.get('name') or d['ticker']}의 공시예요.")
            return d, False
        key = api_key(env)
        if not key:
            raise DartDocsError('no_key', 'DART 키가 없습니다. modu-research-nodes\\local-env.cmd 에 DART_API_KEY 를 넣어 주세요.')
        b, members = fetch_doc(key, rcept_no, get)
        root.mkdir(parents=True, exist_ok=True)
        (root / f'{rcept_no}.zip').write_bytes(b)
        d = {'ticker': ticker, 'corp_code': corp_code, 'name': name, 'report_nm': nm, 'rcept_dt': rcept_dt,
             'kind': k, 'filer': filer, 'remark': remark or '', 'file': f'{rcept_no}.zip', 'bytes': len(b), 'sha256': _sha(b), 'members': members,
             'fetched_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'url': f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}', 'added_by': added_by}
        man['docs'][rcept_no] = d
        man['failed'].pop(rcept_no, None)
        _save_manifest(root, man)
    return d, True


def find(ticker=None, kind=None, cutoff=None, root=None):
    """기준시점(cutoff, ISO) 이전에 접수된 공시 목록(접수번호 순)."""
    man = load_manifest(root)
    last = (cutoff or '9999')[:10]
    out = [{'rcept_no': no, **d} for no, d in man['docs'].items()
           if (ticker is None or d['ticker'] == ticker) and (kind is None or d['kind'] == kind) and d['rcept_dt'] <= last]
    return sorted(out, key=lambda d: d['rcept_no'])


def open_doc(rcept_no, root=None, man=None):
    """원문 ZIP의 해시를 다시 대조한 뒤 안의 파일을 글자로 돌려준다: [(이름, 글)]. 내용은 바꾸지 않는다.
    man: 이미 읽은(해시 대조한) 목록 — 여러 건을 열 때 목록을 건마다 다시 읽지 않게(v0.38)."""
    man = man or load_manifest(root)
    d = man['docs'].get(rcept_no)
    if not d:
        raise DartDocsError('doc_missing', f'접수번호 {rcept_no} 원문이 사본에 없습니다.')
    b = (Path(man['_root']) / d['file']).read_bytes()
    if _sha(b) != d['sha256']:
        raise DartDocsError('doc_mismatch', f'접수번호 {rcept_no} 원문이 받을 때의 해시와 다릅니다. 쓰지 않습니다.')
    out = []
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        for i in z.infolist():
            raw = z.read(i)
            for enc in ('utf-8', 'cp949'):
                try:
                    out.append((i.filename, raw.decode(enc))); break
                except UnicodeDecodeError:
                    continue
            else:
                out.append((i.filename, raw.decode('utf-8', 'replace')))
    return out, {'rcept_no': rcept_no, 'sha256': d['sha256'], 'manifest_sha256': man['_manifest_sha256'], 'url': d['url'], 'report_nm': d['report_nm'], 'rcept_dt': d['rcept_dt']}


def status(root=None):
    man = load_manifest(root)
    by = {}
    for d in man['docs'].values():
        by.setdefault(d['kind'], [0, 0, set()]); by[d['kind']][0] += 1; by[d['kind']][1] += d['bytes']; by[d['kind']][2].add(d['ticker'])
    return {'docs': len(man['docs']), 'companies': len({d['ticker'] for d in man['docs'].values()}), 'bytes': sum(d['bytes'] for d in man['docs'].values()),
            'by_kind': {k: {'label': KIND_LABEL[k], 'docs': v[0], 'bytes': v[1], 'companies': len(v[2])} for k, v in sorted(by.items())},
            'failed': len(man.get('failed') or {}), 'manifest_sha256': man['_manifest_sha256'], 'updated_at': man.get('updated_at')}


def verify_all(root=None):
    man = load_manifest(root); bad = []
    for no, d in man['docs'].items():
        p = Path(man['_root']) / d['file']
        if not p.exists() or _sha(p.read_bytes()) != d['sha256']:
            bad.append(no)
    return {'checked': len(man['docs']), 'bad': bad}


def _companies(tickers=None):
    from .market import resolve, load_manifest as neon_manifest, companies
    root = resolve(''); cos = companies(root, neon_manifest(root))
    pick = tickers or sorted(t for t, c in cos.items() if c.get('market') == 'KR')
    return [{'ticker': t, 'corp_code': (cos.get(t) or {}).get('corp_code'), 'name': (cos.get(t) or {}).get('name', t)} for t in pick]


def metered_get(get=None, log=print, data_dir=None):
    """v0.38 T2-4(T2-H1) 명령창 대량 받기도 앱과 같은 하루 사용량(dart_usage)에 올리고, 상한에 닿으면 멈춘다.
    앱 자료(DB)를 열지 못하거나 쓰는 중이라 잠겨 있으면 세지 않고 받기만 계속한다(받기가 계측 때문에 끊기지 않게)."""
    import sqlite3
    get = get or http_get
    try:
        from . import autocheck as AC
        from .store import Store
        st = Store(str(data_dir or os.environ.get('MODU_NODES_DATA_DIR') or Path(__file__).resolve().parents[1] / 'data')); AC.ensure(st)
        counted = AC.counted_get(st, get)
    except Exception as e:
        log(f'  (사용량 계측을 열지 못해 세지 않고 받습니다: {type(e).__name__})'); return get
    warned = []

    def g(url, *a, **k):
        try:
            return counted(url, *a, **k)
        except sqlite3.Error as e:                              # 계측 DB 가 잠김 등 — 한 번만 알리고 받기는 계속
            if not warned:
                warned.append(1); log(f'  (사용량 계측에 쓰지 못한 호출이 있습니다: {type(e).__name__})')
            return get(url, *a, **k)
    return g


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog='python -m mrn.dartdocs')
    sub = ap.add_subparsers(dest='cmd', required=True)
    f = sub.add_parser('fetch'); f.add_argument('--companies', default='', help='종목코드를 쉼표로. 비우면 사본의 국내 회사 전체')
    f.add_argument('--kinds', default='', help=','.join(KINDS)); f.add_argument('--from', dest='start', default=DEFAULT_FROM); f.add_argument('--to', dest='end', default=None)
    f.add_argument('--limit', type=int, default=None, help='이번 실행에서 새로 받을 최대 건수')
    sub.add_parser('status'); sub.add_parser('verify')
    a = ap.parse_args(argv)
    try:
        if a.cmd == 'fetch':
            cos = _companies([t.strip() for t in a.companies.split(',') if t.strip()] or None)
            kinds = [k.strip() for k in a.kinds.split(',') if k.strip()] or None
            print(f'DART 원문 받기: 회사 {len(cos)}곳, {a.start} ~ {a.end or "오늘"}, 종류 {kinds or "전체"}')
            n = fetch(cos, kinds, a.start, a.end, limit=a.limit, get=metered_get())
            print(f'새로 받은 원문 {n}건.')
        if a.cmd in ('fetch', 'status'):
            s = status()
            print(f"사본: 원문 {s['docs']}건 · 회사 {s['companies']}곳 · {s['bytes'] / 1e6:,.1f}MB · 받지 못한 것 {s['failed']}건")
            for k, v in s['by_kind'].items():
                print(f"  {v['label']}: {v['docs']}건 ({v['companies']}곳, {v['bytes'] / 1e6:,.1f}MB)")
        if a.cmd == 'verify':
            v = verify_all(); print(f"해시 대조: {v['checked']}건 중 다른 것 {len(v['bad'])}건" + (': ' + ', '.join(v['bad'][:10]) if v['bad'] else ''))
    except DartDocsError as e:
        print(f'멈춤: {e}'); return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
