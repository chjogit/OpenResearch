"""v0.38 T1 관심 종목 API — server.create_app 끝에서 register(app, store, owner, now) 한 줄로 붙인다."""
from fastapi import HTTPException, Request
from pydantic import BaseModel


class WatchBody(BaseModel):
    ticker: str


def register(app, store, owner, now):
    from . import watch as W
    from .market import SnapshotError

    @app.get('/api/watch/pick')
    def watch_pick(sort: str = 'name', group: str = 'all', sector: str = '', q: str = '', cutoff: str = ''):
        try:
            return W.pick_list(cutoff or now(), sort, group, sector, q[:40])
        except ValueError as e:
            raise HTTPException(422, str(e))
        except SnapshotError as e:
            raise HTTPException(409, {'code': e.code, 'message': str(e)})

    @app.get('/api/watch')
    def watch_list(request: Request):
        try:
            return W.listing(store, owner(request))
        except SnapshotError as e:
            raise HTTPException(409, {'code': e.code, 'message': str(e)})

    @app.post('/api/watch')
    def watch_add(body: WatchBody, request: Request):
        try:
            return W.add(store, owner(request), body.ticker.strip())
        except LookupError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))
        except SnapshotError as e:
            raise HTTPException(409, {'code': e.code, 'message': str(e)})

    @app.post('/api/watch/remove')
    def watch_remove(body: WatchBody, request: Request):
        try:
            return W.remove(store, owner(request), body.ticker.strip())
        except SnapshotError as e:
            raise HTTPException(409, {'code': e.code, 'message': str(e)})


def register_autocheck(app, store, owner):
    """v0.38 T2-1 자동 확인 상태 · 지금 확인."""
    from . import autocheck as AC
    AC.ensure(store)

    def mine(o):
        with store.lock, store.connect() as c:
            return [r['ticker'] for r in c.execute('SELECT ticker FROM watchlist WHERE owner_id=? ORDER BY ticker', (o,))]

    @app.get('/api/watch/autocheck')
    def autocheck_status(request: Request):
        return AC.status(store, mine(owner(request)))

    @app.post('/api/watch/autocheck/run')
    def autocheck_run(request: Request, background: int = 0):
        if background:                                           # v0.38 T2-4(T2-H2): 바로 돌아오고 화면이 상태를 되묻는다
            r = AC.check_in_background(store); r.pop('thread', None)
            if r.get('status') == 'busy':
                raise HTTPException(409, {'code': 'busy', 'message': r['message']})
            with store.lock, store.connect() as c:
                store.audit(c, owner(request), 'watch.autocheck', 'background', {'status': 'started'})
            r['status_label'] = '확인 시작'
            return r
        r = AC.check_once(store, 'manual')
        if r.get('status') == 'busy':
            raise HTTPException(409, {'code': 'busy', 'message': r['message']})
        with store.lock, store.connect() as c:
            store.audit(c, owner(request), 'watch.autocheck', str(r.get('id')), {'status': r.get('status'), 'new': r.get('new'), 'calls': r.get('calls')})
        r['status_label'] = AC.STATUS_LABEL.get(r['status'], r['status'])
        return r


class FetchBody(BaseModel):
    ticker: str
    rcept_no: str


HTTP_OF = {'bad_rcept_no': 422, 'unsupported_kind': 422, 'subsidiary': 422, 'not_listed': 404, 'other_company': 409, 'no_key': 409,
           'no_corp_code': 409, 'network': 502, 'dart_020': 429, 'usage_cap': 429}   # v0.38 T2-1 usage_cap


def register_filings(app, store, owner):
    """v0.38 T1 접수번호로 공시 받기 · 사본에 있는 1등급 공시 목록."""
    from . import dartdocs as D, filing as FL

    @app.post('/api/watch/fetch')
    def watch_fetch(body: FetchBody, request: Request):
        o = owner(request)
        try:
            from . import autocheck as AC                           # v0.38 T2-1: 접수번호 받기도 하루 사용량에 센다
            with D.MAN_LOCK:                                       # v0.38 T2-4e: 자동 받기와 사본 목록을 동시에 쓰지 않게
                d, new = D.fetch_one(body.ticker.strip(), body.rcept_no.strip(), get=AC.counted_get(store))
        except D.DartDocsError as e:
            raise HTTPException(HTTP_OF.get(e.code, 502 if e.code.startswith('dart_') else 409), {'code': e.code, 'message': str(e)})
        with store.lock, store.connect() as c:
            store.audit(c, o, 'watch.fetch', body.rcept_no.strip(), {'ticker': d['ticker'], 'new': new})
        return {'new': new, 'rcept_no': body.rcept_no.strip(), 'ticker': d['ticker'], 'kind': d['kind'], 'kind_label': D.KIND_LABEL.get(d['kind'], d['kind']),
                'report_nm': d['report_nm'], 'rcept_dt': d['rcept_dt'], 'url': d['url'], 'sha256': d['sha256'], 'computable': d['kind'] in FL.KINDS}

    @app.get('/api/watch/filings/{ticker}')
    def watch_filings(ticker: str):
        try:
            docs = [x for k in FL.KINDS for x in D.find(ticker, k)]
        except D.DartDocsError as e:
            if e.code == 'no_docs':
                return {'ticker': ticker, 'rows': [], 'note': 'DART 원문 사본이 이 PC에 없어요.'}
            raise HTTPException(409, {'code': e.code, 'message': str(e)})
        rows = [{'rcept_no': d['rcept_no'], 'rcept_dt': d['rcept_dt'], 'kind': d['kind'], 'kind_label': FL.KIND_LABEL[d['kind']], 'report_nm': d['report_nm'], 'url': d['url'],
                 'added_by': d.get('added_by') or 'bulk'} for d in docs if not D.OWN_EXCLUDE.search(d.get('report_nm') or '')]
        rows.sort(key=lambda r: r['rcept_no'], reverse=True)
        return {'ticker': ticker, 'rows': rows, 'kinds': [{'key': k, 'label': FL.KIND_LABEL[k]} for k in FL.KINDS],
                'note': '사본에 받아 둔 공시만 보입니다. 새 공시는 접수번호로 받을 수 있어요(DART 키 필요).'}
