"""Choose which stored disclosures the industry Agent reads, and page through their chunks.

Priority by title: annual report > semiannual > quarterly > IR. Other titles (news, major-event filings,
audit reports) are skipped with a reason instead of being read as business-description sources.
"""
import re

MAX_DOCUMENTS = 3
PAGE_SIZE = 100
MAX_CHUNKS_PER_DOCUMENT = 2000

RULES = [  # (rank, kind, pattern)
    (0, 'annual', re.compile(r'사업보고서|\b10-K\b|\b20-F\b', re.IGNORECASE)),
    (1, 'semiannual', re.compile(r'반기보고서')),
    (2, 'quarterly', re.compile(r'분기보고서|\b10-Q\b', re.IGNORECASE)),
    (3, 'ir', re.compile(r'\bIR\b|기업설명회|실적\s*발표|investor\s+(relations|presentation)|earnings\s+(call|release)',
                         re.IGNORECASE)),
]
PERIODIC = {'annual', 'semiannual', 'quarterly'}
EXCLUDE = re.compile(r'감사보고서|첨부추가|주요사항|정정신고|철회', re.IGNORECASE)
PERIOD = re.compile(r'\((\d{4})[.\-/](\d{1,2})\)')


def classify(title, source=None):
    """Return (rank, kind) or (None, reason)."""
    title = (title or '').strip()
    if not title:
        return None, '제목 없음'
    if EXCLUDE.search(title):
        return None, '사업 원문 대상 아님(감사·주요사항·첨부 등)'
    for rank, kind, pattern in RULES:
        if pattern.search(title):
            return rank, kind
    if source == 'ir':
        return 3, 'ir'
    return None, '제목 규칙 불일치(사업·반기·분기보고서/IR 아님)'


def period_key(doc, kind):
    """Same report period and kind -> keep only the latest (corrected) filing."""
    match = PERIOD.search(doc.get('title') or '')
    return (kind, match.group(1) + '-' + match.group(2).zfill(2)) if match else (kind, 'doc:' + str(doc['doc_id']))


def select_documents(docs, max_documents=MAX_DOCUMENTS):
    """docs: rows with doc_id, title, source, published_at. Returns (selected, skipped)."""
    skipped, candidates = [], {}
    for doc in docs:
        rank, kind = classify(doc.get('title'), doc.get('source'))
        if rank is None:
            skipped.append({'doc_id': doc['doc_id'], 'title': doc.get('title'), 'reason': kind})
            continue
        key = period_key(doc, kind)
        current = candidates.get(key)
        if current is None or str(doc.get('published_at')) > str(current['doc'].get('published_at')):
            if current is not None:
                skipped.append({'doc_id': current['doc']['doc_id'], 'title': current['doc'].get('title'),
                                'reason': '같은 기간의 최신 정정본으로 대체'})
            candidates[key] = {'rank': rank, 'kind': kind, 'doc': doc}
        else:
            skipped.append({'doc_id': doc['doc_id'], 'title': doc.get('title'),
                            'reason': '같은 기간의 최신 정정본으로 대체'})
    # Rank first, newer first within a rank (two stable sorts).
    ordered = sorted(candidates.values(), key=lambda c: str(c['doc'].get('published_at')), reverse=True)
    ordered.sort(key=lambda c: c['rank'])
    selected = [{**c['doc'], 'documentKind': c['kind'], 'priority': c['rank']} for c in ordered[:max_documents]]
    for c in ordered[max_documents:]:
        skipped.append({'doc_id': c['doc']['doc_id'], 'title': c['doc'].get('title'),
                        'reason': f'우선순위 상위 {max_documents}건 밖'})
    return selected, skipped


def read_chunks(fetch_page, doc_id, *, page_size=PAGE_SIZE, max_chunks=MAX_CHUNKS_PER_DOCUMENT):
    """Keyset pagination by chunk_idx. fetch_page(doc_id, after_idx, limit) -> rows ordered by chunk_idx.

    Returns (rows, status) where status is 'ok' or 'truncated' (more than max_chunks stored).
    """
    rows, after = [], -1
    while True:
        page = fetch_page(doc_id, after, page_size)
        rows.extend(page)
        if len(rows) > max_chunks:
            return rows[:max_chunks], 'truncated'
        if len(page) < page_size:
            return rows, 'ok'
        after = page[-1]['chunk_idx']
