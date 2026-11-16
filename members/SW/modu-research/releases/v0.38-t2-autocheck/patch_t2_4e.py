"""v0.38 T2-4e 자동 연결(PM 결정 ①): 관심회사의 새 1등급 공시 중 앱이 계산하는 종류는 자동 확인이 원문까지 받아(사용량 상한 70%에서 멈춤) 미리 계산해 둔다.
- 원문 받기: 자동 확인이 이미 본 DART 목록 줄로 원문(document.xml)만 받는다(목록을 다시 부르지 않음). 받는 방식·해시 고정은 접수번호로 받기와 같고, 사본에 「자동 확인이 받음」(added_by=auto)으로 남는다.
- 미리 계산(J24): 공시 숫자 카드와 같은 계산을 한 번 돌려 원문을 읽을 수 있는지 확인하고 확률용 시세·과거 경로를 기억해 둔다. 계산 결과는 저장하지 않는다(카드는 늘 새로 계산).
- 한 번에 MODU_AUTO_DOCS_MAX(기본 30)건까지, 최근 것부터. MODU_AUTO_DOCS=0 이면 끔. 칸은 더하기만(filing_seen: doc_state·doc_note·doc_at·prep_state·prep_note, autocheck_runs: docs·prepared).
고칠 곳을 먼저 모두 확인하고, 하나라도 못 찾으면 아무것도 바꾸지 않는다. 두 번 돌려도 같다."""
import sys
from pathlib import Path

