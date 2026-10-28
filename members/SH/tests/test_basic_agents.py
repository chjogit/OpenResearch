from copy import deepcopy

import pytest
from examples.research_example import build_example
from sh_agents.basic_agents import (
    AgentSettings,
    DemoLLM,
    IndustryBusinessAgent,
    TechnicalAnalysisAgent,
    compare_results,
)
from sh_agents.research_contract import seal_report


def test_two_agents_no_api_and_source_unchanged():
    report = build_example()
    before = deepcopy(report)
    industry = IndustryBusinessAgent(DemoLLM()).run(report)
    tech = TechnicalAnalysisAgent(DemoLLM()).run(report)
    assert report == before
    assert industry['calculations'][0]['result'] == 10
    assert industry['calculations'][0]['unit'] == 'percentage_points'
    assert tech['calculations'][0]['result'] == 99
    assert tech['explanationStatus'] == 'offline_demo'
    assert tech['status'] == 'partial'
    assert compare_results(industry, tech)['verificationStatus'] == 'not_verified'


@pytest.mark.parametrize('change', [
    lambda rows: rows[0].update(close=None),
    lambda rows: rows[0].update(close=float('nan')),
    lambda rows: rows[0].update(close=-1),
    lambda rows: rows[0].update(day=rows[1]['day']),
    lambda rows: rows[0].update(volume=-1),
])
def test_bad_prices_withheld(change):
    import json
    report = build_example()
    rows = json.loads(report['evidence'][2]['excerpt'])
    change(rows)
    # NaN in a quoted raw source is still rejected by the numerical checker.
    report['evidence'][2]['excerpt'] = json.dumps(rows)
    report = seal_report(report)
    result = TechnicalAnalysisAgent().run(report)
    assert result['status'] == 'withheld'
    assert result['calculations'] == []


def test_short_period_actual_guard_and_no_model():
    report = build_example()
    assert TechnicalAnalysisAgent(settings=AgentSettings(window=20)).run(report)['status'] == 'withheld'
    report['dataMode'] = 'actual'
    for d in report['documents']:
        d['dataMode'] = 'actual'
    report = seal_report(report)
    assert TechnicalAnalysisAgent().run(report)['status'] == 'withheld'


def test_model_hook_and_llm_failure_preserve_numbers():
    class Model:
        def predict(self, payload):
            payload['calculations'].clear()
            return {'modelVersion': 'not-trained', 'trainingCutoff': None, 'status': 'not_run',
                    'output': None, 'limitations': ['연결 위치 예시']}
    class Broken:
        def explain(self, *args):
            raise RuntimeError('secret')
    result = TechnicalAnalysisAgent(Broken(), model_tool=Model()).run(build_example())
    assert result['calculations'][0]['result'] == 99
    assert result['explanationStatus'] == 'failed'
    assert result['modelResults'][0]['status'] == 'not_run'
    assert 'secret' not in str(result)


def test_mismatched_report_rejected():
    report = build_example()
    industry = IndustryBusinessAgent().run(report)
    tech = TechnicalAnalysisAgent().run(report)
    tech['contentRevision'] += 1
    with pytest.raises(ValueError):
        compare_results(industry, tech)
    with pytest.raises(ValueError):
        AgentSettings(window=0)


def test_actual_dates_require_metadata_and_reject_future():
    import json
    report = build_example()
    report['dataMode'] = 'actual'
    for doc in report['documents']:
        doc['dataMode'] = 'actual'
    rows = json.loads(report['evidence'][2]['excerpt'])
    for i, row in enumerate(rows):
        row['day'] = f'2026-10-{20+i:02d}'
    report['evidence'][2]['excerpt'] = json.dumps(rows)
    report = seal_report(report)
    metadata = {'adjustment': 'unadjusted', 'sourceDescription': 'test-only declared basis'}
    assert TechnicalAnalysisAgent().run(report, price_metadata=metadata)['calculations'][0]['result'] == 99
    rows[-1]['day'] = '2026-10-30'
    report['evidence'][2]['excerpt'] = json.dumps(rows)
    report = seal_report(report)
    assert TechnicalAnalysisAgent().run(report, price_metadata=metadata)['status'] == 'withheld'


def test_optional_model_failure_keeps_python_result():
    class BrokenModel:
        def predict(self, payload):
            raise RuntimeError('private error')
    result = TechnicalAnalysisAgent(model_tool=BrokenModel()).run(build_example())
    assert result['calculations'][0]['result'] == 99
    assert result['modelResults'] == []
    assert 'private error' not in str(result)
