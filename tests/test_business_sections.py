from agent.basic_agents import AgentSettings, IndustryBusinessAgent
from agent.business_sections import competition_candidates, find_section, section_chunks
from agent.neon_agents import execute_report, to_report
from tests.test_neon_agents import bundle

BODY = '모의 사업 설명 문장입니다. ' * 40
DART = ['목 차', 'II. 사업의 내용 ........ 5', 'III. 재무에 관한 사항 ........ 30',
        'II. 사업의 내용', '1. 사업의 개요', BODY, '2. 주요 제품 및 서비스', '주요 고객은 완성품 업체입니다.',
        'III. 재무에 관한 사항', '재무 내용']


def chunks(lines, title='사업보고서 (2025.12)'):
    return [{'doc_id': 1, 'chunk_id': 100 + i, 'chunk_idx': i, 'content': line, 'title': title,
             'url': 'https://example.com/r', 'published_at': '2026-03-10', 'source': 'dart'}
            for i, line in enumerate(lines)]


def test_dart_section_skips_toc_and_records_subsections():
    found, inside = section_chunks(chunks(DART))
    assert found['status'] == 'found' and found['standard'] == 'DART'
    assert found['endHeading'] == 'III. 재무에 관한 사항'
    assert [s['title'] for s in found['subsections']] == ['1. 사업의 개요', '2. 주요 제품 및 서비스']
    assert found['chunkRange'] == [3, 7]
    assert inside[-1]['section']['subsection'] == '2. 주요 제품 및 서비스'


def test_toc_only_and_not_found():
    assert find_section('\n'.join(DART[:3]))['status'] == 'toc_only'
    assert find_section('II. 사업의 내용\n짧음\nIII. 재무에 관한 사항')['status'] == 'toc_only'
    assert find_section('사업과 관계없는 본문')['status'] == 'not_found'


def test_sec_item_1_business():
    text = ('Table of Contents\nItem 1. Business   3\nItem 1A. Risk Factors   10\n'
            'Item 1. Business\n' + 'We design products. ' * 40 + '\nItem 1A. Risk Factors\nrisks')
    found = find_section(text)
    assert found['status'] == 'found' and found['standard'] == 'SEC'
    assert text[found['start']:found['end']].startswith('Item 1. Business\nWe design')


def test_report_uses_only_section_chunks_and_records_location():
    b = bundle()
    b['chunks'] = chunks(DART)
    r = to_report(b, {})
    assert r['sectionDetection'][0]['status'] == 'found'
    used = [e['location']['chunk_idx'] for e in r['evidence'] if e['evidenceId'].startswith('IND_')]
    assert used == [5, 7]  # 목차·제목 줄·재무 장은 제외
    assert r['evidence'][-1]['location']['section']['heading'] == 'II. 사업의 내용'
    assert '사업의 내용 > 2. 주요 제품 및 서비스' in r['claims'][-1]['text']


def test_periodic_report_without_section_is_excluded_and_withheld():
    b = bundle()
    b['chunks'] = chunks(['본문만 있고 장 제목이 없음'])
    r = to_report(b, {})
    assert r['claims'] == []
    gate, result = execute_report(r, IndustryBusinessAgent(settings=AgentSettings(window=3)),
                                  'industry_business_model', reference_date='2026-10-28')
    assert gate['status'] == result['status'] == 'withheld'
    assert any(c['규칙'].startswith('business_section') for c in gate['checks'])


def test_ir_documents_read_whole():
    b = bundle()
    b['chunks'] = chunks(['IR 발표 내용'], title='2026 IR 자료')
    assert len(to_report(b, {})['claims']) == 1


def test_competition_candidates_are_labelled_not_assessed():
    table = competition_candidates([{'evidenceId': 'E1', 'excerpt': '주요 원재료는 공급업체에서 매입하며 경쟁사가 많다'}])
    rows = {t['factor']: t for t in table}
    assert rows['산업 내 경쟁']['evidenceIds'] == ['E1']
    assert '평가 아님' in rows['산업 내 경쟁']['assessment']
    assert rows['공급자 교섭력']['candidateExcerpts'][0]['snippet']
    assert rows['대체재']['assessment'] == '자료 미확보'
