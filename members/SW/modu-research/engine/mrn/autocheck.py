"""v0.38 T2-1 관심 종목 공시 자동 확인 — 새 공시 「목록」만 정해진 간격으로 확인한다. AI 모델 호출 0회.

- 대상: 누군가의 「내 관심 종목」에 들어 있는 회사(watchlist의 종목 전체). 회사마다 DART 공시 목록(list.json, 모든 공시 유형)을 부른다.
- 원문: 앱이 계산하는 1등급 공시만 원문까지 받아 미리 계산한다(v0.38 T2-4e, auto_docs). 나머지는 목록만. 목록 한 쪽(최대 100건) = DART 호출 1회.
- 따라잡기: 회사마다 「어디까지 확인했나」(covered_to, 한국 날짜)를 적어 두고, 다음 확인은 그날부터 다시 본다(같은 날 늦게 나온 공시까지 잡기 위해 하루 겹침).
  앱이 꺼져 있던 동안의 공시도 다시 켰을 때 이 날짜부터 받아 온다. 처음 등록한 회사는 최근 FIRST_DAYS일만, 공백이 길어도 최대 MAX_CATCHUP_DAYS일만 본다.
- 중복 없음: 접수번호가 열쇠(filing_seen). 앱이 처음 본 시각(first_seen_at)을 기록한다 — DART 목록에는 접수 날짜만 있고 시각이 없다.
- 멈춤: DART 하루 한도(020)·연결 실패·키 문제·사용량 상한이면 그 자리에서 멈춘다. 끝내지 못한 회사의 covered_to는 그대로라 다음 확인에서 이어서 받는다(누락 없음).
- 사용량: 한국 날짜별 DART 호출 수(dart_usage)를 센다. 하루 한도의 DOC_STOP(기본 70%)에 닿으면 원문 받기를, LIST_STOP(기본 95%)에 닿으면 목록 확인도 멈춘다.
- 실행: 앱(python -m mrn)이 켜져 있을 때만. 켤 때 한 번(20초 뒤) + INTERVAL_MIN(기본 60분)마다. 시험·create_app 만으로는 돌지 않는다(__main__에서만 시작).
- 설정(환경 변수, local-env.cmd): MODU_AUTOCHECK=0(끄기) · MODU_AUTOCHECK_MIN · MODU_DART_DAILY_LIMIT · MODU_DART_DOC_STOP · MODU_DART_LIST_STOP.
- 키는 환경 변수에서만 읽고 어디에도 남기지 않는다(dartdocs와 같음).
- v0.38 T2-1b(재검토 반영): 줄마다 그 회사를 「직전에 확인한 시각」(prev_checked_at)을 함께 남겨, 공시가 실제로 뜬 때의 범위(직전 확인 ~ 처음 본 시각)를 알 수 있게 한다(F2).
  연결이 잠깐 끊겨 멈추면 2분→5분→10분 뒤 다시 시도한다(F1). 일정은 30초마다 깨어나 벽시계로 확인 시각을 넘었는지 본다 — PC 절전 뒤에도 바로 따라잡음(F7).
  화면 판은 최근 14일을 기간으로 뽑고 건수 제한은 「하」에만 둔다 — 종목이 많아져도 상·1등급이 밀려나지 않음(F3·F4).
  확인 도중 끊긴 기록 정리는 앱이 켜질 때 한 번만 한다(F6).
"""
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

from . import dartdocs as D
from . import filing as FL
from . import filing_grade as G

KST = timezone(timedelta(hours=9))          # 한국은 서머타임이 없어 고정 +9시간(Windows에 시간대 자료가 없어도 동작)
FIRST_DAYS = 7
MAX_CATCHUP_DAYS = 90
STOP_CODES = ('usage_cap', 'dart_020', 'network', 'dart_010', 'dart_011', 'dart_012', 'dart_800', 'no_key', 'dart_bad_response')
RETRY_CODES = ('network', 'dart_800', 'dart_bad_response')      # F1: 잠깐의 연결·점검 문제는 짧은 간격으로 다시 시도
RETRY_SEC = (120, 300, 600)
WINDOW_DAYS = 14                                                 # F3·F4: 화면 판 기간
LOW_LIMIT = 200                                                  # F3: 「하」만 건수 제한
TICK_SEC = 30                                                    # F7: 일정이 깨어나는 간격

