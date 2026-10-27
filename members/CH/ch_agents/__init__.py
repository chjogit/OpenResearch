"""CH 담당 관점 에이전트 (기초기획서 R4, 교재 8~9장 번호): 에이전트 1 거시경제, 에이전트 3 투자심리·수급.

구조
- db.py                     읽기 전용 조회 (관점마다 SQL 한 번으로 JSON 묶음을 받음)
- facts.py                  숫자 장부(Facts)와 계산 도구. LLM은 장부의 키만 인용
- agent1_macro.py           에이전트 1 데이터 계산 (+ exposure.py 노출 점검표·미확인 전제)
- agent3_sentiment_flow.py  에이전트 3 데이터 계산 (기준선 비교·중복 신호)
- contract.py               데이터 계약 (reportId·claimId·evidenceId, schema/agent_output.schema.json)
- verify.py                 팀 공용 fact_source_verifier 연동 (수치 대조·출처 태그·claimId/evidenceId)
- financial.py              (이관 참고) 재무 계산. 7번에 임시 등록
- llm.py       프롬프트, 출력 검사, 1회 수정 요청, 규칙 기반 대체 요약, 렌더링
- review.py    보고서 첨삭 모드
- evaluate.py  여러 종목 일괄 점검 성적표
"""
from .agents import AGENTS, AgentData, fetch_agent_data
from .llm import run_agent, run_my_agents
from .review import review_report

__all__ = ["AGENTS", "AgentData", "fetch_agent_data", "review_report", "run_agent", "run_my_agents"]
