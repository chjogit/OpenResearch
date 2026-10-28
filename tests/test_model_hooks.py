import itertools
import json
from statistics import pstdev

import pytest

from agent.basic_agents import AgentSettings, IndustryBusinessAgent, TechnicalAnalysisAgent
from agent.model_hooks import KeywordParagraphBaseline, NotTrainedHook, PersistenceVolatilityBaseline
from agent.neon_agents import execute_report
from agent.result_verifier import verify_result
from agent.snapshots import mock_snapshot, reports_from_snapshot

SETTINGS = AgentSettings(window=5)


def run(domain, model_tool, settings=SETTINGS):
    report = reports_from_snapshot(mock_snapshot())[0]
    cls = IndustryBusinessAgent if domain == 'industry_business_model' else TechnicalAnalysisAgent
    _, plain = execute_report(report, cls(settings=settings), domain, reference_date='2026-10-28')
    _, result = execute_report(report, cls(settings=settings, model_tool=model_tool), domain,
                               reference_date='2026-10-28')
    return report, plain, result


def test_paragraph_baseline_attaches_without_changing_values():
    report, plain, result = run('industry_business_model', KeywordParagraphBaseline())
    model = result['modelResults'][0]
    assert model['status'] == 'ok' and model['task'] == 'paragraph_classification'
    assert {r['evidenceId'] for r in model['output']} == {e['evidenceId'] for e in result['evidence']}
    for key in ['claims', 'evidence', 'calculations', 'status']:
        assert result[key] == plain[key]
    assert verify_result(report, result, SETTINGS)['status'] == 'review_required'


def test_volatility_baseline_matches_last_window_std():
    _, plain, result = run('technical_analysis', PersistenceVolatilityBaseline(window=5))
    model = result['modelResults'][0]
    closes = [p['close'] for p in json.loads(result['evidence'][0]['excerpt'])]
    returns = [b / a - 1 for a, b in itertools.pairwise(closes)]
    assert model['output']['predictedVolatility'] == pytest.approx(pstdev(returns[-5:]))
    assert result['calculations'] == plain['calculations']
    _, _, short = run('technical_analysis', PersistenceVolatilityBaseline(window=500))
    assert short['modelResults'][0]['status'] == 'not_run'


def test_wrong_task_or_bad_output_is_isolated():
    _, plain, result = run('technical_analysis', KeywordParagraphBaseline())  # 산업용 도구를 기술 Agent에
    assert result['modelResults'] == [] and result['calculations'] == plain['calculations']
    assert any('ML/DL 도구 실패' in x for x in result['limitations'])

    class BadLabel(KeywordParagraphBaseline):
        def predict(self, payload):
            out = super().predict(payload)
            out['output'][0]['label'] = 'buy_signal'
            return out
    _, _, result = run('industry_business_model', BadLabel())
    assert result['modelResults'] == []

    class BadVol(PersistenceVolatilityBaseline):
        def predict(self, payload):
            out = super().predict(payload)
            out['output']['predictedVolatility'] = float('nan')
            return out
    _, _, result = run('technical_analysis', BadVol(window=5))
    assert result['modelResults'] == []


def test_not_trained_hook_is_marked_and_rejects_unknown_task():
    _, _, result = run('industry_business_model', NotTrainedHook('paragraph_classification'))
    assert result['modelResults'][0]['modelVersion'] == 'not-trained'
    with pytest.raises(ValueError):
        NotTrainedHook('price_target')
    with pytest.raises(ValueError):
        PersistenceVolatilityBaseline(window=1)