DDL = """
CREATE TABLE IF NOT EXISTS filing_seen(
  rcept_no TEXT PRIMARY KEY, ticker TEXT NOT NULL, corp_code TEXT, name TEXT, report_nm TEXT NOT NULL, rcept_dt TEXT NOT NULL,
  filer TEXT, remark TEXT, kind TEXT, first_seen_at TEXT NOT NULL, first_check INTEGER NOT NULL DEFAULT 0, run_id INTEGER, prev_checked_at TEXT);
CREATE INDEX IF NOT EXISTS filing_seen_ticker ON filing_seen(ticker, rcept_no);
CREATE TABLE IF NOT EXISTS autocheck_state(ticker TEXT PRIMARY KEY, covered_to TEXT NOT NULL, checked_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS autocheck_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, trigger TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
  tickers INTEGER NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0, new INTEGER NOT NULL DEFAULT 0, calls INTEGER NOT NULL DEFAULT 0,
  code TEXT, message TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS dart_usage(day TEXT PRIMARY KEY, calls INTEGER NOT NULL DEFAULT 0);
"""
STATUS_LABEL = {'running': '확인 중', 'ok': '확인 끝', 'partial': '일부 회사만 확인', 'stopped': '중간에 멈춤', 'no_key': 'DART 키 없음',
                'empty': '관심회사 없음', 'error': '확인 실패'}
_RUN_LOCK = threading.Lock()


def ensure(store):
    from . import watch as W
    W.ensure(store)
    with store.lock, store.connect() as c:
        c.executescript(DDL)
        cols = {r['name'] for r in c.execute('PRAGMA table_info(filing_seen)')}
        if 'prev_checked_at' not in cols:                         # T2-1에서 만든 표에 칸만 더함(기존 줄은 빈 값 = 모름)
            c.execute('ALTER TABLE filing_seen ADD COLUMN prev_checked_at TEXT')
        for col in ('doc_state', 'doc_note', 'doc_at', 'prep_state', 'prep_note'):     # v0.38 T2-4e 원문 자동 받기·미리 계산(칸만 더함)
            if col not in cols:
                c.execute(f'ALTER TABLE filing_seen ADD COLUMN {col} TEXT')
        rcols = {r['name'] for r in c.execute('PRAGMA table_info(autocheck_runs)')}
        for col in ('docs', 'prepared'):
            if col not in rcols:
                c.execute(f'ALTER TABLE autocheck_runs ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0')
        if 'doc_tries' not in cols:
            c.execute('ALTER TABLE filing_seen ADD COLUMN doc_tries INTEGER NOT NULL DEFAULT 0')


def close_interrupted(store):
    """앱이 켜질 때 한 번만(F6): 확인 도중 앱이 꺼진 기록을 「확인 중」으로 남겨 두지 않는다."""
    ensure(store)
    with store.lock, store.connect() as c:
        return c.execute("UPDATE autocheck_runs SET status='stopped', code='interrupted', message='앱이 꺼지거나 오류로 확인이 중간에 끊겼어요 — 다음 확인 때 이어서 받습니다.' "
                         "WHERE status='running'").rowcount


def config(env=None):
    env = os.environ if env is None else env

    def num(k, d, lo, hi, f=int):
        try:
            return min(hi, max(lo, f(env.get(k) or d)))
        except (TypeError, ValueError):
            return d
    return {'enabled': (env.get('MODU_AUTOCHECK') or '1') != '0',
            'interval_min': num('MODU_AUTOCHECK_MIN', 60, 10, 24 * 60),
            'daily_limit': num('MODU_DART_DAILY_LIMIT', 20000, 100, 10 ** 7),
            'doc_stop': num('MODU_DART_DOC_STOP', 0.70, 0.05, 1.0, float),
            'list_stop': num('MODU_DART_LIST_STOP', 0.95, 0.05, 1.0, float),
            'auto_docs': (env.get('MODU_AUTO_DOCS') or '1') != '0', 'auto_docs_max': num('MODU_AUTO_DOCS_MAX', 30, 0, 500)}     # v0.38 T2-4e


def kst_day(at=None):
    return (at or datetime.now(timezone.utc)).astimezone(KST).date()


def _iso(at):
    return at.astimezone(timezone.utc).isoformat()


def usage(store, day=None, cfg=None):
    cfg = cfg or config(); day = (day or kst_day()).isoformat()
    with store.lock, store.connect() as c:
        r = c.execute('SELECT calls FROM dart_usage WHERE day=?', (day,)).fetchone()
    n = r['calls'] if r else 0
    lim = cfg['daily_limit']
    return {'day': day, 'calls': n, 'limit': lim, 'doc_stop_at': int(lim * cfg['doc_stop']), 'list_stop_at': int(lim * cfg['list_stop']),
            'docs_paused': n >= int(lim * cfg['doc_stop']), 'lists_paused': n >= int(lim * cfg['list_stop'])}


