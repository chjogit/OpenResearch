"""Decide whether a learned model should replace a rule baseline. No model is trained here.

A model is only considered when (1) the baseline shows a concrete weakness, (2) both are scored on the
same human-labelled gold set held out by document, and (3) the model beats the baseline by a margin
without getting worse on any label that has enough support.
"""

MIN_GAIN = 0.05
MIN_TEST_SAMPLES = 50
MIN_LABEL_SUPPORT = 5
MAX_LABEL_DROP = 0.05


def weaknesses(baseline, min_f1=0.6):
    """Labels where the rule baseline is weak enough to justify trying a model."""
    return [{'label': k, 'f1': v['f1'], 'support': v['support']}
            for k, v in baseline['perLabel'].items()
            if v['support'] >= MIN_LABEL_SUPPORT and v['f1'] < min_f1]


def compare(baseline, model, *, model_info, min_gain=MIN_GAIN):
    """baseline/model: outputs of paragraph_labels.evaluate on the same held-out gold set.

    model_info must carry modelVersion, trainingCutoff and trainingGoldDigest (the training split).
    """
    reasons, adopt = [], True
    for key in ['modelVersion', 'trainingCutoff', 'trainingGoldDigest']:
        if not model_info.get(key):
            reasons.append(f'모델 정보 {key} 없음')
            adopt = False
    if baseline['goldDigest'] != model['goldDigest']:
        reasons.append('기준선과 모델의 평가 정답셋이 다름')
        adopt = False
    if model_info.get('trainingGoldDigest') == model['goldDigest']:
        reasons.append('학습 정답셋과 평가 정답셋이 같음(누수)')
        adopt = False
    if model['n'] < MIN_TEST_SAMPLES:
        reasons.append(f'평가 문단 {model["n"]}개 < {MIN_TEST_SAMPLES}개')
        adopt = False
    if not weaknesses(baseline):
        reasons.append('규칙 기준선에서 개선할 약점(지원 충분·F1<0.6)이 확인되지 않음')
        adopt = False
    gain = (model['macroF1'] or 0) - (baseline['macroF1'] or 0)
    if gain < min_gain:
        reasons.append(f'macro F1 개선 {gain:+.3f} < 기준 {min_gain:.3f}')
        adopt = False
    drops = [k for k, v in baseline['perLabel'].items() if v['support'] >= MIN_LABEL_SUPPORT
             and model['perLabel'].get(k, {'f1': 0})['f1'] < v['f1'] - MAX_LABEL_DROP]
    if drops:
        reasons.append('나빠진 분류: ' + ', '.join(drops))
        adopt = False
    return {'adopt': adopt, 'macroF1Gain': gain, 'baselineMacroF1': baseline['macroF1'],
            'modelMacroF1': model['macroF1'], 'reasons': reasons or ['모든 채택 조건 충족(사람 최종 검토 필요)'],
            'goldDigest': model['goldDigest']}
