"""v0.32 T1 공유용 답 페이지 API — server.create_app 끝에서 register(app, store, owner) 한 줄로 붙인다."""
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse


def register(app, store, owner):
    from .store import NotFound

    @app.get('/api/share/{rid}')
    def share_page(rid: str, request: Request, q: str = ''):
        from .easy import answer, receipt
        from . import share
        from .market import company_name
        o = owner(request)
        try:
            run = store.get_run(o, rid)
        except NotFound:
            raise HTTPException(404, 'run_not_found')
        if run['status'] in ('waiting', 'queued', 'running'):
            raise HTTPException(409, '실행이 끝난 뒤에 공유용 페이지를 만들 수 있습니다.')
        get = lambda pid: store.get_packet(pid, o)
        from .autocheck import seen_info                 # v0.38 T2-4d (J23)
        html, meta = share.build(answer(run, get, company_name, seen=lambda no: seen_info(store, no)), receipt(run, get), (q or '')[:120])
        store.agent_audit(o, 'easy.share', rid[:16], {'receipt': meta['receipt8']})
        fn = f"공유_{meta['name']}_{meta['receipt8']}.html".replace(' ', '')
        return HTMLResponse(html, headers={'Content-Disposition': f"attachment; filename=\"share_{meta['receipt8']}.html\"; filename*=UTF-8''{quote(fn)}",
                                           'Cache-Control': 'no-store'})
