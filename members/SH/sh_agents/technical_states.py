"""Rules that describe the observed state of existing technical calculations.

States are fixed descriptive bands over values the Agent already computed (plus one volatility ratio).
They describe what was observed in the stored period. They are not signals, forecasts or trade advice,
and the thresholds are initial product rules that have not been validated.
"""
import itertools
from statistics import pstdev

RULE_VERSION = 'technical-states-1'
NEAR_SMA = 0.01            # |종가/SMA - 1| < 1% 이면 이동평균 부근
RETURN_BANDS = (0.03, 0.10)  # 작은 변동 < 3% ≤ 뚜렷한 변동 < 10% ≤ 큰 폭 변동
VOL_RATIO_BANDS = (0.67, 1.5)  # 최근/전체 변동성 비율
VOLUME_BANDS = (-0.5, 0.5, 1.0)  # 감소 ≤ -50% / 증가 ≥ +50% / 급증 ≥ +100%

THRESHOLDS = {'nearSma': NEAR_SMA, 'returnBands': RETURN_BANDS, 'volatilityRatioBands': VOL_RATIO_BANDS,
              'volumeBands': VOLUME_BANDS}


def trend_state(close, sma):
    gap = close / sma - 1
    if abs(gap) < NEAR_SMA:
        return gap, '이동평균 부근'
    return gap, '이동평균 위' if gap > 0 else '이동평균 아래'


def return_state(value):
    size = abs(value)
    band = '작은 변동' if size < RETURN_BANDS[0] else '뚜렷한 변동' if size < RETURN_BANDS[1] else '큰 폭 변동'
    if value == 0:
        return '변동 없음'
    return band + ('(상승)' if value > 0 else '(하락)')


def volatility_state(ratio):
    if ratio < VOL_RATIO_BANDS[0]:
        return '최근 변동성 축소'
    return '최근 변동성 확대' if ratio > VOL_RATIO_BANDS[1] else '전체 기간과 비슷한 변동성'


def volume_state(change):
    if change <= VOLUME_BANDS[0]:
        return '거래량 감소'
    if change >= VOLUME_BANDS[2]:
        return '거래량 급증'
    return '거래량 증가' if change >= VOLUME_BANDS[1] else '평이한 거래량'


def describe_states(closes, window, calculations, evidence_id, horizon):
    """Return (extra calculations, state claims). Reads existing TECH_* results; adds only the ratio."""
    values = {c['calculationId']: c['result'] for c in calculations}
    extra, claims = [], []

    def claim(key, text, calc_ids, rule):
        claims.append({'claimId': 'TECH_STATE_' + key, 'claimVersion': 1, 'kind': 'interpretation',
                       'text': text + ' (관측 상태 설명이며 예측·매매 신호가 아닙니다.)',
                       'horizon': horizon, 'assessment': 'provisional',
                       'evidenceLinks': [{'evidenceId': evidence_id, 'relation': 'supports'}],
                       'calculationIds': calc_ids, 'stateRule': {'ruleVersion': RULE_VERSION, **rule}})

    if 'TECH_SMA' in values:
        gap, state = trend_state(closes[-1], values['TECH_SMA'])
        claim('TREND', f'마지막 종가가 {window}개 관측 이동평균 대비 {gap:+.2%}로 "{state}" 상태입니다.',
              ['TECH_SMA'], {'state': state, 'value': gap, 'threshold': NEAR_SMA})
    if 'TECH_RETURN' in values:
        state = return_state(values['TECH_RETURN'])
        claim('RETURN', f'직전 대비 수익률 {values["TECH_RETURN"]:+.2%}는 "{state}" 구간입니다.',
              ['TECH_RETURN'], {'state': state, 'value': values['TECH_RETURN'], 'threshold': RETURN_BANDS})
    returns = [b / a - 1 for a, b in itertools.pairwise(closes)]
    if len(returns) >= 2 * window and pstdev(returns) > 0:
        ratio = pstdev(returns[-window:]) / pstdev(returns)
        extra.append({'calculationId': 'TECH_VOLATILITY_RATIO', 'result': ratio, 'unit': 'ratio',
                      'formula': 'pstdev(last window returns) / pstdev(all available returns)',
                      'inputs': [len(returns[-window:]), len(returns)], 'methodVersion': RULE_VERSION,
                      'inputEvidenceIds': [evidence_id], 'window': window})
        state = volatility_state(ratio)
        claim('VOLATILITY', f'최근 {window}개 수익률 변동성이 전체 기간의 {ratio:.2f}배로 "{state}"입니다.',
              ['TECH_VOLATILITY_RATIO'], {'state': state, 'value': ratio, 'threshold': VOL_RATIO_BANDS})
    if 'TECH_VOLUME_CHANGE' in values:
        state = volume_state(values['TECH_VOLUME_CHANGE'])
        claim('VOLUME', f'마지막 거래량이 직전 {window}개 평균 대비 {values["TECH_VOLUME_CHANGE"]:+.2%}로 '
              f'"{state}"입니다.', ['TECH_VOLUME_CHANGE'],
              {'state': state, 'value': values['TECH_VOLUME_CHANGE'], 'threshold': VOLUME_BANDS})
    return extra, claims