def counted_get(store, get=None, cfg=None, clock=None, counter=None):
    """DART 호출 한 번마다 그날(한국 날짜) 사용량을 1 올린다. 상한에 닿았으면 부르지 않고 usage_cap 으로 멈춘다.
    원문(document.xml)은 DOC_STOP, 목록은 LIST_STOP 기준. counter: 이번 실행의 호출 수를 세는 [0]."""
    get = get or D.http_get; cfg = cfg or config()

    def g(url, *a, **k):
        day = kst_day(clock() if clock else None).isoformat()
        is_doc = 'document.xml' in url
        cap = int(cfg['daily_limit'] * (cfg['doc_stop'] if is_doc else cfg['list_stop']))
        with store.lock, store.connect() as c:
            r = c.execute('SELECT calls FROM dart_usage WHERE day=?', (day,)).fetchone()
            n = r['calls'] if r else 0
            if n >= cap:
                what = '원문 받기' if is_doc else '공시 목록 확인'
                raise D.DartDocsError('usage_cap', f"오늘 DART 사용량이 {n:,}회로 상한({cap:,}회, 하루 한도 {cfg['daily_limit']:,}회의 "
                                                   f"{round((cfg['doc_stop'] if is_doc else cfg['list_stop']) * 100)}%)에 닿아 {what}를 멈췄어요. 내일 이어서 합니다.")
            c.execute('INSERT INTO dart_usage(day,calls) VALUES(?,1) ON CONFLICT(day) DO UPDATE SET calls=calls+1', (day,))
        if counter is not None:
            counter[0] += 1
        return get(url, *a, **k)
    return g


def watched(store):
    with store.lock, store.connect() as c:
        return [r['ticker'] for r in c.execute('SELECT DISTINCT ticker FROM watchlist ORDER BY ticker')]


def _companies(tickers):
    return {c['ticker']: c for c in D._companies(tickers)}


def _finish(store, run_id, status, at, **kw):
    kw.setdefault('code', None); kw.setdefault('message', None)        # F6: 정상 종료면 code를 비움
    sets = ', '.join(f'{k}=?' for k in kw)
    with store.lock, store.connect() as c:
        c.execute(f"UPDATE autocheck_runs SET status=?, finished_at=?{', ' + sets if sets else ''} WHERE id=?", (status, _iso(at), *kw.values(), run_id))
        return dict(c.execute('SELECT * FROM autocheck_runs WHERE id=?', (run_id,)).fetchone())


def check_once(store, trigger='manual', clock=None, get=None, env=None, companies=None):
    """한 번 확인. 반환: 실행 기록 한 줄(dict). 다른 확인이 돌고 있으면 {'status': 'busy'}."""
    if not _RUN_LOCK.acquire(blocking=False):
        return {'status': 'busy', 'message': '이미 확인하고 있어요. 끝나면 다시 눌러 주세요.'}
    try:
        return _check(store, trigger, clock or (lambda: datetime.now(timezone.utc)), get, env, companies)
    finally:
        _RUN_LOCK.release()


def check_in_background(store, **kw):
    """v0.38 T2-4(T2-H2) 「지금 확인」을 뒤에서 돌린다. 바로 돌아오고, 끝났는지는 status()['checking'] 과 마지막 실행 기록으로 본다."""
    if _RUN_LOCK.locked():
        return {'status': 'busy', 'message': '이미 확인하고 있어요. 끝나면 다시 눌러 주세요.'}
    th = threading.Thread(target=lambda: check_once(store, 'manual', **kw), name='autocheck-manual', daemon=True); th.start()
    return {'status': 'started', 'message': '확인을 시작했어요. 끝나면 목록이 바뀝니다.', 'thread': th}


def _check(store, trigger, clock, get, env, companies):
    ensure(store)
    cfg = config(env); start_at = clock(); today = kst_day(start_at)
    tickers = watched(store)
    with store.lock, store.connect() as c:
        run_id = c.execute('INSERT INTO autocheck_runs(trigger, started_at, status, tickers) VALUES(?,?,?,?)',
                           (trigger, _iso(start_at), 'running', len(tickers))).lastrowid
    try:
        return _check_body(store, run_id, tickers, today, cfg, clock, get, env, companies)
    except Exception as e:                                           # 예상 못 한 오류도 「확인 중」으로 남기지 않는다
        return _finish(store, run_id, 'error', clock(), code='internal', message=f'확인 중 오류가 나 멈췄어요({type(e).__name__}). 다음 확인 때 이어서 받습니다.')


