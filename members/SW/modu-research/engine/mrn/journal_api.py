"""v0.32 T2 가설 일지 · T3 배우는 길 API — server.create_app 끝에서 register(app, store, owner, now) 한 줄로 붙인다."""
from fastapi import HTTPException, Request
from pydantic import BaseModel


class NoteIn(BaseModel):
    ticker: str
    fiscal_year: int
    metric: str
    period: str
    note: str = ''


class MarkIn(BaseModel):
    task: str


def register(app, store, owner, now):
    from . import journal as J, learn as L

    def trend_of(ticker, fy, metric):
        from .broker import broker_dir, load_manifest, report_ticker
        from . import forecasts as FC
        reps, cands = store.broker_reports()
        man = load_manifest(broker_dir())
        files = {r['file'] for r in reps if (r.get('ticker') or report_ticker(man.get(r['file']))) == ticker}
        fs = [{'broker': c['broker'], 'report_date': c['report_date'], 'metric': c['metric'], 'fiscal_year': c['fiscal_year'], 'value': c['effective_value_mn']}
              for c in cands if c['file'] in files and c['state'] == 'approved']
        return FC.trend(fs, metric, fy) if fs else None

    def actual_of(ticker, fy, metric):
        from decimal import Decimal
        from .market import company_filings
        f = company_filings(ticker, now())
        for x in f.get('facts', []):
            if int(x['year']) == int(fy) and x['metric'] == metric and x.get('amount') not in (None, ''):
                return (str(Decimal(str(x['amount'])) / Decimal(1000000)), x.get('filed_at'))
        return None

    def name_of(t):
        try:
            from .market import company_name
            return company_name(t)
        except Exception:
            return None

    @app.get('/api/journal')
    def journal(request: Request):
        return J.build(store, owner(request), trend_of, actual_of, name_of)

    @app.post('/api/journal/note')
    def journal_note(body: NoteIn, request: Request):
        try:
            J.save_note(store, owner(request), body.ticker, body.fiscal_year, body.metric, body.period, body.note, now())
        except ValueError as e:
            raise HTTPException(422, str(e))
        except LookupError as e:
            raise HTTPException(404, str(e))
        return {'ok': True}

    @app.get('/api/learn')
    def learn(request: Request):
        return L.progress(store, owner(request))

    @app.post('/api/learn/mark')
    def learn_mark(body: MarkIn, request: Request):
        try:
            L.mark(store, owner(request), body.task, now())
        except ValueError as e:
            raise HTTPException(422, str(e))
        return L.progress(store, owner(request))
