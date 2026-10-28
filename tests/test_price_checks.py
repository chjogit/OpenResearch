import pytest

from agent.basic_agents import AgentSettings, TechnicalAnalysisAgent
from agent.neon_agents import execute_report, to_report
from agent.price_checks import (
    check_prices,
    large_moves,
    load_corporate_actions,
    load_trading_calendar,
    ohlc_issues,
)
from tests.test_neon_agents import POLICY, bundle

DAYS = ['2026-10-26', '2026-10-27', '2026-10-28']


def rows(closes=(100, 101, 102)):
    return [{'day': d, 'open': c, 'high': c + 1, 'low': c - 1, 'close': c, 'volume': 10}
            for d, c in zip(DAYS, closes)]


def status(checks, rule):
    return [c['status'] for c in checks if c['rule'] == rule]


@pytest.mark.parametrize('change, issue', [
    ({'high': 90}, '고가 < 저가'),
    ({'high': 100.5, 'open': 101}, '고가 < 시가/종가'),
    ({'low': 100.5}, '저가 > 시가/종가'),
    ({'low': 0}, '0 이하 가격'),
])
def test_ohlc_logic_violations(change, issue):
    data = rows()
    data[0].update(change)
    assert ohlc_issues(data)[0]['issue'] == issue
    assert status(check_prices(data), 'ohlc_logic') == ['hold']


def test_incomplete_ohlc_not_counted_as_logic_error():
    data = rows()
    data[0]['high'] = None
    assert ohlc_issues(data) == []


def test_limit_move_without_action_is_hold():
    data = rows((100, 140, 141))
    assert large_moves(data, 0.30)[0]['day'] == '2026-10-27'
    assert status(check_prices(data), 'daily_limit') == ['hold']
    assert status(check_prices(rows((100, 130, 131))), 'daily_limit') == ['pass']  # 상한가 자체는 허용


def test_limit_move_explained_by_action_is_partial_but_adjusted_split_is_hold():
    data = rows((100, 50, 51))
    split = [{'ticker': '005930', 'date': '2026-10-27', 'type': 'split', 'source': 'test'}]
    checks = check_prices(data, corporate_actions=split, ticker='005930', adjustment='unadjusted')
    assert status(checks, 'daily_limit') == ['partial']
    checks = check_prices(data, corporate_actions=split, ticker='005930', adjustment='split_adjusted')
    assert status(checks, 'adjustment_consistency') == ['hold']
    other = [{**split[0], 'ticker': '000660'}]
    assert status(check_prices(data, corporate_actions=other, ticker='005930'), 'daily_limit') == ['hold']


def test_unregistered_market_limit_and_missing_references_are_partial():
    checks = check_prices(rows(), market='US')
    assert status(checks, 'daily_limit') == ['partial']
    assert status(checks, 'calendar') == ['partial']
    assert status(checks, 'corporate_actions') == ['partial']
    assert status(check_prices(rows(), corporate_actions=[]), 'corporate_actions') == ['pass']


def test_calendar_missing_extra_and_coverage():
    assert status(check_prices(rows(), trading_dates=DAYS), 'calendar') == ['pass']
    data = rows()
    del data[1]
    assert status(check_prices(data, trading_dates=DAYS), 'calendar') == ['hold']
    holiday = check_prices(rows(), trading_dates=['2026-10-26', '2026-10-28'])
    assert status(holiday, 'calendar') == ['hold']
    assert status(check_prices(rows(), trading_dates=DAYS[:2]), 'calendar') == ['partial']


def test_csv_loaders(tmp_path):
    cal = tmp_path / 'cal.csv'
    cal.write_text('date,market\n2026-10-27,KR\n2026-10-26,KR\n2026-10-26,US\n', encoding='utf-8')
    assert [str(d) for d in load_trading_calendar(cal)] == ['2026-10-26', '2026-10-27']
    actions = tmp_path / 'actions.csv'
    actions.write_text('ticker,date,type,source\n005930,2026-10-27,split,공시 URL\n', encoding='utf-8')
    assert load_corporate_actions(actions)[0]['type'] == 'split'
    actions.write_text('ticker,date,type,source\n005930,2026-10-27,unknown,x\n', encoding='utf-8')
    with pytest.raises(ValueError):
        load_corporate_actions(actions)
    actions.write_text('ticker,date,type,source\n005930,2026-10-27,split,\n', encoding='utf-8')
    with pytest.raises(ValueError):
        load_corporate_actions(actions)


def test_gate_blocks_unexplained_jump_before_any_call():
    b = bundle()
    b['prices'][1].update(close=40, open=40, high=41, low=39)
    class Spy:
        calls = 0
        def explain(self, *args):
            Spy.calls += 1
            return 'x'
    report = to_report(b, POLICY)
    gate, result = execute_report(report, TechnicalAnalysisAgent(Spy(), settings=AgentSettings(window=3)),
                                  'technical_analysis', reference_date='2026-10-28')
    assert gate['status'] == result['status'] == 'withheld'
    assert Spy.calls == 0
    assert any(c['규칙'] == 'daily_limit' and c['판정'] == '보류' for c in gate['checks'])


def test_gate_with_calendar_and_actions_still_partial_not_approved():
    report = to_report(bundle(), POLICY)
    gate, result = execute_report(report, TechnicalAnalysisAgent(settings=AgentSettings(window=3)),
                                  'technical_analysis', reference_date='2026-10-28',
                                  trading_dates=DAYS, corporate_actions=[])
    rules = {c['규칙']: c['판정'] for c in gate['checks']}
    assert rules['calendar'] == rules['corporate_actions'] == rules['ohlc_logic'] == '실행 가능'
    assert gate['status'] == 'passed'  # 자동 규칙 통과일 뿐, 사람 검수·승인은 Verifier가 계속 요구합니다.
    assert result['calculations']