def _check_body(store, run_id, tickers, today, cfg, clock, get, env, companies):
    key = D.api_key(env)
    if not key:
        return _finish(store, run_id, 'no_key', clock(), code='no_key', message='DART 키가 없어 확인하지 않았어요. local-env.cmd 에 DART_API_KEY 를 넣어 주세요.')
    if not tickers:
        return _finish(store, run_id, 'empty', clock(), message='관심회사가 없어 확인할 회사가 없어요.')
    try:
        cos = companies if companies is not None else _companies(tickers)
    except Exception as e:                                           # 사본(회사 목록)을 못 읽으면 DART를 부르지 않는다
        return _finish(store, run_id, 'error', clock(), code='companies', message=f'회사 목록을 읽지 못해 확인하지 않았어요({type(e).__name__}).')
    counter = [0]; g = counted_get(store, get, cfg, clock, counter)
    done = new = 0; notes = []; stop = None
    for t in tickers:
        co = cos.get(t) or {}
        if not co.get('corp_code'):
            notes.append(f'{t}: DART 고유번호(corp_code)가 사본에 없어 건너뜀'); continue
        with store.lock, store.connect() as c:
            st = c.execute('SELECT covered_to, checked_at FROM autocheck_state WHERE ticker=?', (t,)).fetchone()
        first = st is None
        prev = None if st is None else st['checked_at']                  # F2: 이 회사를 직전에 확인(성공)한 시각
        start = today - timedelta(days=FIRST_DAYS) if first else date.fromisoformat(st['covered_to'])
        if (today - start).days > MAX_CATCHUP_DAYS:
            notes.append(f"{t}: 마지막 확인({start.isoformat()})이 {MAX_CATCHUP_DAYS}일보다 오래돼 최근 {MAX_CATCHUP_DAYS}일만 확인")
            start = today - timedelta(days=MAX_CATCHUP_DAYS)
            first = True                                              # 공백이 너무 길면 처음 등록처럼 표시(오래된 공시를 「새 공시」로 쏟아 내지 않게)
        start = min(start, today)                                     # PC 시계가 뒤로 간 경우에도 시작일이 오늘을 넘지 않게
        try:
            rows = D.list_filings(key, co['corp_code'], None, start.isoformat(), today.isoformat(), g)
        except D.DartDocsError as e:
            if e.code in STOP_CODES:
                stop = e; break
            notes.append(f'{t}: {e}'); continue
        seen_at = _iso(clock()); added = 0
        with store.lock, store.connect() as c:
            for r in rows:
                no = str(r.get('rcept_no') or '')
                if len(no) != 14 or not no.isdigit():
                    continue
                nm = ' '.join((r.get('report_nm') or '').split()); dt = str(r.get('rcept_dt') or no[:8])
                added += c.execute('INSERT OR IGNORE INTO filing_seen(rcept_no,ticker,corp_code,name,report_nm,rcept_dt,filer,remark,kind,first_seen_at,first_check,run_id,prev_checked_at) '
                                   'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                   (no, t, co['corp_code'], co.get('name'), nm, f'{dt[:4]}-{dt[4:6]}-{dt[6:8]}', r.get('flr_nm'), r.get('rm') or '',
                                    D.classify(nm), seen_at, 1 if first else 0, run_id, None if first else prev)).rowcount
            c.execute('INSERT INTO autocheck_state(ticker,covered_to,checked_at) VALUES(?,?,?) ON CONFLICT(ticker) DO UPDATE SET covered_to=excluded.covered_to, checked_at=excluded.checked_at',
                      (t, today.isoformat(), seen_at))
        done += 1; new += added
    docs = prepared = 0
    if stop is None and cfg.get('auto_docs'):                    # v0.38 T2-4e(PM 결정 ①): 1등급 원문 자동 받기 + 미리 계산. 사용량 상한이면 받기만 멈추고 목록 결과는 그대로
        docs, prepared, dnotes = auto_docs(store, tickers, today, cfg, g, env, clock)
        notes += dnotes
    kw = {'done': done, 'new': new, 'calls': counter[0], 'notes': '\n'.join(notes), 'docs': docs, 'prepared': prepared}
    if stop is not None:
        return _finish(store, run_id, 'stopped', clock(), code=stop.code, message=f'{stop} — 확인하지 못한 회사는 다음 확인 때 이어서 받습니다.', **kw)
    status = 'ok' if done == len(tickers) else 'partial'
    return _finish(store, run_id, status, clock(), message=f'관심회사 {len(tickers)}곳 중 {done}곳 확인 · 새 공시 {new}건' + (f' · 원문 자동 받기 {docs}건' if docs else ''), **kw)


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
        if D.OWN_EXCLUDE.search(r['report_nm'] or '') or G.classify(r['report_nm'])['grade'] == 3:      # v0.39 T3-2(J32) 2등급 중 계산하는 종류도 받음
            _mark(store, r['rcept_no'], doc_state='skipped', doc_note='자회사 공시이거나 숫자 없는 공시라 받지 않음'); continue
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
    with store.lock, store.connect() as c:
        r = c.execute('SELECT * FROM autocheck_runs ORDER BY id DESC LIMIT 1').fetchone()
    return dict(r) if r else None


