"""Read-only Neon adapters for independently executable domain notebooks."""
import hashlib
import json
import math
from datetime import UTC, date, datetime
from decimal import Decimal

from agent.data_inventory import Inventory, _date_expr, _ident, _table, open_connection
from agent.quality_gate import assess_report, run_checked
from agent.research_contract import seal_report


def serial(value):
    if isinstance(value, dict):
        return {k: serial(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serial(v) for v in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def encode(value):
    return json.dumps(serial(value), ensure_ascii=False, sort_keys=True, allow_nan=False)


def load_company(conn, inv, company, start, end, domain, limit=2000):
    if domain not in {'industry_business_model', 'technical_analysis'}:
        raise ValueError('Unknown Agent')
    start, end = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    if start > end or not 1 <= limit <= 5000:
        raise ValueError('Invalid date range / row limit')
    bundle = {'company': serial(company), 'start': str(start), 'end': str(end),
                  'retrievedAt': datetime.now(UTC).isoformat(),
                  'prices': [], 'financials': [], 'chunks': [], 'loadChecks': []}

    def query(table, sql, params, cap=limit):
        try:
            with conn.transaction():
                rows = conn.execute(sql, (*params, cap + 1)).fetchall()
            bundle['loadChecks'].append({'table': table, 'status': 'truncated' if len(rows) > cap else 'ok',
                                             'rows': min(len(rows), cap)})
            return serial(rows[:cap])
        except Exception:  # noqa: BLE001
            bundle['loadChecks'].append({'table': table, 'status': 'unavailable', 'rows': 0})
            return []

    def table_rows(table, date_col, fields):
        cols = inv.columns.get(table, {})
        if not {'company_id', date_col} <= cols.keys():
            bundle['loadChecks'].append({'table': table, 'status': 'schema_or_permission', 'rows': 0})
            return []
        fields = [f for f in fields if f in cols]
        expr = _date_expr(date_col, cols[date_col])
        return query(table, f'SELECT {",".join(_ident(f) for f in fields)} FROM {_table(table)} '
                     f'WHERE company_id=%s AND {expr} BETWEEN %s AND %s ORDER BY {expr} DESC LIMIT %s',
                     (company['company_id'], start, end))

    if domain == 'technical_analysis':
        bundle['prices'] = list(reversed(table_rows('core.price_daily', 'trade_date',
            ['company_id', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'source', 'collected_at'])))
    else:
        bundle['financials'] = table_rows('core.financial_quarter', 'period_end',
            ['company_id', 'period_end', 'metric', 'amount', 'currency', 'fiscal_year', 'fiscal_q'])
        dc, cc = inv.columns.get('rag.document', {}), inv.columns.get('rag.chunk', {})
        if ({'doc_id', 'company_id', 'source', 'title', 'url', 'published_at'} <= dc.keys()
                and {'chunk_id', 'doc_id', 'chunk_idx', 'content'} <= cc.keys()):
            bundle['chunks'] = query('rag.document + rag.chunk',
                'SELECT d.doc_id,d.source,d.title,d.url,d.published_at,c.chunk_id,c.chunk_idx,c.content '
                'FROM rag.document d JOIN rag.chunk c ON c.doc_id=d.doc_id '
                'WHERE d.company_id=%s AND d.published_at::date BETWEEN %s AND %s '
                'AND d.source=ANY(%s) ORDER BY d.published_at DESC,d.doc_id,c.chunk_idx LIMIT %s',
                (company['company_id'], start, end, ['dart', 'sec_edgar', 'opendart', 'sec', 'ir']), cap=50)
        else:
            bundle['loadChecks'].append({'table': 'rag.document + rag.chunk',
                                             'status': 'schema_or_permission', 'rows': 0})
    return bundle


def to_report(bundle, price_metadata_by_source=None):
    """Hashes identify stored excerpts, not original PDF versions."""
    bundle = serial(bundle)
    subject = bundle['company']
    r = {'schemaVersion': '1.0', 'reportId': 'neon-' + str(subject['company_id']) + '-' + bundle['end'],
             'contentRevision': 1, 'question': '기업 사업 근거 또는 가격·거래량 분석', 'asOf': bundle['end'],
             'dataMode': 'actual', 'status': 'partial', 'subject': subject, 'documents': [], 'evidence': [], 'claims': [],
             'calculations': [], 'map': {'nodes': [], 'edges': []}, 'agentResults': [], 'analysisRelations': [],
             'objections': [], 'history': [], 'checks': [], 'approvals': [], 'sourceSnapshot': bundle,
             'adapterVersion': 'neon-1', 'priceMetadata': {}}

    def evidence(eid, content, location, **metadata):
        digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
        doc = dict(documentId='D_' + eid, version=digest, sha256=digest,
                   dataMode='actual', hashScope='stored_db_excerpt', **metadata)
        r['documents'].append(doc)
        r['evidence'].append({'evidenceId': eid, 'documentId': doc['documentId'],
            'documentVersion': digest, 'location': location, 'excerpt': content, 'verificationStatus': 'unverified',
            'observationPeriod': bundle['start'] + ' ~ ' + bundle['end']})

    if bundle['prices']:
        prices = []
        for row in bundle['prices']:
            p = {'day': str(row.get('trade_date', ''))[:10]}
            for key in ['open', 'high', 'low', 'close', 'volume']:
                try:
                    value = float(row[key])
                    p[key] = value if math.isfinite(value) else None
                except (KeyError, TypeError, ValueError, OverflowError):
                    p[key] = None
            prices.append(p)
        evidence('E03', encode(prices), {'table': 'core.price_daily', 'company_id': subject['company_id']},
                 path='snapshot:core.price_daily', sourceType='db_snapshot')
        policies = price_metadata_by_source or {}
        sources = {p.get('source') for p in bundle['prices']}
        chosen = [policies.get(s, {}) for s in sources]
        if (chosen and all(p.get('sourceDescription') and p.get('adjustment') in
                           {'unadjusted', 'split_adjusted', 'total_return'} for p in chosen)
                and len({p['adjustment'] for p in chosen}) == 1):
            r['priceMetadata'] = {'adjustment': chosen[0]['adjustment'],
                    'sourceDescription': '; '.join(p['sourceDescription'] for p in chosen),
                    'sources': sorted(str(s) for s in sources)}

    for i, row in enumerate(bundle['chunks']):
        text = (row.get('content') or '').strip()
        if not text or not row.get('url'):
            continue
        eid, excerpt = f'IND_E{i:03}', text[:6000]
        evidence(eid, excerpt, {'table': 'rag.chunk', 'doc_id': row['doc_id'],
            'chunk_id': row['chunk_id'], 'chunk_idx': row['chunk_idx'], 'characters': [0, len(excerpt)]},
            originalUrl=row['url'], publishedAt=row.get('published_at'), title=row.get('title'),
            sourceType='stored_document_chunk')
        r['claims'].append({'claimId': f'IND_C{i:03}', 'claimVersion': 1, 'domain': 'industry_business_model',
            'kind': 'fact', 'text': 'DB 문서 발췌(관련성·내용 검수 전): ' + excerpt[:500],
            'horizon': str(row.get('published_at')), 'assessment': 'provisional',
            'evidenceLinks': [{'evidenceId': eid, 'relation': 'context'}], 'calculationIds': [],
            'missingInformation': ['사업 부문별 매출·고객·경쟁 근거의 관련성 및 원문 검수 필요'],
            'nextQuestions': ['사업의 내용·경쟁 강도·고객 및 공급자 원문을 대조하세요.']})
    return seal_report(r)


def fetch_reports(tickers, start, end, domain, *, market='KR', expected_role='agent_reader',
                  price_metadata_by_source=None):
    with open_connection(expected_role) as conn, conn.transaction():
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        inv = Inventory(conn)
        companies = inv.companies(tickers, market)
        missing = set(tickers) - {c['ticker'] for c in companies}
        if missing:
            raise ValueError('종목 마스터 미등록: ' + ', '.join(sorted(missing)))
        return [to_report(load_company(conn, inv, c, start, end, domain), price_metadata_by_source)
                for c in companies]


def execute_report(report, agent, domain, *, reference_date=None, max_price_age_days=5):
    gates, _ = assess_report(report, window=agent.settings.window, reference_date=reference_date,
                             max_price_age_days=max_price_age_days)
    gate = gates[domain]
    for item in report.get('sourceSnapshot', {}).get('loadChecks', []):
        if item['status'] != 'ok':
            gate['status'], gate['label'] = 'withheld', '보류'
            gate['reasons'].append(item['table'] + ': ' + item['status'])
    return gate, run_checked(agent, report, gate)

