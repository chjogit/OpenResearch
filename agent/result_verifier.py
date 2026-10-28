"""Deterministic output checks, not a semantic or investment approval."""
from agent.basic_agents import AgentSettings, IndustryBusinessAgent, TechnicalAnalysisAgent
from agent.quality_gate import run_checked
from agent.research_contract import content_digest, validate_report


def verify_result(report, result, settings):
    checks = []

    def add(rule, ok, reason):
        checks.append({'검사': rule, '상태': '통과' if ok else '실패', '설명': reason})

    try:
        validate_report(report)
    except (ValueError, KeyError, TypeError):
        return {'status': 'failed', 'checks': [
            {'검사': '입력 구조·해시', '상태': '실패', '설명': '입력이 변경되었거나 형식이 잘못됨'}]}
    add('입력 버전', (result.get('inputDigest'), result.get('reportId'), result.get('contentRevision')) ==
        (report['digest'], report['reportId'], report['contentRevision']), '동일 입력 스냅샷인지 비교')
    classes = {'industry_business_model': IndustryBusinessAgent, 'technical_analysis': TechnicalAnalysisAgent}
    cls = classes.get(result.get('agentType'))
    gate = result.get('qualityGate')
    if cls is None or not gate:
        add('실행 정보', False, 'Agent 종류 또는 품질검사 결과 없음')
    else:
        try:
            expected = run_checked(cls(settings=settings), report, gate)
            for field in ['status', 'claims', 'evidence', 'calculations', 'subject', 'asOf', 'dataMode']:
                add(field, result.get(field) == expected.get(field), '동일 코드로 재실행한 기본 결과와 비교')
            # Persona invariance: neutral presentation must give the same values and decisions.
            neutral = run_checked(cls(settings=AgentSettings(window=settings.window)), report, gate)
            add('페르소나 불변', all(result.get(f) == neutral.get(f) for f in
                                ['status', 'claims', 'evidence', 'calculations', 'qualityGate']),
                '표현 설정(L1~L4·A/C/U)과 관계없이 수치·근거·판정이 같아야 함')
            if 'withheld' in {gate['status'], expected.get('status'), result.get('status')}:
                add('보류 시 호출 차단', result.get('explanation') is None and not result.get('modelResults'),
                    '보류 결과에 LLM 설명·모델 결과가 없어야 함')
        except (ValueError, KeyError, TypeError):
            add('재현 검사', False, '검사 설정·근거·품질 결과의 일관성 오류')
    # Gate is internal application state, not proof of authorization or verified truth.
    checks.append({'검사': '원문 사실성·주장 지지', '상태': '검수 필요',
                   '설명': 'DB 원문 진위, 발췌 관련성, 반대 근거는 사람이 확인해야 함'})
    if result.get('explanationStatus') == 'failed':
        checks.append({'검사': 'LLM 설명', '상태': '검수 필요', '설명': 'LLM 호출 실패; Python 결과만 사용'})
    elif result.get('explanation'):
        checks.append({'검사': 'LLM 설명', '상태': '검수 필요',
                       '설명': '수치·보류·근거를 왜곡하지 않았는지 의미 검수 필요; 자동 사실 검증 아님'})
    if result.get('modelResults'):
        checks.append({'검사': 'ML/DL', '상태': '검수 필요', '설명': '모델 타당성·학습 시점은 별도 검증'})
    status = 'failed' if any(c['상태'] == '실패' for c in checks) else (
        'withheld' if result.get('status') == 'withheld' else 'review_required')
    return {'status': status, 'inputDigest': report['digest'], 'resultDigest': content_digest({'result': result}),
            'methodVersion': 'deterministic-replay-1', 'checks': checks,
            'limitation': '동일 코드 재현 검사이며 독립 계산 공식 감사·외부 원문 검증·승인은 아님'}
