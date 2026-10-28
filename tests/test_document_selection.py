from contextlib import nullcontext
from typing import ClassVar

from agent.document_selection import classify, read_chunks, select_documents
from agent.neon_agents import load_company


def doc(i, title, published, source='dart'):
    return {'doc_id': i, 'title': title, 'published_at': published, 'source': source}


def test_title_classification():
    assert classify('사업보고서 (2025.12)')[1] == 'annual'
    assert classify('[기재정정]사업보고서 (2025.12)')[1] == 'annual'
    assert classify('반기보고서 (2026.06)')[1] == 'semiannual'
    assert classify('분기보고서 (2026.09)')[1] == 'quarterly'
    assert classify('Form 10-K annual report', 'sec')[1] == 'annual'
    assert classify('2026년 3분기 실적발표 IR 자료', 'ir')[1] == 'ir'
    assert classify('아무 제목', 'ir')[1] == 'ir'
    assert classify('감사보고서 (2025.12)')[0] is None
    assert classify('주요사항보고서(자기주식취득결정)')[0] is None
    assert classify('삼성전자 주가 급등 뉴스', 'dart')[0] is None
    assert classify('')[0] is None


def test_priority_order_limit_and_skip_reasons():
    docs = [doc(1, '분기보고서 (2026.09)', '2026-11-14'), doc(2, '사업보고서 (2025.12)', '2026-03-10'),
            doc(3, '반기보고서 (2026.06)', '2026-08-14'), doc(4, 'IR 자료', '2026-10-01', 'ir'),
            doc(5, '분기보고서 (2026.03)', '2026-05-15'), doc(6, '뉴스 요약', '2026-10-02')]
    selected, skipped = select_documents(docs)
    assert [d['doc_id'] for d in selected] == [2, 3, 1]
    reasons = {s['doc_id']: s['reason'] for s in skipped}
    assert '상위 3건 밖' in reasons[5] and '상위 3건 밖' in reasons[4]
    assert '제목 규칙' in reasons[6]


def test_correction_replaces_same_period():
    docs = [doc(1, '사업보고서 (2025.12)', '2026-03-10'), doc(2, '[기재정정]사업보고서 (2025.12)', '2026-04-01')]
    selected, skipped = select_documents(docs)
    assert [d['doc_id'] for d in selected] == [2]
    assert skipped[0]['doc_id'] == 1 and '정정본' in skipped[0]['reason']


def test_read_chunks_keyset_pages_and_truncation():
    stored = [{'chunk_id': i, 'chunk_idx': i, 'content': str(i)} for i in range(250)]
    calls = []
    def page(doc_id, after, size):
        calls.append(after)
        return [c for c in stored if c['chunk_idx'] > after][:size]
    rows, status = read_chunks(page, 1)
    assert status == 'ok' and len(rows) == 250 and calls == [-1, 99, 199]
    rows, status = read_chunks(page, 1, max_chunks=150)
    assert status == 'truncated' and len(rows) == 150


class Inv:
    columns: ClassVar[dict] = {
        'core.financial_quarter': {'company_id': 'bigint', 'period_end': 'date', 'metric': 'text', 'amount': 'numeric'},
        'rag.document': dict.fromkeys(['doc_id', 'company_id', 'source', 'title', 'url', 'published_at'], 'text'),
        'rag.chunk': dict.fromkeys(['chunk_id', 'doc_id', 'chunk_idx', 'content'], 'text')}


class Conn:
    docs: ClassVar[list] = [{'doc_id': 1, 'source': 'dart', 'title': '사업보고서 (2025.12)', 'url': 'u1',
                             'published_at': '2026-03-10'},
                            {'doc_id': 2, 'source': 'dart', 'title': '뉴스', 'url': 'u2', 'published_at': '2026-03-11'}]

    def __init__(self):
        self.sql = []

    def transaction(self):
        return nullcontext()

    def execute(self, sql, params):
        self.sql.append(sql)
        assert sql.startswith('SELECT') and '%s' in sql
        if 'FROM rag.document' in sql:
            assert params[3] == ['dart', 'sec_edgar', 'opendart', 'sec', 'ir']
            self.rows = self.docs
        elif 'FROM rag.chunk' in sql:
            doc_id, after, _ = params
            assert doc_id == 1
            self.rows = [{'chunk_id': 10 + i, 'chunk_idx': i, 'content': f'c{i}'} for i in range(3) if i > after]
        else:
            self.rows = []
        return self

    def fetchall(self):
        return self.rows


def test_loader_selects_then_pages_chunks_with_doc_metadata():
    conn = Conn()
    b = load_company(conn, Inv(), {'company_id': 7, 'ticker': 'X', 'name': 'X', 'market': 'KR'},
                     '2026-01-01', '2026-10-28', 'industry_business_model')
    assert [c['chunk_idx'] for c in b['chunks']] == [0, 1, 2]
    assert b['chunks'][0]['url'] == 'u1' and b['chunks'][0]['title'] == '사업보고서 (2025.12)'
    assert b['documentSelection']['selected'][0]['doc_id'] == 1
    assert b['documentSelection']['skipped'][0]['doc_id'] == 2
    assert {c['table']: c['status'] for c in b['loadChecks']}['rag.chunk doc_id=1'] == 'ok'
    assert all(c['domain'] == 'industry_business_model' for c in b['loadChecks'])
    assert not any('core.price_daily' in s for s in conn.sql)


def test_shared_loader_tags_checks_by_domain():
    inv = Inv()
    inv.columns = {**Inv.columns, 'core.price_daily': {'company_id': 'bigint', 'trade_date': 'date',
                                                        'close': 'numeric', 'volume': 'bigint'}}
    b = load_company(Conn(), inv, {'company_id': 7, 'ticker': 'X', 'name': 'X', 'market': 'KR'},
                     '2026-01-01', '2026-10-28', 'shared')
    domains = {c['table']: c['domain'] for c in b['loadChecks']}
    assert domains['core.price_daily'] == 'technical_analysis'
    assert domains['rag.document'] == 'industry_business_model'
