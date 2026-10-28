"""Read-only Neon adapters for independently executable domain notebooks."""
import hashlib
import json
import math
from datetime import UTC, date, datetime
from decimal import Decimal

from sh_agents.business_sections import section_chunks
from sh_agents.data_inventory import Inventory, _date_expr, _ident, _table, open_connection
from sh_agents.document_selection import MAX_DOCUMENTS, PERIODIC, classify, read_chunks, select_documents
from sh_agents.quality_gate import assess_report, run_checked
from sh_agents.research_contract import seal_report

DOMAINS = ('industry_business_model', 'technical_analysis')
# 실DB의 source 값은 담당자 확인 후 조정합니다. 뉴스/블로그를 사업 공시로 넣지 마세요.
ALLOWED_SOURCES = ('dart', 'sec_edgar', 'opendart', 'sec', 'ir')
MAX_DOCUMENT_ROWS = 200


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


def load_company(conn, inv, company, start, end, domain, limit=2000, *, sources=ALLOWED_SOURCES,
                 max_documents=MAX_DOCUMENTS):
    """domain: one Agent, or 'shared' to load both Agents' inputs in the caller's transaction."""
    if domain not in {*DOMAINS, 'shared'}:
        raise ValueError('Unknown Agent')
    start, end = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    if start > end or not 1 <= limit <= 5000:
        raise ValueError('Invalid date range / row limit')
    bundle = {'company': serial(company), 'start': str(start), 'end': str(end),
                  'retrievedAt': datetime.now(UTC).isoformat(), 'domain': domain,
                  'prices': [], 'financials': [], 'chunks': [], 'loadChecks': []}
    current = {'domain': domain}

    def check(table, status, rows):
        bundle['loadChecks'].append({'table': table, 'status': status, 'rows': rows, 'domain': current['domain']})

    def query(table, sql, params, cap=limit):
        try:
            with conn.transaction():
                rows = conn.execute(sql, (*params, cap + 1)).fetchall()
            check(table, 'truncated' if len(rows) > cap else 'ok', min(len(rows), cap))
            return serial(rows[:cap])
        except Exception:  # noqa: BLE001
            check(table, 'unavailable', 0)
            return []

    def table_rows(table, date_col, fields):
        cols = inv.columns.get(table, {})
        if not {'company_id', date_col} <= cols.keys():
            check(table, 'schema_or_permission', 0)
            return []
        fields = [f for f in fields if f in cols]
        expr = _date_expr(date_col, cols[date_col])
        return query(table, f'SELECT {",".join(_ident(f) for f in fields)} FROM {_table(table)} '
                     f'WHERE company_id=%s AND {expr} BETWEEN %s AND %s ORDER BY {expr} DESC LIMIT %s',
                     (company['company_id'], start, end))

    if domain in {'technical_analysis', 'shared'}:
        current['domain'] = 'technical_analysis'
        bundle['prices'] = list(reversed(table_rows('core.price_daily', 'trade_date',
            ['company_id', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'source', 'collected_at'])))
    if domain in {'industry_business_model', 'shared'}:
        current['domain'] = 'industry_business_model'
        bundle['financials'] = table_rows('core.financial_quarter', 'period_end',
            ['company_id', 'period_end', 'metric', 'amount', 'currency', 'fiscal_year', 'fiscal_q'])
        dc, cc = inv.columns.get('rag.document', {}), inv.columns.get('rag.chunk', {})
        if ({'doc_id', 'company_id', 'source', 'title', 'url', 'published_at'} <= dc.keys()
                and {'chunk_id', 'doc_id', 'chunk_idx', 'content'} <= cc.keys()):
            docs = query('rag.document',
                'SELECT doc_id,source,title,url,published_at FROM rag.document '
                'WHERE company_id=%s AND published_at::date BETWEEN %s AND %s AND source=ANY(%s) '
                'ORDER BY published_at DESC,doc_id LIMIT %s',
                (company['company_id'], start, end, list(sources)), cap=MAX_DOCUMENT_ROWS)
            selected, skipped = select_documents(docs, max_documents)
            bundle['documentSelection'] = {'rule': '사업보고서 > 반기보고서 > 분기보고서 > IR',
                                           'maxDocuments': max_documents, 'candidates': len(docs),
                                           'selected': [{k: d.get(k) for k in
                                                         ['doc_id', 'title', 'source', 'published_at',
                                                          'documentKind', 'priority']} for d in selected],
                                           'skipped': skipped}

            def fetch_page(doc_id, after, size):
                with conn.transaction():
                    return conn.execute('SELECT chunk_id,chunk_idx,content FROM rag.chunk '
                                        'WHERE doc_id=%s AND chunk_idx>%s ORDER BY chunk_idx LIMIT %s',
                                        (doc_id, after, size)).fetchall()

            for doc in selected:
                table = f'rag.chunk doc_id={doc["doc_id"]}'
                try:
                    rows, status = read_chunks(fetch_page, doc['doc_id'])
                except Exception:  # noqa: BLE001
                    check(table, 'unavailable', 0)
                    continue
                check(table, status, len(rows))
                meta = {k: doc.get(k) for k in ['doc_id', 'source', 'title', 'url', 'published_at']}
                bundle['chunks'] += [{**meta, **serial(row)} for row in rows]
        else:
            check('rag.document + rag.chunk', 'schema_or_permission', 0)
    return bundle


