from contextlib import nullcontext
from copy import deepcopy
from decimal import Decimal
from typing import ClassVar

import pytest

from agent.basic_agents import AgentSettings, IndustryBusinessAgent, TechnicalAnalysisAgent
from agent.neon_agents import execute_report, load_company, to_report
from agent.research_contract import validate_report


def bundle():
    return {'company': {'company_id': 1, 'ticker': '005930', 'name': '시험 기업', 'market': 'KR'},
                'start': '2026-10-01', 'end': '2026-10-28', 'retrievedAt': '2026-10-28T00:00:00Z',
                'prices': [{'trade_date': f'2026-10-{d}', 'close': Decimal(str(d)), 'volume': 100,
                             'open': d, 'high': d+1, 'low': d-1, 'source': 'test'} for d in [26, 27, 28]],
                'chunks': [{'doc_id': 1, 'chunk_id': 2, 'chunk_idx': 0, 'content': '사업의 내용 시험 원문',
                             'url': 'https://example.com/fixture', 'published_at': '2026-10-27', 'title': '시험'}],
                'financials': [], 'loadChecks': []}


POLICY = {'test': {'adjustment': 'unadjusted', 'sourceDescription': '테스트에서만 쓰는 기준'}}


def run(b, domain='technical_analysis', policy=POLICY, llm=None):
    r = to_report(b, policy)
    cls = TechnicalAnalysisAgent if domain == 'technical_analysis' else IndustryBusinessAgent
    return r, execute_report(r, cls(settings=AgentSettings(window=3), llm=llm), domain,
                             reference_date='2026-10-28')


def test_conversion_trace_and_calculation():
    b = bundle()
    before = deepcopy(b)
    r, (gate, result) = run(b)
    validate_report(r)
    assert b == before
    assert gate['status'] == 'partial'
    assert result['calculations'][0]['result'] == 27
    assert result['inputDigest'] == r['digest']
    assert r['documents'][0]['hashScope'] == 'stored_db_excerpt'


@pytest.mark.parametrize('fault', ['null', 'duplicate', 'future', 'old', 'basis', 'truncated'])
def test_bad_prices_never_call_llm(fault):
    b = bundle()
    policy = POLICY
    if fault == 'null':
        b['prices'][0]['close'] = None
    if fault == 'duplicate':
        b['prices'][1]['trade_date'] = b['prices'][0]['trade_date']
    if fault == 'future':
        b['prices'][-1]['trade_date'] = '2026-10-29'
    if fault == 'old':
        for n, row in enumerate(b['prices']):
            row['trade_date'] = f'2026-10-{10+n}'
    if fault == 'basis':
        policy = {}
    if fault == 'truncated':
        b['loadChecks'] = [{'table': 'core.price_daily', 'status': 'truncated'}]
    class Spy:
        calls = 0
        def explain(self, *args):
            self.calls += 1
            return 'wrong'
    spy = Spy()
    _, (gate, result) = run(b, policy=policy, llm=spy)
    assert gate['status'] == result['status'] == 'withheld'
    assert result['calculations'] == []
    assert spy.calls == 0


def test_industry_requires_original_and_preserves_refs():
    b = bundle()
    r, (gate, result) = run(b, 'industry_business_model')
    assert gate['status'] == 'partial'
    assert result['claims'][0]['evidenceLinks'][0]['evidenceId'] == 'IND_E000'
    assert r['evidence'][-1]['location']['chunk_id'] == 2
    b['chunks'] = []
    _, (gate, result) = run(b, 'industry_business_model')
    assert gate['status'] == result['status'] == 'withheld'


def test_future_document_blocked():
    b = bundle()
    b['chunks'][0]['published_at'] = '2026-10-29'
    _, (gate, _) = run(b, 'industry_business_model')
    assert gate['status'] == 'withheld'


def test_loader_parameterization_truncation_and_redaction():
    class Inv:
        columns: ClassVar[dict] = {'core.price_daily': {'company_id': 'bigint', 'trade_date': 'date',
                                       'close': 'numeric', 'volume': 'bigint', 'source': 'text'}}
    class Conn:
        def transaction(self):
            return nullcontext()
        def execute(self, sql, params):
            assert sql.startswith('SELECT')
            assert 'company_id=%s' in sql
            assert params[0] == 1
            self.sql = sql
            return self
        def fetchall(self):
            return list(reversed(bundle()['prices']))
    b = load_company(Conn(), Inv(), bundle()['company'], '2026-10-01', '2026-10-28',
                     'technical_analysis', limit=2)
    assert b['loadChecks'][0]['status'] == 'truncated'
    assert [x['trade_date'] for x in b['prices']] == ['2026-10-27', '2026-10-28']
    class Broken(Conn):
        def execute(self, *args):
            raise RuntimeError('secret password')
    b = load_company(Broken(), Inv(), bundle()['company'], '2026-10-01', '2026-10-28', 'technical_analysis')
    assert b['loadChecks'][0]['status'] == 'unavailable'
    assert 'secret' not in str(b)

