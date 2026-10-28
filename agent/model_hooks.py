"""【ML/DL 연결 위치】 Contracts and untrained baselines for the two Agents' `model_tool`.

Pass an object with `predict(payload) -> dict` as `model_tool=` when creating an Agent. The Agent calls it
after its Python results are final (never for withheld results) and stores the return in `modelResults`.
Model output is advisory: it never changes claims, evidence, calculations or the quality decision.

Return contract (all tasks): modelVersion, trainingCutoff, status (ok / not_run / failed), output,
limitations, and `task` naming one of TASKS so the output shape can be checked.

| Agent | task | ML baseline here | ML candidate | DL candidate |
|---|---|---|---|---|
| 산업·사업모델 | paragraph_classification | 키워드 규칙 | TF-IDF + 로지스틱 회귀 | 한국어 사전학습 분류기 |
| 기술적 분석 | volatility_forecast | 직전 변동성 유지 | 회귀(과거 변동성 특징) | 작은 LSTM/GRU |
"""
import itertools
import json
import math
from statistics import pstdev

from agent.paragraph_labels import LABELS, RULE_VERSION, rule_classify

TASKS = {'industry_business_model': 'paragraph_classification', 'technical_analysis': 'volatility_forecast'}
STATUSES = {'ok', 'not_run', 'failed'}


def validate_model_output(domain, model, result):
    """Shape check for known tasks. Models without `task` only need the common contract."""
    if model['status'] not in STATUSES:
        raise ValueError('Invalid model status')
    task = model.get('task')
    if task is None:
        return
    if task != TASKS.get(domain):
        raise ValueError('Model task does not match this Agent')
    if model['status'] != 'ok':
        return
    output = model['output']
    if task == 'paragraph_classification':
        ids = {e['evidenceId'] for e in result['evidence']}
        if not isinstance(output, list):
            raise ValueError('paragraph_classification output must be a list')
        for row in output:
            if row.get('evidenceId') not in ids or row.get('label') not in LABELS:
                raise ValueError('Unknown evidence or label')
            confidence = row.get('confidence')
            if confidence is not None and not (isinstance(confidence, (int, float)) and 0 <= confidence <= 1):
                raise ValueError('confidence must be within 0..1')
    else:
        value = (output or {}).get('predictedVolatility')
        horizon = (output or {}).get('horizon')
        if not (isinstance(value, (int, float)) and math.isfinite(value) and value >= 0):
            raise ValueError('predictedVolatility must be a finite non-negative number')
        if type(horizon) is not int or horizon < 1:
            raise ValueError('horizon must be a positive integer (observations)')


class KeywordParagraphBaseline:
    """산업 Agent 【ML 연결 위치】 기준선. 학습 모델이 아니라 키워드 규칙을 같은 계약으로 감쌉니다.

    학습 모델은 이 클래스와 같은 predict 계약으로 만들고, paragraph_labels.evaluate·model_comparison.compare로
    이 기준선보다 나은지 확인한 뒤 연결합니다.
    """
    task = 'paragraph_classification'

    def predict(self, payload):
        output = []
        for e in payload['evidence']:
            section = (e.get('location') or {}).get('section') or {}
            label, _ = rule_classify(e.get('excerpt'), section.get('subsection'))
            output.append({'evidenceId': e['evidenceId'], 'label': label, 'confidence': None})
        return {'task': self.task, 'modelVersion': RULE_VERSION, 'trainingCutoff': None, 'status': 'ok',
                'output': output,
                'limitations': ['학습 모델이 아닌 키워드 규칙 기준선입니다. 신뢰도(confidence)는 제공하지 않습니다.']}


class PersistenceVolatilityBaseline:
    """기술 Agent 【ML 연결 위치】 기준선: 다음 구간 변동성 = 최근 window 수익률 변동성(그대로 유지).

    가장 단순한 비교 기준입니다. 회귀·LSTM 등은 시간순으로 나눈 평가에서 이 기준선보다 오차(MAE)가
    작을 때만 의미가 있습니다. 예측값은 관측 사실이 아니며 매매 신호가 아닙니다.
    """
    task = 'volatility_forecast'

    def __init__(self, window=20):
        if type(window) is not int or window < 2:
            raise ValueError('window must be an integer >= 2')
        self.window = window

    def predict(self, payload):
        evidence = next((e for e in payload['evidence'] if e['evidenceId'] == 'E03'), None)
        closes = [row['close'] for row in json.loads(evidence['excerpt'])] if evidence else []
        returns = [b / a - 1 for a, b in itertools.pairwise(closes)]
        if len(returns) < self.window:
            return {'task': self.task, 'modelVersion': 'persistence-baseline-1', 'trainingCutoff': None,
                    'status': 'not_run', 'output': None,
                    'limitations': [f'수익률 {len(returns)}개 < window {self.window}: 기준선 계산 보류']}
        return {'task': self.task, 'modelVersion': 'persistence-baseline-1', 'trainingCutoff': None,
                'status': 'ok',
                'output': {'horizon': self.window, 'predictedVolatility': pstdev(returns[-self.window:]),
                           'basis': f'최근 {self.window}개 수익률 모집단 표준편차를 다음 {self.window}개 관측에 그대로 적용'},
                'limitations': ['학습 없는 기준선입니다. 예측 정확도는 평가하지 않았습니다.',
                                '변동성 예측은 가격 방향·매매 판단이 아닙니다.']}


class NotTrainedHook:
    """학습된 모델을 아직 연결하지 않았음을 명시하는 자리 표시. 예측을 만들지 않습니다."""

    def __init__(self, task):
        if task not in TASKS.values():
            raise ValueError('Unknown task')
        self.task = task

    def predict(self, payload):
        return {'task': self.task, 'modelVersion': 'not-trained', 'trainingCutoff': None, 'status': 'not_run',
                'output': None, 'limitations': ['학습·평가 후 연결할 자리입니다. 실제 예측 없음.']}
