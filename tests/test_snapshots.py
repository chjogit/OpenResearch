import json

import pytest

from agent.basic_agents import AgentSettings, IndustryBusinessAgent, TechnicalAnalysisAgent, compare_results
from agent.neon_agents import execute_report
from agent.result_verifier import verify_result
from agent.snapshots import load_snapshot, mock_snapshot, reports_from_snapshot, save_results, save_snapshot

SETTINGS = AgentSettings(window=20)


def run_both(snapshot):
    report = reports_from_snapshot(snapshot)[0]
    out = {}
    for domain, cls in [('industry_business_model', IndustryBusinessAgent),
                        ('technical_analysis', TechnicalAnalysisAgent)]:
        _, out[domain] = execute_report(report, cls(settings=SETTINGS), domain, reference_date='2026-10-28',
                                        trading_dates=snapshot.get('mockTradingDates'), corporate_actions=[])
    return report, out


def test_mock_is_labelled_synthetic():
    snap = mock_snapshot()
    report = reports_from_snapshot(snap)[0]
    assert snap['dataMode'] == report['dataMode'] == 'synthetic'
    assert '모의' in snap['notice'] and all(d['dataMode'] == 'synthetic' for d in report['documents'])


def test_both_agents_share_digest_and_can_be_compared():
    report, out = run_both(mock_snapshot())
    ind, tech = out['industry_business_model'], out['technical_analysis']
    assert ind['inputDigest'] == tech['inputDigest'] == report['digest']
    assert ind['claims'] and tech['calculations']
    assert compare_results(ind, tech)['verificationStatus'] == 'not_verified'
    assert verify_result(report, ind, SETTINGS)['status'] == 'review_required'
    assert verify_result(report, tech, SETTINGS)['status'] == 'review_required'


def test_snapshot_roundtrip_and_tamper_detection(tmp_path):
    snap = mock_snapshot()
    path = save_snapshot(snap, tmp_path)
    loaded, latest = load_snapshot(folder=tmp_path)
    assert latest == path and loaded == snap
    assert reports_from_snapshot(loaded)[0]['digest'] == reports_from_snapshot(snap)[0]['digest']
    data = json.loads(path.read_text(encoding='utf-8'))
    data['bundles'][0]['prices'][0]['close'] = 1
    path.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError):
        load_snapshot(path)
    with pytest.raises(FileNotFoundError):
        load_snapshot(folder=tmp_path / 'empty')


def test_domain_scoped_load_checks():
    snap = mock_snapshot()
    snap['bundles'][0]['loadChecks'][0]['status'] = 'truncated'  # 가격만 상한 초과
    from agent.snapshots import _seal
    _, out = run_both(_seal({k: v for k, v in snap.items() if k != 'digest'}))
    assert out['technical_analysis']['status'] == 'withheld'
    assert out['industry_business_model']['status'] != 'withheld'


def test_save_blocked_on_failed_verification(tmp_path):
    report, out = run_both(mock_snapshot())
    tech = out['technical_analysis']
    good = verify_result(report, tech, SETTINGS)
    tech['calculations'][0]['result'] = 0
    bad = verify_result(report, tech, SETTINGS)
    assert bad['status'] == 'failed'
    path, message = save_results(tmp_path, 'technical_analysis', {'results': [tech]}, [good, bad])
    assert path is None and '저장 차단' in message and not list(tmp_path.rglob('*.json'))
    path, message = save_results(tmp_path, 'technical_analysis', {'results': []}, [])
    assert path is None
    path, message = save_results(tmp_path, 'technical_analysis', {'results': []}, [good])
    assert path.exists() and json.loads(path.read_text(encoding='utf-8'))['verifications'][0]['status']
