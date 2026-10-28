"""Locate the business-description section in stored DART/SEC report chunks.

Detection is heading-based: DART "II. 사업의 내용" up to the next chapter, SEC "Item 1. Business" up to
"Item 1A/2". Table-of-contents entries are skipped. Finding a section says where the text sits, not that
its content supports any claim.
"""
import re

DART_START = re.compile(r'^[ \t]*(?:II|Ⅱ|2)[ \t]*[.．][ \t]*사업의[ \t]*내용'
                        r'[ \t]*(?:(?:\.{3,}|·{3,}|…{2,}|[ \t]{2,})[ \t]*\d+)?[ \t]*$', re.MULTILINE)
DART_CHAPTER = re.compile(r'^[ \t]*(?:III|IV|V|VI{0,3}|IX|X|XI{1,2}|Ⅲ|Ⅳ|Ⅴ|Ⅵ|Ⅶ|Ⅷ|Ⅸ|Ⅹ)[ \t]*[.．][ \t]*\S.*$', re.MULTILINE)
DART_SUB = re.compile(r'^[ \t]*([1-9])[ \t]*[.．][ \t]*(\S[^\n]{0,40})$', re.MULTILINE)
SEC_START = re.compile(r'^[ \t]*item[ \t]*1[ \t]*[.:\-—][ \t]*business\b.*$', re.MULTILINE | re.IGNORECASE)
SEC_END = re.compile(r'^[ \t]*item[ \t]*(?:1A|1B|1C|2)[ \t]*[.:\-—].*$', re.MULTILINE | re.IGNORECASE)
TOC_LINE = re.compile(r'(?:\.{3,}|·{3,}|…{2,}|-{3,})[ \t]*\d+[ \t]*$|[ \t]{2,}\d{1,3}[ \t]*$')
MIN_SECTION_CHARS = 400  # 다음 장 제목이 이보다 가까우면 목차 항목으로 봅니다.

COMPETITION_KEYWORDS = {
    '산업 내 경쟁': ['경쟁', '시장점유율', '점유율', 'competition', 'competitor', 'market share'],
    '진입 장벽': ['진입장벽', '진입 장벽', '특허', '인허가', '규제', 'barrier', 'patent', 'license'],
    '대체재': ['대체재', '대체 ', 'substitute'],
    '고객 교섭력': ['주요 고객', '주요고객', '매출처', '거래처', 'customer'],
    '공급자 교섭력': ['원재료', '공급자', '공급업체', '매입처', 'supplier', 'raw material'],
}


def join_chunks(chunks):
    """Concatenate chunks in chunk_idx order with '\n'; returns text and [(start, end, chunk)] spans."""
    text, spans, pos = [], [], 0
    for c in sorted(chunks, key=lambda c: c['chunk_idx']):
        content = c.get('content') or ''
        spans.append((pos, pos + len(content), c))
        text.append(content)
        pos += len(content) + 1
    return '\n'.join(text), spans


def _is_toc(text, match, end_pos):
    return bool(TOC_LINE.search(match.group(0))) or end_pos - match.end() < MIN_SECTION_CHARS


def find_section(text, standard=None):
    """Return dict(status found/toc_only/not_found, standard, start, end, headings, subsections)."""
    patterns = []
    if standard in (None, 'DART'):
        patterns.append(('DART', DART_START, DART_CHAPTER))
    if standard in (None, 'SEC'):
        patterns.append(('SEC', SEC_START, SEC_END))
    toc_seen = False
    for name, start_re, end_re in patterns:
        for m in start_re.finditer(text):
            end_m = end_re.search(text, m.end())
            end = end_m.start() if end_m else len(text)
            if _is_toc(text, m, end):
                toc_seen = True
                continue
            subsections = []
            if name == 'DART':
                subsections = [{'title': (s.group(1) + '. ' + s.group(2)).strip(), 'offset': s.start()}
                               for s in DART_SUB.finditer(text, m.end(), end)
                               if not TOC_LINE.search(s.group(0))]
            return {'status': 'found', 'standard': name, 'start': m.start(), 'end': end,
                    'startHeading': m.group(0).strip(), 'endHeading': end_m.group(0).strip() if end_m else None,
                    'subsections': subsections}
    return {'status': 'toc_only' if toc_seen else 'not_found', 'standard': standard}


def section_chunks(chunks, standard=None):
    """Chunks overlapping the detected section, each annotated with section location metadata."""
    text, spans = join_chunks(chunks)
    found = find_section(text, standard)
    if found['status'] != 'found':
        return found, []
    out = []
    for start, end, chunk in spans:
        if end <= found['start'] or start >= found['end']:
            continue
        sub = [s['title'] for s in found['subsections'] if s['offset'] < end]
        out.append({**chunk, 'section': {
            'standard': found['standard'], 'heading': found['startHeading'],
            'subsection': sub[-1] if sub else None,
            'characters': [max(found['start'], start) - start, min(found['end'], end) - start]}})
    found['chunkRange'] = [out[0]['chunk_idx'], out[-1]['chunk_idx']] if out else None
    return found, out


def competition_candidates(evidence, per_factor=5, context=80):
    """Keyword-matched excerpt candidates per competition factor. Not an assessment of strength."""
    table = []
    for factor, words in COMPETITION_KEYWORDS.items():
        hits = []
        for e in evidence:
            text = e.get('excerpt') or ''
            lower = text.lower()
            pos = min((p for p in (lower.find(w.lower()) for w in words) if p >= 0), default=-1)
            if pos >= 0:
                hits.append({'evidenceId': e['evidenceId'],
                             'snippet': text[max(0, pos - context):pos + context].replace('\n', ' ')})
        table.append({'factor': factor,
                      'assessment': f'후보 발췌 {len(hits)}건(키워드 일치, 관련성·강도 평가 아님)' if hits
                      else '자료 미확보',
                      'evidenceIds': [h['evidenceId'] for h in hits[:per_factor]],
                      'candidateExcerpts': hits[:per_factor]})
    return table
