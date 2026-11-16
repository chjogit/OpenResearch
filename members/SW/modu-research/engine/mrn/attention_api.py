"""v0.27: 관심 체온계 API — server.create_app 에서 register(app) 한 줄로 붙인다."""
from fastapi import HTTPException


def register(app):
    from . import attention as A
    from .market import SnapshotError

    @app.get('/api/attention/thermo')
    def attention_thermo(company: str, cutoff: str = '', days: int = 20):
        if not 5 <= days <= 120:
            raise HTTPException(422, '보여 줄 기간은 5~120거래일이에요.')
        try:
            return A.thermo(company.strip(), cutoff, '', days)
        except SnapshotError as e:
            raise HTTPException(422, str(e))

    @app.get('/api/attention/search')
    def attention_search(cutoff: str = ''):
        from .datalab import DatalabError
        try:
            sp = A.search_panel(cutoff)
        except (SnapshotError, DatalabError) as e:
            raise HTTPException(422, str(e))
        if sp is None:
            return {'available': False, 'line': A.search_block(None, '')['line']}
        return {'available': True, 'model_calls': 0} | A.public_search(sp)

    @app.get('/api/attention/panel')
    def attention_panel(cutoff: str = ''):
        try:
            return A.public_panel(A.panel(cutoff)) | {'model_calls': 0, 'notice': A.NOTICE}
        except SnapshotError as e:
            raise HTTPException(422, str(e))
