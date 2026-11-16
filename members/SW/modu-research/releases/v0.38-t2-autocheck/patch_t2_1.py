"""v0.38 T2-1 붙이기: watch_api(자동 확인 API + 접수번호 받기도 사용량 계량) · server(등록 한 줄) · __main__(일정 시작). 여러 번 돌려도 같은 결과."""
import sys
from pathlib import Path

N = Path(sys.argv[1])


def patch(rel, old, new, mark):
    p = N / rel; s = p.read_text(encoding='utf-8')
    if mark in s:
        print(f'{rel}: 이미 적용됨'); return
    if s.count(old) != 1:
        raise SystemExit(f'{rel}: 바꿀 자리를 정확히 하나 찾지 못함({s.count(old)})')
    p.write_text(s.replace(old, new), encoding='utf-8', newline='')
    print(f'{rel}: 적용')


# 1) 접수번호 받기도 DART 사용량에 센다 + 상한이면 429
patch('mrn/watch_api.py',
      "           'no_corp_code': 409, 'network': 502, 'dart_020': 429}",
      "           'no_corp_code': 409, 'network': 502, 'dart_020': 429, 'usage_cap': 429}   # v0.38 T2-1 usage_cap",
      'usage_cap')
patch('mrn/watch_api.py',
      "            d, new = D.fetch_one(body.ticker.strip(), body.rcept_no.strip())",
      "            from . import autocheck as AC                           # v0.38 T2-1: 접수번호 받기도 하루 사용량에 센다\n"
      "            d, new = D.fetch_one(body.ticker.strip(), body.rcept_no.strip(), get=AC.counted_get(store))",
      'AC.counted_get(store)')
# 2) 자동 확인 API (더하기만)
patch('mrn/watch_api.py',
      "class FetchBody(BaseModel):",
      '''def register_autocheck(app, store, owner):
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
    def autocheck_run(request: Request):
        r = AC.check_once(store, 'manual')
        if r.get('status') == 'busy':
            raise HTTPException(409, {'code': 'busy', 'message': r['message']})
        with store.lock, store.connect() as c:
            store.audit(c, owner(request), 'watch.autocheck', str(r.get('id')), {'status': r.get('status'), 'new': r.get('new'), 'calls': r.get('calls')})
        r['status_label'] = AC.STATUS_LABEL.get(r['status'], r['status'])
        return r


class FetchBody(BaseModel):''',
      'def register_autocheck')
patch('mrn/server.py',
      "    _filings_register(app, store, owner)\n",
      "    _filings_register(app, store, owner)\n"
      "    from .watch_api import register_autocheck as _autocheck_register   # v0.38 T2-1 공시 자동 확인(API만; 일정은 __main__에서)\n"
      "    _autocheck_register(app, store, owner)\n",
      '_autocheck_register')
patch('mrn/__main__.py',
      "    app = create_app(str(data_dir), port=port, stop_token=token)\n",
      "    app = create_app(str(data_dir), port=port, stop_token=token)\n"
      "    from .autocheck import start_scheduler                     # v0.38 T2-1: 앱이 켜져 있는 동안만 관심 종목 공시 목록 확인(MODU_AUTOCHECK=0이면 끔)\n"
      "    start_scheduler(app.state.store)\n",
      'start_scheduler')
