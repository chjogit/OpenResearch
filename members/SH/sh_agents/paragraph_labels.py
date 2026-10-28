"""Human-labelled paragraph classification baseline for the industry Agent.

Workflow: export the Agent's section paragraphs to CSV -> people fill `human_label` -> load and validate ->
score the keyword rule baseline against those labels. The export never pre-fills the rule's guess, so
labellers are not anchored by it. The rule baseline is the yardstick any later ML model must beat.
"""
import csv
import hashlib
from collections import Counter
from pathlib import Path

RULE_VERSION = 'paragraph-keyword-1'
LABELS = {
    'business_overview': '사업 개요',
    'products_services': '제품·서비스',
    'revenue_orders': '매출·수주',
    'customers': '고객·판매처',
    'suppliers_materials': '원재료·공급·생산설비',
    'competition': '경쟁·시장점유율',
    'barriers_regulation': '진입장벽·규제·특허',
    'rnd_contracts': '연구개발·주요계약',
    'risk_management': '위험관리·파생거래',
    'other': '기타·분류 불가',
}
# Paragraph keywords first (more specific), then the DART subsection heading as a fallback hint.
KEYWORDS = [
    ('competition', ['경쟁', '시장점유율', '점유율', 'competitor', 'competition', 'market share']),
    ('barriers_regulation', ['진입장벽', '진입 장벽', '특허', '인허가', '규제', 'patent', 'regulation']),
    ('customers', ['주요 고객', '주요고객', '매출처', '판매처', '판매경로', 'customer']),
    ('suppliers_materials', ['원재료', '원자재', '매입처', '공급업체', '생산설비', '생산능력', '가동률', 'supplier']),
    ('revenue_orders', ['매출액', '매출 비중', '수주', '판매실적', 'revenue', 'backlog']),
    ('rnd_contracts', ['연구개발', '연구 개발', 'R&D', '라이선스', '기술도입', '계약']),
    ('risk_management', ['환율', '이자율', '파생', '헤지', '위험관리']),
    ('products_services', ['주요 제품', '제품', '서비스', 'product']),
]
SUBSECTION_HINTS = [
    ('사업의 개요', 'business_overview'), ('주요 제품', 'products_services'),
    ('원재료', 'suppliers_materials'), ('매출', 'revenue_orders'), ('위험관리', 'risk_management'),
    ('연구개발', 'rnd_contracts'), ('주요계약', 'rnd_contracts'),
]
SHEET_COLUMNS = ['evidenceId', 'documentId', 'documentVersion', 'title', 'publishedAt', 'subsection',
                 'text', 'human_label', 'labeler', 'note']
MIN_EVAL_SAMPLES = 50


def rule_classify(text, subsection=None):
    """Return (label, matched keyword or hint). Keyword order encodes priority."""
    lower = (text or '').lower()
    for label, words in KEYWORDS:
        for w in words:
            if w.lower() in lower:
                return label, w
    for hint, label in SUBSECTION_HINTS:
        if subsection and hint in subsection:
            return label, 'subsection:' + hint
    return 'other', None


def paragraphs(result_or_report):
    """Industry evidence rows (one stored chunk = one paragraph unit) with section location."""
    docs = {d['documentId']: d for d in result_or_report.get('documents', [])}
    rows = []
    for e in result_or_report['evidence']:
        if not e['evidenceId'].startswith('IND_'):
            continue
        section = (e.get('location') or {}).get('section') or {}
        doc = docs.get(e['documentId'], {})
        rows.append({'evidenceId': e['evidenceId'], 'documentId': e['documentId'],
                     'documentVersion': e['documentVersion'], 'title': doc.get('title'),
                     'publishedAt': doc.get('publishedAt'), 'subsection': section.get('subsection'),
                     'text': e['excerpt']})
    return rows


