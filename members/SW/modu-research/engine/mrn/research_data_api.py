"""v0.39.2 연구용 데이터 API — server.create_app 에서 register(app, store) 한 줄로 붙인다(기존 API는 그대로)."""
from fastapi import Request


def register(app, store):
    from . import research_data as RD

    @app.get('/api/research/flags')
    def research_flags():
        return RD.flags()

    @app.get('/api/quote/{ticker}')
    def research_quote(ticker: str):
        return RD.quote(ticker, store=store)

    @app.get('/api/consensus/{ticker}')
    def research_consensus(ticker: str, request: Request, cutoff: str = ''):
        from .broker import broker_dir, load_manifest, report_ticker
        reps, cands = store.broker_reports()
        man = load_manifest(broker_dir())
        files = {r['file'] for r in reps if (r.get('ticker') or report_ticker(man.get(r['file']))) == ticker}
        fs = [{'broker': c['broker'], 'report_date': c['report_date'], 'metric': c['metric'], 'fiscal_year': c['fiscal_year'], 'value': c['effective_value_mn']}
              for c in cands if c['file'] in files and c['state'] == 'approved']
        return RD.consensus(ticker, fs, until=(cutoff or None))
