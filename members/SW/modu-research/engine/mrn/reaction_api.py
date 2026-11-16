"""v0.25: 공시 반응 사전 API — server.create_app 에서 register(app) 한 줄로 붙인다(공용 파일 변경 최소화)."""
from fastapi import HTTPException
from pydantic import BaseModel


class JudgeIn(BaseModel):
    title: str
    company: str = ''
    cutoff: str = ''
    bench: str = ''


def _err(e):
    from .market import SnapshotError
    if isinstance(e, SnapshotError):
        return HTTPException(422, str(e))
    return e


def register(app):
    from . import reaction as R

    def _bench(b):
        if b and b not in ('equal', 'kospi'):
            raise HTTPException(422, '비교 기준은 equal(보통 종목 평균) 또는 kospi(코스피 지수)만 있어요.')
        return b or None

    @app.get('/api/reaction/dictionary')
    def reaction_dictionary(cutoff: str = '', bench: str = ''):
        try:
            res = R.build(cutoff, '', _bench(bench))
        except Exception as e:
            raise _err(e)
        return R.public(res) | {'control': R.control(res), 'model_calls': 0}

    @app.post('/api/reaction/judge')
    def reaction_judge(body: JudgeIn):
        t = (body.title or '').strip()
        if not t or len(t) > 300:
            raise HTTPException(422, '공시 제목을 1~300자로 넣어 주세요.')
        try:
            return R.judge(t, body.company.strip(), body.cutoff, '', _bench(body.bench))
        except Exception as e:
            raise _err(e)

    @app.get('/api/reaction/recent')
    def reaction_recent(company: str = '', cutoff: str = '', days: int = 30, bench: str = ''):
        if not 1 <= days <= 365:
            raise HTTPException(422, '기간은 1~365일이에요.')
        try:
            return R.recent(company.strip(), cutoff, '', days, 60, _bench(bench))
        except Exception as e:
            raise _err(e)
