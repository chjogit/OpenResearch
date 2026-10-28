"""Evaluation table: does changing the persona keep numbers, evidence and quality decisions identical?

Each of the 12 presentation settings (L1-L4 x A/C/U) is run on the same report and quality gate without
LLM or model tools, and compared with the neutral L2-U run. Only `presentation` may differ.
"""
from agent.basic_agents import AgentSettings
from agent.quality_gate import run_checked

CHECKS = [
    ('수치 보존', ['calculations']),
    ('근거 보존', ['evidence']),
    ('주장 보존', ['claims']),
    ('품질 판정 보존', ['qualityGate']),
    ('보류·상태 보존', ['status', 'limitations', 'followUpRequests']),
    ('입력 보존', ['inputDigest', 'reportId', 'contentRevision', 'asOf', 'dataMode', 'subject']),
]
PERSONAS = [(level, style) for level in ['L1', 'L2', 'L3', 'L4'] for style in ['A', 'C', 'U']]


def evaluate_persona_invariance(report, gate, agent_cls, window):
    neutral = run_checked(agent_cls(settings=AgentSettings(window=window)), report, gate)
    rows = []
    for level, style in PERSONAS:
        settings = AgentSettings(window=window, literacy=level, style=style, persona_status='user_confirmed')
        result = run_checked(agent_cls(settings=settings), report, gate)
        row = {'페르소나': f'{level}-{style}'}
        for name, fields in CHECKS:
            row[name] = '통과' if all(result.get(f) == neutral.get(f) for f in fields) else '실패'
        row['표현 차이'] = ' → '.join(s['key'] for s in result['presentation']['sections'])
        row['결과'] = '통과' if all(row[name] == '통과' for name, _ in CHECKS) else '실패'
        rows.append(row)
    return {'status': 'passed' if all(r['결과'] == '통과' for r in rows) else 'failed', 'rows': rows,
            'inputDigest': report['digest'], 'agentType': neutral['agentType'],
            'note': '같은 코드로 표현 설정만 바꾼 재실행 비교입니다. 설명 품질·LLM 문장은 평가하지 않습니다.'}