def recent(store, tickers, limit=50, since=None, now=None):
    """since: 이 날짜(YYYY-MM-DD, 접수일) 이후만. now: 「새로」 표시 기준 시각(기본 지금)."""
    if not tickers:
        return []
    q = ','.join('?' * len(tickers)); now = now or datetime.now(timezone.utc)
    with store.lock, store.connect() as c:
        rows = c.execute(f"SELECT * FROM filing_seen WHERE ticker IN ({q}) AND rcept_dt >= ? ORDER BY rcept_no DESC LIMIT ?",
                         (*tickers, since or '0000-00-00', int(limit))).fetchall()
    out = []
    for r in rows:
        d = dict(r); d.pop('run_id', None)
        seen = datetime.fromisoformat(d['first_seen_at'])
        d['is_new'] = (not d['first_check']) and (now - seen) <= timedelta(hours=24)        # F4: 하루 안에 새로 들어온 줄
        d['seen_gap_min'] = (round((seen - datetime.fromisoformat(d['prev_checked_at'])).total_seconds() / 60)
                             if d.get('prev_checked_at') else None)                         # F2: 실제로 뜬 때의 범위(분)
        d['url'] = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={d['rcept_no']}"
        d['kind_label'] = D.KIND_LABEL.get(d['kind']) if d['kind'] else None
        d['subsidiary'] = bool(D.OWN_EXCLUDE.search(d['report_nm'] or ''))
        g = G.classify(d['report_nm'])                                 # v0.38 T2-2 제목으로 등급(원문 호출 0)
        d.update(grade=g['grade'], tier=g['tier'], rule=g['rule'], label=g['label'], bundle=g['bundle'], corrected=g['corrected'],
                 can_compute=bool(d['kind'] in FL.KINDS and not d['subsidiary']))
        out.append(d)
    return out


def seen_info(store, rcept_no):
    """v0.38 T2-4d 출처 표시: 이 공시를 앱이 공시 목록에서 처음 본 시각(자동 확인 기록). 기록이나 표가 없으면 None — 지어내지 않는다."""
    import sqlite3
    if store is None:
        return None
    try:
        with store.lock, store.connect() as c:
            r = c.execute('SELECT first_seen_at, prev_checked_at, first_check FROM filing_seen WHERE rcept_no=?', (rcept_no,)).fetchone()
    except sqlite3.OperationalError:                       # 자동 확인을 한 번도 켜지 않아 표가 없음
        return None
    return {'first_seen_at': r['first_seen_at'], 'prev_checked_at': r['prev_checked_at'], 'first_check': bool(r['first_check'])} if r else None


def board_view(store, tickers, now=None):
    """F3·F4: 최근 WINDOW_DAYS일(접수일) 공시를 모두 등급별로 — 건수 제한은 「하」에만(LOW_LIMIT줄, 묶음은 한 줄로 셈)."""
    now = now or datetime.now(timezone.utc)
    since = (kst_day(now) - timedelta(days=WINDOW_DAYS)).isoformat()
    b = G.board(recent(store, tickers, 100000, since, now))
    if len(b['하']) > LOW_LIMIT:
        b['하_more'] = len(b['하']) - LOW_LIMIT; b['하'] = b['하'][:LOW_LIMIT]
    return b


