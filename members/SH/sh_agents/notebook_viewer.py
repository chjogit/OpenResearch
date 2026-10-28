"""Notebook-native read-only viewer. Rendering helpers use only the standard library."""
import json
from html import escape
from pathlib import Path

from sh_agents.research_contract import validate_report

ROOT = Path(__file__).resolve().parents[1]
LABELS = {'fact': '사실', 'interpretation': '해석', 'forecast': '예측',
          'withheld': '판단 보류', 'provisional': '잠정 관찰', 'unverified': '미검증',
          'in_review': '검토 중', 'accept': '수용 의사', 'draft': '수정 초안', 'partial': '일부 완료'}


def text(value):
    if value == 'Changed claim needs new evidence review':
        value = '변경된 주장의 근거를 다시 검토해야 합니다.'
    return escape(str(value if value is not None else '미확인'))


def load_reports():
    reports = {}
    for version in (1, 2):
        report = json.loads((ROOT / f'examples/data/a_company_report_v{version}.json').read_text('utf-8-sig'))
        validate_report(report)
        reports[version] = report
    return reports


def source_text(report, document_id):
    doc = next(d for d in report['documents'] if d['documentId'] == document_id)
    path = (ROOT / doc['path']).resolve()
    allowed = (ROOT / 'examples/data').resolve()
    if not path.is_relative_to(allowed) or path.suffix not in {'.md', '.json'}:
        raise ValueError('Only example text sources are allowed')
    return path.read_text('utf-8-sig')


