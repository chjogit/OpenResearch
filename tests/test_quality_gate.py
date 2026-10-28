import json
from copy import deepcopy

import pytest

from agent.basic_agents import AgentSettings, IndustryBusinessAgent, TechnicalAnalysisAgent
from agent.quality_gate import assess_report, gate_table, inventory_gate_table, run_checked
from agent.research_contract import seal_report
from examples.research_example import build_example


def actual_report():
    r = build_example()
    r['dataMode'] = 'actual'
    r['priceMetadata'] = {'adjustment': 'unadjusted', 'sourceDescription': 'test-only metadata'}
    for doc in r['documents']:
        doc['dataMode'] = 'actual'
    prices = json.loads(r['evidence'][2]['excerpt'])
    for i, p in enumerate(prices):
        p.update(day=f'2026-10-{20+i:02d}', open=100, high=103, low=95)
    r['evidence'][2]['excerpt'] = json.dumps(prices)
    return seal_report(r)


def test_synthetic_is_partial_and_original_unchanged():
    r = build_example()
    original = deepcopy(r)
    gates, checks = assess_report(r, reference_date='2026-10-27')
    assert all(g['status'] == 'partial' for g in gates.values())
    assert len(gate_table(gates)) == 2 and checks
    assert r == original


@pytest.mark.parametrize('fault', ['short', 'null', 'duplicate', 'future', 'old', 'metadata'])
def test_critical_price_faults_block_calls(fault):
    r = actual_report()
    rows = json.loads(r['evidence'][2]['excerpt'])
    if fault == 'short':
        rows = rows[:1]
    elif fault == 'null':
        rows[0]['close'] = None
    elif fault == 'duplicate':
        rows[0]['day'] = rows[1]['day']
    elif fault == 'future':
        rows[-1]['day'] = '2026-10-30'
    elif fault == 'old':
        for i, row in enumerate(rows):
            row['day'] = f'2026-09-{20+i:02d}'
    else:
        r.pop('priceMetadata')
    r['evidence'][2]['excerpt'] = json.dumps(rows)
    r = seal_report(r)
    gates, _ = assess_report(r, reference_date='2026-10-27')
    class ForbiddenLLM:
        def explain(self, *args):
            pytest.fail('LLM must not run when quality is withheld')
    class ForbiddenModel:
        def predict(self, *args):
            pytest.fail('Model must not run when quality is withheld')
    result = run_checked(TechnicalAnalysisAgent(ForbiddenLLM(), model_tool=ForbiddenModel()),
                         r, gates['technical_analysis'])
    assert result['status'] == 'withheld'
    assert result['explanationStatus'] == 'not_run'
    assert result['calculations'] == []


def test_industry_no_evidence_hold_and_source_checked_pass():
    r = actual_report()
    r['claims'][0]['evidenceLinks'] = []
    r = seal_report(r)
    gates, _ = assess_report(r, reference_date='2026-10-27')
    assert gates['industry_business_model']['status'] == 'withheld'
    r = actual_report()
    r['claims'][0].update(missingInformation=[], assessment='provisional')
    for e in r['evidence'][:2]:
        e['verificationStatus'] = 'support_checked'
    r = seal_report(r)
    gates, _ = assess_report(r, reference_date='2026-10-27')
    assert gates['industry_business_model']['label'] == '실행 가능'
    assert run_checked(IndustryBusinessAgent(), r, gates['industry_business_model'])['qualityGate']['status'] == 'passed'


def test_changed_input_or_window_requires_recheck():
    r = build_example()
    gates, _ = assess_report(r, reference_date='2026-10-27')
    with pytest.raises(ValueError):
        run_checked(TechnicalAnalysisAgent(settings=AgentSettings(window=4)), r, gates['technical_analysis'])
    r['question'] = 'changed'
    r = seal_report(r)
    with pytest.raises(ValueError):
        run_checked(TechnicalAnalysisAgent(), r, gates['technical_analysis'])


def test_inventory_partial_and_hold_distinguish_missing_query():
    rows = [{'종목': '005930', '기업': '테스트기업', '테이블': 'core.price_daily',
             '상태': '기간 내 보유', '건수': 5, '날짜 수': 5, '날짜 결측': 0,
             '최초': '2026-10-20', '최종': '2026-10-24', 'nullCounts': {'close': 0, 'volume': 0}}]
    table = inventory_gate_table(rows, start='2026-10-20', end='2026-10-27', reference_date='2026-10-27')
    assert table[0]['상태'] == '보류'
    assert table[1]['상태'] == '일부 가능'
    rows[0]['상태'] = '조회 실패'
    table = inventory_gate_table(rows, start='2026-10-20', end='2026-10-27', reference_date='2026-10-27')
    assert table[1]['상태'] == '보류'
