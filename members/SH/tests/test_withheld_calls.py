"""A withheld result must not reach LLM or ML/DL, even when an Agent is run directly without the gate."""
import json

import pytest
from examples.research_example import build_example
from sh_agents.basic_agents import IndustryBusinessAgent, TechnicalAnalysisAgent
from sh_agents.research_contract import seal_report
from sh_agents.result_verifier import verify_result


class Forbidden:
    def explain(self, *args):
        pytest.fail('LLM called on withheld result')

    def predict(self, *args):
        pytest.fail('Model called on withheld result')


def short_report():
    r = build_example()
    rows = json.loads(r['evidence'][2]['excerpt'])[:1]
    r['evidence'][2]['excerpt'] = json.dumps(rows)
    return seal_report(r)


def test_technical_direct_run_withheld_blocks_calls():
    result = TechnicalAnalysisAgent(Forbidden(), model_tool=Forbidden()).run(short_report())
    assert result['status'] == 'withheld'
    assert result['explanation'] is None and result['modelResults'] == []
    assert any('호출하지 않았습니다' in x for x in result['limitations'])


def test_industry_direct_run_withheld_blocks_calls():
    r = build_example()
    r['claims'] = [c for c in r['claims'] if c['domain'] != 'industry_business_model']
    r['map']['edges'] = []
    r['agentResults'] = [a for a in r['agentResults'] if a['domain'] != 'industry_business_model']
    r['analysisRelations'], r['objections'] = [], []
    result = IndustryBusinessAgent(Forbidden(), model_tool=Forbidden()).run(seal_report(r))
    assert result['status'] == 'withheld' and result['explanationStatus'] == 'not_run'


def test_no_tools_means_no_extra_limitation():
    result = TechnicalAnalysisAgent().run(short_report())
    assert not any('호출하지 않았습니다' in x for x in result['limitations'])


def test_verifier_fails_explanation_on_withheld_result_even_if_gate_partial():
    from sh_agents.basic_agents import AgentSettings
    from sh_agents.quality_gate import assess_report, run_checked
    r = build_example()
    gates, _ = assess_report(r, reference_date='2026-10-27', window=20)
    gate = gates['technical_analysis']
    assert gate['status'] == 'withheld'  # 관측 부족은 gate에서도 보류
    settings = AgentSettings(window=20)
    result = run_checked(TechnicalAnalysisAgent(settings=settings), r, gate)
    result['explanation'] = 'injected'
    assert verify_result(r, result, settings)['status'] == 'failed'