def render_report(report, claim_id='C01'):
    """HTML escapes all data. No Javascript, API calls, or file mutation."""
    validate_report(report)
    claim = next(c for c in report['claims'] if c['claimId'] == claim_id)
    parts = ['<div style="font-family:system-ui;color:#19314e;line-height:1.8">',
             '<h2>모두의 리서치 · 가상 A기업</h2>',
             '<p><b>교육용 합성 예시 · 읽기 전용 · 실제 투자 판단 아님</b></p>',
             f'<p>{text(report["question"])}</p>',
             (f'<p>보고서 {report["contentRevision"]}판 · {text(LABELS.get(report["status"], report["status"]))}'
             f' · 기준 {text(report["asOf"])}</p>'),
             '<h3>산업·사업모델 지도</h3><p>고객 → 제품·서비스 → 매출 → 비용 → 이익 → 위험</p>',
             '<p>위 순서는 사업 이해의 탐색 순서이며 모든 연결의 인과관계가 입증된 것은 아닙니다.</p>']
    for edge in report['map']['edges']:
        parts.append(f'<p>등록된 연결 {text(edge["edgeId"])}: 매출 → 이익 · '
                     f'{text(edge["claimId"])} / 주장 v{edge["claimVersion"]}</p>')
    parts.append('<h3>두 분석의 주장</h3><table style="border-collapse:collapse;width:100%">')
    for c in report['claims']:
        parts.append(f'<tr><td style="padding:10px;border:1px solid #ccd8e6">{text(c["claimId"])} · '
                     f'{"산업·사업모델" if c["domain"] == "industry_business_model" else "기술적 분석"}</td>'
                     f'<td style="padding:10px;border:1px solid #ccd8e6">{text(c["text"])}</td></tr>')
    parts.append('</table><h3>기술적 분석 · 합성 가격</h3>')
    prices = json.loads(source_text(report, 'D02'))['observations']
    parts.append('<p>' + ' → '.join(f'{text(p["day"])}: {p["close"]}' for p in prices) + '</p>')
    for calc in report['calculations']:
        parts.append(f'<p>{text(calc["calculationId"])}: {text(calc["formula"])} = '
                     f'{text(calc["result"])} {text(calc["unit"])}</p>')
    parts.append('<p>' + text(report['analysisRelations'][0]['explanation'] if report['analysisRelations']
                             else '수정된 주장과 다른 관점의 관계를 다시 검토해야 합니다.') + '</p>')
    parts.append(f'<hr><h3>선택한 주장 {text(claim_id)} · v{claim["claimVersion"]}</h3>'
                 f'<p>{text(claim["text"])}</p><p>{text(LABELS[claim["kind"]])} · '
                 f'{text(claim["horizon"])} · {text(LABELS[claim["assessment"]])}</p><h3>근거 원문</h3>')
    if not claim['evidenceLinks']:
        parts.append('<p>현재 버전의 근거 연결 없음. 이전 연결을 자동 승계하지 않았습니다.</p>')
    for link in claim['evidenceLinks']:
        e = next(e for e in report['evidence'] if e['evidenceId'] == link['evidenceId'])
        relation = {'supports': '지지', 'opposes': '반대', 'context': '참고'}[link['relation']]
        parts.append(f'<h4>{text(e["evidenceId"])} · {relation} · 문서 v{text(e["documentVersion"])}</h4>'
                     f'<p>위치: {text(json.dumps(e["location"], ensure_ascii=False))}<br>'
                     f'검증: {text(LABELS.get(e["verificationStatus"], e["verificationStatus"]))}</p>'
                     f'<blockquote>{text(e["excerpt"])}</blockquote><details><summary>전체 원문 펼치기</summary>'
                     f'<pre style="white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f5fa;padding:15px">'
                     f'{text(source_text(report, e["documentId"]))}</pre></details>')
    parts.append('<h3>부족한 자료와 다음 확인</h3><ul>' + ''.join(
        '<li>' + text(x) + '</li>' for x in claim['missingInformation'] + claim['nextQuestions']) + '</ul>')
    parts.append('<h3>현재 반론</h3>')
    objections = [o for o in report['objections'] if o['target']['claimId'] == claim_id]
    if not objections:
        parts.append('<p>현재 버전 반론 없음. 과거 반론은 아래 이력에 보존됩니다.</p>')
    for o in objections:
        parts.append(f'<p><b>{text(o["objectionId"])} · {text(LABELS.get(o["status"], o["status"]))}</b><br>'
                     f'{text(o["text"])}<br>작성자 응답: {text(o["authorResponse"])}<br>'
                     f'검토자 판단: {text(o["reviewerDecision"])} · 실제 반영: {text(o["implementation"])}</p>')
    parts.append('<h3>버전 변경 이력</h3>')
    for snapshot in report['history'] + [report]:
        c = next(c for c in snapshot['claims'] if c['claimId'] == claim_id)
        parts.append(f'<p><b>보고서 {snapshot["contentRevision"]}판 / 주장 v{c["claimVersion"]}</b><br>'
                     f'{text(c["text"])}<br>{text(snapshot.get("changeReason", "최초 합성 분석"))}<br>'
                     f'근거 {len(c["evidenceLinks"])}개 · 검사 {len(snapshot["checks"])}개 · '
                     f'승인 {len(snapshot["approvals"])}개</p>')
        for o in snapshot['objections']:
            if o['target']['claimId'] == claim_id:
                parts.append(f'<p>원래 대상의 반론 {text(o["objectionId"])}: {text(o["text"])}<br>'
                             f'검토자 판단 {text(o["reviewerDecision"])}, 실제 반영 {text(o["implementation"])}</p>')
    parts.append('<small>작성자의 수용 응답은 검토 승인·반영 완료를 뜻하지 않습니다.</small></div>')
    return ''.join(parts)


def show_viewer():
    """Requires an active Jupyter kernel and ipywidgets frontend support."""
    import ipywidgets as widgets
    from IPython.display import HTML, display

    reports = load_reports()
    version = widgets.Dropdown(options=[('1판 · 최초 분석', 1), ('2판 · 수정 초안', 2)], description='보고서:')
    claim = widgets.ToggleButtons(options=[('산업·사업모델 C01', 'C01'), ('기술적 분석 C02', 'C02')],
                                  description='주장:', layout=widgets.Layout(flex_flow='row wrap'))
    output = widgets.HTML()

    def refresh(change=None):
        output.value = render_report(reports[version.value], claim.value)

    version.observe(refresh, names='value')
    claim.observe(refresh, names='value')
    refresh()
    display(HTML('<h2 style="color:#183451">A기업 리서치 탐색기</h2>'))
    display(widgets.VBox([version, claim, output]))
    return {'version': version, 'claim': claim, 'output': output}
