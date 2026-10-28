import json
from copy import deepcopy

import pytest
from examples.research_example import ROOT, build_example
from sh_agents.persona_agents import build_linked_messages
from sh_agents.personas import PersonaProfile
from sh_agents.research_contract import (
    agent_view,
    attach_agent_context,
    content_digest,
    revise_claim,
    seal_report,
    validate_report,
)


def test_fixture_and_source_hashes():
    r = build_example()
    validate_report(r)
    assert r['calculations'][0]['result'] == 99
    assert r['claims'][1]['text'].startswith('마지막 종가 97')
    for name in ['a_company_report_v1.json', 'a_company_report_v2.json']:
        validate_report(json.loads((ROOT / 'examples/data' / name).read_text(encoding='utf-8')))


@pytest.mark.parametrize('mutation', [
    lambda r: r['claims'][0]['evidenceLinks'][0].update(evidenceId='absent'),
    lambda r: r['map']['edges'][0].update(claimVersion=99),
    lambda r: r['evidence'][0].update(documentVersion='missing'),
    lambda r: r['documents'][0].update(dataMode='actual'),
    lambda r: r['claims'].append(deepcopy(r['claims'][0])),
    lambda r: r['agentResults'][1]['claims'][0].update(claimId='C01'),
    lambda r: r['objections'][0].update(targetReportRevision=99),
    lambda r: r['calculations'][0].update(inputEvidenceIds=['missing']),
    lambda r: r['analysisRelations'][0]['claims'][0].update(claimVersion=99),
])
def test_bad_references(mutation):
    r = build_example()
    mutation(r)
    r['digest'] = content_digest(r)
    with pytest.raises(ValueError):
        validate_report(r)


def test_tampering():
    r = build_example()
    r['question'] = 'changed'
    with pytest.raises(ValueError, match='Digest'):
        validate_report(r)


def test_revision_preserves_history_invalidates_links_and_approval():
    r = build_example()
    r['checks'] = [{'status': 'passed'}]
    r['approvals'] = [{'status': 'approved'}]
    before = deepcopy(r)
    new = revise_claim(r, 'C01', text='수정된 주장', reason='반론 확인')
    assert r == before
    assert new['contentRevision'] == 2 and new['claims'][0]['claimVersion'] == 2
    assert new['history'][0] == before
    assert new['history'][0]['objections'][0]['target']['claimVersion'] == 1
    assert new['objections'] == new['checks'] == new['approvals'] == []
    assert new['claims'][0]['evidenceLinks'] == []
    assert new['analysisRelations'] == []
    assert new['agentResults'][0]['status'] == 'not_run'
    assert new['parentDigest'] == before['digest']
    validate_report(new)


def test_adapter_and_both_message_paths():
    r = build_example()
    original = deepcopy(r)
    context = {'stock_info': {'name': '가상 A기업'}, 'other_data': {'kept': True}}
    new = attach_agent_context(context, r)
    assert 'technical_data' not in context
    assert new['other_data'] == context['other_data']
    for key, domain in [('industry_bm_data', 'industry_business_model'),
                        ('technical_data', 'technical_analysis')]:
        assert new[key]['digest'] == r['digest']
        messages = build_linked_messages(r, PersonaProfile('L2', 'A', confirmed=True), data_key=key)
        payload = json.loads(messages[1]['content'].split('\n', 1)[1])
        assert payload['domain_data']['claims'] == agent_view(r, domain)['claims']
        assert 'claimVersion' in messages[0]['content']
    assert r == original


def test_unknown_domain_and_empty_revision():
    r = build_example()
    with pytest.raises(ValueError):
        agent_view(r, 'unknown')
    with pytest.raises(ValueError):
        revise_claim(r, 'C01', text='', reason='reason')
    assert seal_report(r) == r
