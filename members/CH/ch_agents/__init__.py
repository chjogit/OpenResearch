"""CH 담당 관점 에이전트: A1 거시·민감도, A2 재무·밸류에이션·건전성, A4 투자심리·수급.

구조
- db.py        읽기 전용 조회 (관점마다 SQL 한 번으로 JSON 묶음을 받음)
- facts.py     숫자 장부(Facts)와 계산 도구. LLM은 장부의 키만 인용
- macro.py     A1 데이터 계산
- financial.py A2 데이터 계산
- sentiment.py A4 데이터 계산
- llm.py       프롬프트, 출력 검사, 1회 수정 요청, 규칙 기반 대체 요약, 렌더링
- review.py    보고서 첨삭 모드
- evaluate.py  여러 종목 일괄 점검 성적표
"""
from .agents import AGENTS, AgentData, fetch_agent_data
from .llm import run_agent, run_my_agents
from .review import review_report

__all__ = ["AGENTS", "AgentData", "fetch_agent_data", "review_report", "run_agent", "run_my_agents"]
