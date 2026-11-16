# v0.3-agent1 — 1단계: 규칙 기반 자기 수정 실행기
- 추가: mrn/agent.py(규칙표 R01~R20, R99), /api/agent/rules, /api/agent/runs, 「에이전트 실행」 버튼·대화상자
- DB: agent_runs 표만 추가(기존 표 변경 없음)
- 시험: 48개 통과(에이전트 9개 추가), 2차_실제 기준선 898 일치
- 되돌리기: ..\v0.2-stable\restore.cmd (DB 호환: v0.2 앱은 agent_runs 표를 무시함)