def document_sources(tickers, start, end, *, market='KR', expected_role='agent_reader'):
    """Distinct rag.document source values with counts and title samples, to agree on ALLOWED_SOURCES."""
    with open_connection(expected_role) as conn, conn.transaction():
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        companies = Inventory(conn).companies(tickers, market)
        rows = []
        for c in companies:
            for r in conn.execute(
                    'SELECT source,count(*) AS n,min(published_at) AS first,max(published_at) AS last,'
                    '(array_agg(title ORDER BY published_at DESC))[1:3] AS sample_titles '
                    'FROM rag.document WHERE company_id=%s AND published_at::date BETWEEN %s AND %s '
                    'GROUP BY source ORDER BY n DESC', (c['company_id'], start, end)).fetchall():
                rows.append({'종목': c['ticker'], 'source': r['source'], '건수': r['n'],
                             '최초': serial(r['first']), '최종': serial(r['last']),
                             '제목 예시': ' | '.join(t or '' for t in r['sample_titles'] or []),
                             '허용 목록 포함': r['source'] in ALLOWED_SOURCES})
        return rows


def to_report(bundle, price_metadata_by_source=None, *, data_mode='actual'):
    """Hashes identify stored excerpts, not original PDF versions. data_mode='synthetic' marks mock input."""
    if data_mode not in {'actual', 'synthetic'}:
        raise ValueError('Invalid data mode')
    bundle = serial(bundle)
    subject = bundle['company']
    r = {'schemaVersion': '1.0', 'reportId': 'neon-' + str(subject['company_id']) + '-' + bundle['end'],
             'contentRevision': 1, 'question': '기업 사업 근거 또는 가격·거래량 분석', 'asOf': bundle['end'],
             'dataMode': data_mode, 'status': 'partial', 'subject': subject, 'documents': [], 'evidence': [], 'claims': [],
             'calculations': [], 'map': {'nodes': [], 'edges': []}, 'agentResults': [], 'analysisRelations': [],
             'objections': [], 'history': [], 'checks': [], 'approvals': [], 'sourceSnapshot': bundle,
             'adapterVersion': 'neon-2', 'priceMetadata': {}, 'sectionDetection': []}

    def evidence(eid, content, location, **metadata):
        digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
        doc = dict(documentId='D_' + eid, version=digest, sha256=digest,
                   dataMode=data_mode, hashScope='stored_db_excerpt', **metadata)
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

    # Periodic reports: only chunks inside the detected business section become evidence.
    # IR and other selected documents are read whole. Detection outcome is recorded per document.
    sections, by_doc = {}, {}
    for row in bundle['chunks']:
        by_doc.setdefault(row.get('doc_id'), []).append(row)
    for doc_id, rows in by_doc.items():
        _, kind = classify(rows[0].get('title'), rows[0].get('source'))
        if kind not in PERIODIC:
            continue
        found, inside = section_chunks(rows)
        sections[doc_id] = {(c['chunk_id']): c['section'] for c in inside}
        r['sectionDetection'].append({'doc_id': doc_id, 'title': rows[0].get('title'),
            'status': found['status'], 'standard': found.get('standard'),
            'heading': found.get('startHeading'), 'endHeading': found.get('endHeading'),
            'chunkRange': found.get('chunkRange'),
            'subsections': [x['title'] for x in found.get('subsections', [])]})

    for i, row in enumerate(bundle['chunks']):
        text = (row.get('content') or '').strip()
        if not text or not row.get('url'):
            continue
        section = None
        if row.get('doc_id') in sections:
            section = sections[row['doc_id']].get(row['chunk_id'])
            if section is None or text in {section['heading'], section.get('subsection')}:
                continue  # outside the section, or a heading line with no content
        eid, excerpt = f'IND_E{i:03}', text[:6000]
        location = {'table': 'rag.chunk', 'doc_id': row['doc_id'],
                    'chunk_id': row['chunk_id'], 'chunk_idx': row['chunk_idx'], 'characters': [0, len(excerpt)]}
        if section:
            location['section'] = section
        evidence(eid, excerpt, location,
            originalUrl=row['url'], publishedAt=row.get('published_at'), title=row.get('title'),
            sourceType='stored_document_chunk')
        where = ''
        if section:
            where = '사업의 내용' + (' > ' + section['subsection'] if section.get('subsection') else '') + ', '
        r['claims'].append({'claimId': f'IND_C{i:03}', 'claimVersion': 1, 'domain': 'industry_business_model',
            'kind': 'fact', 'text': f'DB 문서 발췌({where}관련성·내용 검수 전): ' + excerpt[:500],
            'horizon': str(row.get('published_at')), 'assessment': 'provisional',
            'evidenceLinks': [{'evidenceId': eid, 'relation': 'context'}], 'calculationIds': [],
            'missingInformation': ['사업 부문별 매출·고객·경쟁 근거의 관련성 및 원문 검수 필요'],
            'nextQuestions': ['사업의 내용·경쟁 강도·고객 및 공급자 원문을 대조하세요.']})
    return seal_report(r)