def classify_result(result):
    """Rule labels for a result's evidence. Marked unreviewed; never replaces a human label."""
    out = []
    for e in result.get('evidence', []):
        section = (e.get('location') or {}).get('section') or {}
        label, matched = rule_classify(e.get('excerpt'), section.get('subsection'))
        out.append({'evidenceId': e['evidenceId'], 'label': label, 'labelName': LABELS[label],
                    'matched': matched, 'method': RULE_VERSION, 'reviewStatus': 'unreviewed'})
    return out


def export_sheet(rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow({**{k: r.get(k) for k in SHEET_COLUMNS}, 'human_label': '', 'labeler': '', 'note': ''})
    return path


def load_labels(path):
    """Read a filled sheet. Blank labels are skipped; unknown labels raise with the row number."""
    labelled = []
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        for n, r in enumerate(csv.DictReader(f), start=2):
            label = (r.get('human_label') or '').strip()
            if not label:
                continue
            if label not in LABELS:
                names = {v: k for k, v in LABELS.items()}
                if label not in names:
                    raise ValueError(f'{n}행: 알 수 없는 분류 "{label}". 허용: ' + ', '.join(LABELS))
                label = names[label]
            if not (r.get('labeler') or '').strip():
                raise ValueError(f'{n}행: labeler(분류한 사람)가 비어 있습니다.')
            labelled.append({**r, 'human_label': label})
    ids = [r['evidenceId'] for r in labelled]
    if len(ids) != len(set(ids)):
        raise ValueError('같은 evidenceId에 분류가 두 번 있습니다. 합의된 하나만 남기세요.')
    return labelled


def gold_digest(labelled):
    """Identifies the gold set so a model and the baseline are scored on the same rows."""
    key = sorted((r['evidenceId'], r.get('documentVersion') or '', r['human_label']) for r in labelled)
    return hashlib.sha256(repr(key).encode()).hexdigest()


def evaluate(labelled, predict=None):
    """Score predict(text, subsection) -> label against human labels (default: rule baseline)."""
    method = 'custom' if predict else RULE_VERSION
    predict = predict or (lambda text, sub: rule_classify(text, sub)[0])
    pairs = [(r['human_label'], predict(r.get('text'), r.get('subsection') or None)) for r in labelled]
    n = len(pairs)
    per_label = {}
    for label in LABELS:
        tp = sum(g == p == label for g, p in pairs)
        fp = sum(p == label and g != label for g, p in pairs)
        fn = sum(g == label and p != label for g, p in pairs)
        support = tp + fn
        if not support and not fp:
            continue
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_label[label] = {'precision': precision, 'recall': recall, 'f1': f1, 'support': support}
    supported = [v['f1'] for v in per_label.values() if v['support']]
    warnings = []
    if n < MIN_EVAL_SAMPLES:
        warnings.append(f'정답 문단 {n}개: {MIN_EVAL_SAMPLES}개 미만이라 수치가 불안정합니다.')
    if len({r.get('documentId') for r in labelled}) < 3:
        warnings.append('문서 3건 미만: 특정 회사·문서 형식에 치우칠 수 있습니다.')
    return {'n': n, 'accuracy': sum(g == p for g, p in pairs) / n if n else None,
            'macroF1': sum(supported) / len(supported) if supported else None,
            'perLabel': per_label, 'confusion': Counter(f'{g}->{p}' for g, p in pairs if g != p).most_common(10),
            'goldDigest': gold_digest(labelled), 'method': method,
            'warnings': warnings}


def split_by_document(labelled, test_share=0.3):
    """Hold out whole documents (newest first) so paragraphs of one filing never sit on both sides."""
    if not 0 < test_share < 1:
        raise ValueError('test_share must be between 0 and 1')
    docs = sorted({(r.get('publishedAt') or '', r['documentId']) for r in labelled}, reverse=True)
    held = {d for _, d in docs[:max(1, round(len(docs) * test_share))]}
    return ([r for r in labelled if r['documentId'] not in held],
            [r for r in labelled if r['documentId'] in held])
