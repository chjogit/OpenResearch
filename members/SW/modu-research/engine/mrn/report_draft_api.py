"""v0.39.4 근거 고정 보고서 초안 API — server.create_app 에서 register(app, store, owner) 한 줄로 붙인다."""
from fastapi import HTTPException, Request
from pydantic import BaseModel


class DraftIn(BaseModel):
    run_id: str
    use_model: bool = False


def register(app, store, owner):
    from . import report_draft as RD

    @app.post('/api/report/draft')
    def report_draft(body: DraftIn, request: Request):
        from .easy import answer
        from .market import company_name
        from .store import NotFound
        o = owner(request)
        try:
            run = store.get_run(o, body.run_id)
        except NotFound:
            raise HTTPException(404, 'run_not_found')
        a = answer(run, lambda pid: store.get_packet(pid, o), company_name)
        r = RD.draft(a, body.use_model)
        store.agent_audit(o, 'report.draft', r['mode'], RD.audit_detail(r))
        return r