def fetch_reports(tickers, start, end, domain, *, market='KR', expected_role='agent_reader',
                  price_metadata_by_source=None, sources=ALLOWED_SOURCES):
    with open_connection(expected_role) as conn, conn.transaction():
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        inv = Inventory(conn)
        companies = inv.companies(tickers, market)
        missing = set(tickers) - {c['ticker'] for c in companies}
        if missing:
            raise ValueError('종목 마스터 미등록: ' + ', '.join(sorted(missing)))
        return [to_report(load_company(conn, inv, c, start, end, domain, sources=sources),
                          price_metadata_by_source)
                for c in companies]


def execute_report(report, agent, domain, *, reference_date=None, max_price_age_days=5,
                   trading_dates=None, corporate_actions=None):
    gates, _ = assess_report(report, window=agent.settings.window, reference_date=reference_date,
                             max_price_age_days=max_price_age_days, trading_dates=trading_dates,
                             corporate_actions=corporate_actions)
    gate = gates[domain]
    for item in report.get('sourceSnapshot', {}).get('loadChecks', []):
        # Checks without a domain (older bundles) apply to both Agents.
        if item['status'] != 'ok' and item.get('domain', domain) == domain:
            gate['status'], gate['label'] = 'withheld', '보류'
            gate['reasons'].append(item['table'] + ': ' + item['status'])
    return gate, run_checked(agent, report, gate)
