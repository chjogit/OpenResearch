from copy import deepcopy

from agent.basic_agents import AgentSettings
from agent.result_verifier import verify_result
from tests.test_neon_agents import bundle, run


def test_verifier_detects_result_tamper():
    report, (_, result) = run(bundle())
    assert verify_result(report, result, AgentSettings())['status'] == 'review_required'
    modified = deepcopy(result)
    modified['calculations'][0]['result'] = 999
    assert verify_result(report, modified, AgentSettings())['status'] == 'failed'


def test_verifier_does_not_approve_llm_or_override_hold():
    report, (_, result) = run(bundle(), policy={})
    assert verify_result(report, result, AgentSettings())['status'] == 'withheld'
    result['explanation'] = 'fabricated'
    assert verify_result(report, result, AgentSettings())['status'] == 'failed'
    report, (_, result) = run(bundle())
    result['explanation'] = 'unchecked text'
    assert verify_result(report, result, AgentSettings())['status'] == 'review_required'


def test_verifier_rejects_changed_input():
    report, (_, result) = run(bundle())
    report['asOf'] = '2026-10-29'
    assert verify_result(report, result, AgentSettings())['status'] == 'failed'