N = Path(sys.argv[1])
FETCH_LISTED = '''

MAN_LOCK = threading.RLock()                    # v0.38 T2-4e: 자동 받기와 접수번호로 받기가 사본 목록(manifest)을 동시에 쓰지 않게


def fetch_listed(ticker, corp_code, name, rcept_no, report_nm, rcept_dt, filer=None, remark='', out_root=None, get=http_get, env=None, added_by='auto'):
    """v0.38 T2-4e 자동 확인이 DART 목록에서 이미 본 공시의 원문만 받는다(목록을 다시 부르지 않음). 받은 그대로·해시 고정은 접수번호로 받기와 같다.
    rcept_dt: YYYY-MM-DD. 반환: (manifest 항목, 새로 받았는지). 이미 사본에 있으면 DART를 부르지 않는다."""
    rcept_no = (rcept_no or '').strip()
    if not re.fullmatch(r'\\d{14}', rcept_no):
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
            raise DartDocsError('no_key', 'DART 키가 없습니다. modu-research-nodes\\\\local-env.cmd 에 DART_API_KEY 를 넣어 주세요.')
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
'''
EDITS = {
    'mrn/dartdocs.py': ("def fetch_listed", [
        ("import sys\nimport time\n", "import sys\nimport threading\nimport time\n"),
        ("    _save_manifest(root, man)\n    return d, True\n\n\ndef find(",
         "    _save_manifest(root, man)\n    return d, True\n" + FETCH_LISTED + "\n\ndef find("),
    ]),
    'mrn/watch_api.py': ("D.MAN_LOCK", [
        ("            d, new = D.fetch_one(body.ticker.strip(), body.rcept_no.strip(), get=AC.counted_get(store))\n",
         "            with D.MAN_LOCK:                                       # v0.38 T2-4e: 자동 받기와 사본 목록을 동시에 쓰지 않게\n"
         "                d, new = D.fetch_one(body.ticker.strip(), body.rcept_no.strip(), get=AC.counted_get(store))\n"),
    ]),
    'web/watch.js': ("function wDoc", [
        ("function wRow(x){\n",
         "function wDoc(x){   // v0.38 T2-4e 원문 자동 받기·미리 계산 상태\n"
         "  if (x.doc_state === 'got') return `<br><span class=\"hint\" title=\"${esc(x.prep_note || '')}\">${x.prep_state === 'ready' ? '원문 받음 · 미리 계산함' : '원문 받음'}</span>`;\n"
         "  if (x.doc_state === 'failed') return `<br><span class=\"hint\" title=\"${esc(x.doc_note || '')}\">원문 자동 받기 실패 — 누르면 다시 받아요</span>`;\n"
         "  return '';\n"
         "}\n"
         "function wRow(x){\n"),
        ("data-t=\"${esc(x.ticker)}\">숫자로 보기</button>`;\n", "data-t=\"${esc(x.ticker)}\">숫자로 보기</button>${wDoc(x)}`;\n"),
    ]),
}
AUTO = '''

def _mark(store, rcept_no, **kw):
    with store.lock, store.connect() as c:
        c.execute(f"UPDATE filing_seen SET {', '.join(f'{k}=?' for k in kw)} WHERE rcept_no=?", (*kw.values(), rcept_no))


def prepare(ticker, rcept_no, cutoff=None):
    """v0.38 T2-4e 미리 계산(J24): 공시 숫자 카드(N20)와 같은 계산을 한 번 돌려 본다. 원문을 읽을 수 있는지 확인하고, 확률 계산에 쓰는 시세·과거 경로를
    기억해 둬 카드를 처음 열 때 빨라진다. 계산 결과는 저장하지 않는다(카드는 늘 새로 계산 — 숫자는 한 곳에서만 나옴). 반환: (상태, 한 줄 설명)."""
    from .market import price_series, company_name, SnapshotError
    cutoff = cutoff or (kst_day().isoformat() + 'T16:00:00+09:00')
    f = FL.load(ticker, rcept_no, cutoff)
    f.update(company=ticker, name=company_name(ticker) or ticker)
    try:
        ps = price_series(ticker, cutoff, '', 1300)
    except SnapshotError:
        ps = None
    rows = (ps or {}).get('rows') or None
    mkt = FL.market_before(rows, f['rcept_dt']) if rows else None
    F, held, _, _ = FL.compute(f, mkt, prices=rows, ticker=ticker, snapshot=((ps or {}).get('source') or {}).get('snapshot'))
    if not F:
        return 'held', '숫자를 내지 않음' + (f' — {held[0]}' if held else '')
    return 'ready', f'숫자 {len(F)}줄 미리 계산' + (f' · 보류 {len(held)}건' if held else '')


DOC_TRIES = 3                                                    # 목록에 막 뜬 공시는 원문이 늦게 열리기도 함 → 실패한 줄은 다음 확인 때 다시(모두 3번까지)


def auto_docs(store, tickers, today, cfg, get, env=None, clock=None):
    """v0.38 T2-4e(PM 결정 ①): 관심회사의 최근 WINDOW_DAYS일 1등급 공시 중 앱이 계산하는 종류의 원문을 자동으로 받고 미리 계산한다.
    DART 원문 호출은 사용량 상한(DOC_STOP)에서 멈추고, 한 번에 auto_docs_max건까지(최근 것부터). 이미 사본에 있으면 DART를 부르지 않는다.
    반환: (새로 받은 수, 미리 계산한 수, 알림 줄)."""
    clock = clock or (lambda: datetime.now(timezone.utc))
    if not tickers or cfg.get('auto_docs_max', 0) <= 0:
        return 0, 0, []
    kinds = sorted(FL.KINDS)
    with store.lock, store.connect() as c:
        rows = [dict(r) for r in c.execute(
            f"SELECT * FROM filing_seen WHERE ticker IN ({','.join('?' * len(tickers))}) AND rcept_dt >= ? AND kind IN ({','.join('?' * len(kinds))}) "
            f"AND (doc_state IS NULL OR (doc_state='failed' AND doc_tries < {DOC_TRIES}) OR (doc_state='got' AND prep_state IS NULL)) ORDER BY rcept_no DESC",
            (*tickers, (today - timedelta(days=WINDOW_DAYS)).isoformat(), *kinds))]
    got = prepared = 0; notes = []; budget = cfg['auto_docs_max']
    for r in rows:
        if D.OWN_EXCLUDE.search(r['report_nm'] or '') or G.classify(r['report_nm'])['grade'] != 1:
            _mark(store, r['rcept_no'], doc_state='skipped', doc_note='자회사 공시이거나 1등급이 아니라 받지 않음'); continue
        if r['doc_state'] in (None, 'failed'):
            if budget <= 0:
                notes.append(f"원문 자동 받기: 한 번에 {cfg['auto_docs_max']}건까지라 나머지는 다음 확인 때 받음"); break
            try:
                d, new = D.fetch_listed(r['ticker'], r['corp_code'], r['name'], r['rcept_no'], r['report_nm'], r['rcept_dt'], r.get('filer'), r.get('remark') or '',
                                        get=get, env=env)
            except D.DartDocsError as e:
                if e.code in STOP_CODES:
                    notes.append(f'원문 자동 받기를 멈춤: {e}'); break
                _mark(store, r['rcept_no'], doc_state='failed', doc_note=str(e)[:300], doc_tries=(r.get('doc_tries') or 0) + 1); continue
            except Exception as e:                                       # 예상 못 한 오류도 목록 확인 결과를 버리지 않는다
                _mark(store, r['rcept_no'], doc_state='failed', doc_note=f'원문 받기 중 오류({type(e).__name__})', doc_tries=(r.get('doc_tries') or 0) + 1); continue
            if new:
                budget -= 1; got += 1
            _mark(store, r['rcept_no'], doc_state='got', doc_at=_iso(clock()), doc_note=('자동 확인이 받음' if new else '이미 사본에 있음'))
        try:
            st, note = prepare(r['ticker'], r['rcept_no'])
        except D.DartDocsError as e:
            st, note = 'held', str(e)[:300]
        except Exception as e:
            st, note = 'failed', f'미리 계산 중 오류({type(e).__name__}) — 카드를 열면 다시 계산합니다'
        _mark(store, r['rcept_no'], prep_state=st, prep_note=note)
        prepared += st == 'ready'
    return got, prepared, notes


def last_run(store):
'''
EDITS['mrn/autocheck.py'] = ("def auto_docs", [
    ("- 원문은 받지 않는다(원문 받기는 T2-4에서 1등급만). 목록 한 쪽(최대 100건) = DART 호출 1회.\n",
     "- 원문: 앱이 계산하는 1등급 공시만 원문까지 받아 미리 계산한다(v0.38 T2-4e, auto_docs). 나머지는 목록만. 목록 한 쪽(최대 100건) = DART 호출 1회.\n"),
    ("            c.execute('ALTER TABLE filing_seen ADD COLUMN prev_checked_at TEXT')\n",
     "            c.execute('ALTER TABLE filing_seen ADD COLUMN prev_checked_at TEXT')\n"
     "        for col in ('doc_state', 'doc_note', 'doc_at', 'prep_state', 'prep_note'):     # v0.38 T2-4e 원문 자동 받기·미리 계산(칸만 더함)\n"
     "            if col not in cols:\n"
     "                c.execute(f'ALTER TABLE filing_seen ADD COLUMN {col} TEXT')\n"
     "        rcols = {r['name'] for r in c.execute('PRAGMA table_info(autocheck_runs)')}\n"
     "        for col in ('docs', 'prepared'):\n"
     "            if col not in rcols:\n"
     "                c.execute(f'ALTER TABLE autocheck_runs ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0')\n"
     "        if 'doc_tries' not in cols:\n"
     "            c.execute('ALTER TABLE filing_seen ADD COLUMN doc_tries INTEGER NOT NULL DEFAULT 0')\n"),
    ("            'list_stop': num('MODU_DART_LIST_STOP', 0.95, 0.05, 1.0, float)}\n",
     "            'list_stop': num('MODU_DART_LIST_STOP', 0.95, 0.05, 1.0, float),\n"
     "            'auto_docs': (env.get('MODU_AUTO_DOCS') or '1') != '0', 'auto_docs_max': num('MODU_AUTO_DOCS_MAX', 30, 0, 500)}     # v0.38 T2-4e\n"),
    ("    kw = {'done': done, 'new': new, 'calls': counter[0], 'notes': '\\n'.join(notes)}\n",
     "    docs = prepared = 0\n"
     "    if stop is None and cfg.get('auto_docs'):                    # v0.38 T2-4e(PM 결정 ①): 1등급 원문 자동 받기 + 미리 계산. 사용량 상한이면 받기만 멈추고 목록 결과는 그대로\n"
     "        docs, prepared, dnotes = auto_docs(store, tickers, today, cfg, g, env, clock)\n"
     "        notes += dnotes\n"
     "    kw = {'done': done, 'new': new, 'calls': counter[0], 'notes': '\\n'.join(notes), 'docs': docs, 'prepared': prepared}\n"),
    ("message=f'관심회사 {len(tickers)}곳 중 {done}곳 확인 · 새 공시 {new}건', **kw)\n",
     "message=f'관심회사 {len(tickers)}곳 중 {done}곳 확인 · 새 공시 {new}건' + (f' · 원문 자동 받기 {docs}건' if docs else ''), **kw)\n"),
    ("\n\ndef last_run(store):\n", AUTO),
    ("'note': '앱이 켜져 있을 때만 확인합니다. 꺼져 있던 동안의 공시는 다시 켜면 이어서 받아 옵니다. 공시 목록만 확인하고 원문은 받지 않습니다.'",
     "'note': '앱이 켜져 있을 때만 확인합니다. 꺼져 있던 동안의 공시는 다시 켜면 이어서 받아 옵니다. '\n"
     "                    f\"앱이 계산하는 1등급 공시는 원문까지 받아 미리 계산해 둡니다(하루 DART 사용량의 {round(cfg['doc_stop'] * 100)}%에서 멈춤). 나머지는 목록만 봅니다.\""),
])

todo = {}
for rel, (mark, pairs) in EDITS.items():
    s = (N / rel).read_text(encoding='utf-8')
    if mark in s:
        print(f'{rel}: 이미 적용됨'); continue
    for old, _ in pairs:
        if s.count(old) != 1:
            raise SystemExit(f'{rel}: 「{old[:60]!r}」 자리를 정확히 하나 찾지 못함({s.count(old)}) — 아무것도 바꾸지 않음')
    todo[rel] = (s, pairs)
for rel, (s, pairs) in todo.items():
    for old, new in pairs:
        s = s.replace(old, new)
    (N / rel).write_text(s, encoding='utf-8', newline=''); print(f'{rel}: {len(pairs)}곳 적용')
