import json

import pytest

from agent.notebook_viewer import load_reports, render_report, source_text


@pytest.mark.parametrize('version,claim', [(1, 'C01'), (1, 'C02'), (2, 'C01'), (2, 'C02')])
def test_notebook_views(version, claim):
    reports = load_reports()
    before = json.dumps(reports, ensure_ascii=False)
    html = render_report(reports[version], claim)
    assert '교육용 합성 예시' in html and '버전 변경 이력' in html
    assert '선택한 주장 ' + claim in html
    assert json.dumps(reports, ensure_ascii=False) == before
    assert '<script' not in html
    if version == 2 and claim == 'C01':
        assert '이전 연결을 자동 승계하지 않았습니다' in html
        assert '원래 대상의 반론 O01' in html
    if claim == 'C02':
        assert 'CAL01' in html and '/observations' in html


def test_source_path_boundary():
    report = load_reports()[1]
    report['documents'][0]['path'] = '../outside.md'
    with pytest.raises(ValueError, match='Only example'):
        source_text(report, 'D01')
