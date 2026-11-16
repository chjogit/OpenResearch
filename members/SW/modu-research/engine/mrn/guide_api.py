"""v0.26 AI 길잡이 API — server.create_app 에서 register(app, store, owner) 한 줄로 붙인다(공용 파일 변경 최소화)."""
from fastapi import HTTPException, Request
from pydantic import BaseModel


class TranslateIn(BaseModel):
    question: str
    company: str = ''
    use_model: bool = False


def register(app, store, owner):
    from . import guide as G

    @app.get('/api/guide/status')
    def guide_status():
        s = G.status()
        return {k: s[k] for k in ('available', 'model', 'local', 'how')}

    @app.post('/api/guide/translate')
    def guide_translate(body: TranslateIn, request: Request):
        q = (body.question or '').strip()
        if not q or len(q) > 300:
            raise HTTPException(422, '질문을 1~300자로 적어 주세요.')
        name, cards_ok = '', None
        if body.company:
            try:
                from .market import company_name
                name = company_name(body.company) or ''
            except Exception:
                name = ''
        r = G.translate(q, name, cards_ok, body.use_model)
        store.agent_audit(owner(request), 'guide.translate', r['mode'], G.audit_detail(q, r))
        return r