class Scheduler:
    """앱이 켜져 있는 동안만 도는 확인 일정. 켤 때 한 번(delay 초 뒤) + interval_min 분마다.
    F7: TICK_SEC마다 깨어나 벽시계(time.time)로 확인 시각을 넘었는지 본다 — PC가 절전했다 깨어나도 바로 확인.
    F1: 연결·점검 문제로 멈추면 RETRY_SEC 간격(2분→5분→10분)으로 다시 시도한 뒤 원래 간격으로."""
    def __init__(self, store, env=None, delay=20, check=check_once, clock=time.time, tick=TICK_SEC, retry_sec=RETRY_SEC):
        self.store, self.env, self.delay, self.check, self.clock, self.tick, self.retry_sec = store, env, delay, check, clock, tick, retry_sec
        self.cfg = config(env); self.stop_event = threading.Event(); self.thread = None; self.next_run_at = None; self.retry = 0

    def start(self):
        if not self.cfg['enabled'] or (self.thread and self.thread.is_alive()):
            return False
        self.thread = threading.Thread(target=self._loop, name='autocheck', daemon=True); self.thread.start()
        return True

    def stop(self):
        self.stop_event.set()

    def _wait_until(self, due):
        self.next_run_at = _iso(datetime.fromtimestamp(due, timezone.utc))
        while self.clock() < due:
            if self.stop_event.wait(max(0.0, min(self.tick, due - self.clock()))):
                return True
        return False

    def next_gap(self, result):
        """확인 결과 → (다음까지 초, 다음 trigger)."""
        code = (result or {}).get('code')
        if code in RETRY_CODES and self.retry < len(self.retry_sec):
            gap = self.retry_sec[self.retry]; self.retry += 1
            return gap, 'retry'
        self.retry = 0
        return self.cfg['interval_min'] * 60, 'interval'

    def _loop(self):
        trigger, due = 'startup', self.clock() + self.delay
        while True:
            if self._wait_until(due):
                return
            try:
                r = self.check(self.store, trigger, env=self.env)
            except Exception:                                    # 확인 하나가 실패해도 일정은 멈추지 않는다(실행 기록은 check 안에서 남김)
                r = None
            gap, trigger = self.next_gap(r)
            due = self.clock() + gap


SCHED = {'scheduler': None}


def start_scheduler(store, env=None):
    """python -m mrn 에서만 부른다."""
    close_interrupted(store)                                     # F6: 끊긴 기록 정리는 앱이 켜질 때 한 번만
    s = Scheduler(store, env)
    SCHED['scheduler'] = s
    ok = s.start()
    try:                                                         # v0.39 T3-1 주가 큰 움직임 감지(MODU_SURGE=0 이면 끔)
        from . import surge as S
        S.start(store, env)
    except Exception:                                            # 감지가 못 켜져도 공시 확인 일정은 그대로
        pass
    return ok


def _surge(store, tickers, env=None):
    """v0.39 T3-1: 주가 큰 움직임 상태. 실패해도 공시함 상태는 그대로 나가게 None."""
    try:
        from . import surge as S
        return S.status(store, tickers, env)
    except Exception:
        return None


def status(store, tickers, env=None):
    cfg = config(env); s = SCHED['scheduler']
    th = getattr(s, 'thread', None)
    running = bool(th and th.is_alive())
    lr = last_run(store)
    if lr:
        lr['status_label'] = STATUS_LABEL.get(lr['status'], lr['status'])
    return {'enabled': cfg['enabled'], 'running': running, 'checking': _RUN_LOCK.locked(), 'interval_min': cfg['interval_min'], 'next_run_at': getattr(s, 'next_run_at', None) if running else None,
            'has_key': bool(D.api_key(env)), 'usage': usage(store, cfg=cfg), 'last_run': lr, 'tickers': len(tickers),
            'recent': recent(store, tickers),
            'board': board_view(store, tickers),
            'window_days': WINDOW_DAYS,
            'tier_note': G.TIER_NOTE, 'grade_label': G.GRADE_LABEL,
            'surge': _surge(store, tickers, env),               # v0.39 T3-1
            'note': '앱이 켜져 있을 때만 확인합니다. 꺼져 있던 동안의 공시는 다시 켜면 이어서 받아 옵니다. '
                    f"앱이 계산하는 공시(1등급과, 2등급 중 공급계약·타법인 주식)은 원문까지 받아 미리 계산해 둡니다(하루 DART 사용량의 {round(cfg['doc_stop'] * 100)}%에서 멈춤). 나머지는 목록만 봅니다."}
