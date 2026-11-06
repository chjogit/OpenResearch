"""질문 → 답 파이프라인 설명(#61). 시연 화면의 그림(번호 단계)과 같은 번호의 설명 목록이 이 모듈 하나에서 나온다.

- 단계 번호·이름·하는 일은 코드가 실제로 도는 순서(qa.agent.answer)를 그대로 옮긴 것이고,
- 쓰인 기술(모델 이름·검색 방식·설정값·켜짐/꺼짐)은 설정·상수·실행 기록에서 읽어 채운다(손으로 쓴 값 없음).
- describe(None) = 설정만(서버 없이 처음 여는 화면), describe(out) = 설정 + 이번 실행의 결과 요약(stat).
"""
from __future__ import annotations

from typing import Any

# 추적 이벤트(trace[].kind, 도구는 kind:tool) → 그림 단계 번호. 에이전트가 내는 이벤트 종류는 모두 여기 있어야 한다(시험).
EVENT_STAGE: dict[str, list[int]] = {
    "해석": [2], "선택": [3], "시간 초과": [3],
    "도구:run_node_agent": [4], "도구:price_summary": [4], "도구:doc_search": [5],
    "답·검사": [6, 7], "종료": [8, 9],
}


def _on(value: Any, label: str = "") -> dict:
    return {"label": label, "value": str(value), "state": "on"}


def _flag(label: str, enabled: bool, detail: str = "", env: str = "") -> dict:
    return {"label": label, "value": ("켜짐" if enabled else "꺼짐") + (f" — {detail}" if detail else ""), "state": "on" if enabled else "off", "env": env}


def _stat(out: dict | None, no: int) -> str | None:
    """이번 실행에서 이 단계가 낸 결과 요약. 실행 기록(out)이 없으면 None."""
    if not out:
        return None
    trace = out.get("trace") or []
    tools = [e for e in trace if e.get("kind") == "도구"]
    if no == 1:
        return f"질문 {len(out.get('question') or '')}자"
    if no == 2:
        c = (out.get("interpretation") or {}).get("company") or {}
        it = out.get("interpretation") or {}
        return f"종목 {c.get('name') or c.get('mention') or '-'} · 의도 {it.get('intent') or '-'}"
    if no == 3:
        origins = sorted({str(e.get("origin") or "") for e in tools if e.get("origin")})
        return f"도구 {len(tools)}회" + (f" ({' · '.join(origins)})" if origins else "")
    if no == 4:
        n = [e for e in tools if e.get("tool") in ("run_node_agent", "price_summary")]
        agents = sorted({(e.get("args") or {}).get("agent_no") for e in n if e.get("tool") == "run_node_agent"} - {None})
        return (f"에이전트 {', '.join(str(a) for a in agents)}" if agents else "") + (" · " if agents and any(e.get("tool") == "price_summary" for e in n) else "") + ("시세 요약" if any(e.get("tool") == "price_summary" for e in n) else "") or "실행 없음"
    if no == 5:
        d = [e for e in tools if e.get("tool") == "doc_search"]
        if not d:
            return "검색 안 함"
        r = (d[0].get("result") or {}).get("rag") or {}
        h = r.get("hybrid") or {}
        return f"문서 {len(r.get('found') or [])}건 · {h.get('modeLabel') or '키워드 검색'}" + (f" · 대체: {h['fallback']}" if h.get("fallback") else "")
    chk = next((e for e in reversed(trace) if e.get("kind") == "답·검사"), None)
    if no == 6:
        return f"문장 {(chk.get('kept', 0) + len(chk.get('removed') or [])) if chk else 0}개 생성"
    if no == 7:
        return f"통과 {chk.get('kept', 0)}문장 · 제거 {len(chk.get('removed') or [])}문장" if chk else "검사 안 함"
    if no == 8:
        return f"전망 카드 {len((out.get('outlook') or {}).get('cards') or [])}장" if out.get("outlook") is not None else None
    if no == 9:
        u = out.get("usage") or {}
        return f"{out.get('status') or '-'} · LLM {u.get('llm_calls', 0)}회 · {u.get('total_seconds', 0)}초"
    return None


def describe(out: dict | None = None) -> dict:
    """{'steps': [...], 'events': EVENT_STAGE}. 각 단계: no, name, what, tech[{label,value,state}], subs[{name,state}], stat."""
    from ch_agents import llm as llm_mod
    from ch_agents import outlook as outlook_mod
    from ch_agents import rag_hybrid, rerank

    from . import agent

    hybrid, rr = rag_hybrid.enabled(), rerank.enabled()
    steps = [
        {"no": 1, "name": "질문 입력", "what": "사용자가 자연어로 질문을 적습니다(한 번에 한 질문).",
         "tech": [_on("자연어 한 문장, 최대 400자", "입력")], "subs": []},
        {"no": 2, "name": "질문 해석", "what": "질문에서 종목·기간·영역·의도를 뽑고, 코드가 종목 사전·별칭·투자 판단 표현으로 바로잡습니다.",
         "tech": [_on(llm_mod.MODEL, "LLM"), _on("JSON 모드 한 번 호출 + 코드 보정(종목 사전·투자 판단 표현 정규식·가정은 질문 속 글자만)", "방식")], "subs": []},
        {"no": 3, "name": "도구 선택 루프", "what": "LLM 이 필요한 도구와 인자·이유를 고르고, 형식이 틀리면 기본 계획으로 대체합니다.",
         "tech": [_on(llm_mod.MODEL, "LLM"), _on("LLM 이 JSON 행동을 고르는 자체 루프(함수호출 API 미사용)", "방식"),
                  _on(f"{agent.MAX_TOOL_CALLS}회", "도구 호출 상한"), _on(f"{agent.TIME_BUDGET_S:.0f}초", "시간 목표")], "subs": []},
        {"no": 4, "name": "노드·시세 조회", "what": "에이전트 3·4·6 의 노드(점검·해석)를 규칙·통계로 계산하고 읽기 전용 DB 에서 시세를 가져옵니다.",
         "tech": [_on("규칙·통계 계산, LLM 없음", "방식"), _on("읽기 전용", "DB")], "subs": []},
        {"no": 5, "name": "문서 검색", "what": "질문·종목·영역으로 만든 질의를 임베딩해 벡터 검색으로 기준일 이하 근거 청크를 독립적으로 찾고 키워드 후보와 합칩니다. 개인 작성 글(블로그·카페·유튜브)은 번호·점수만 보이고 원문은 보이지 않습니다.",
         "tech": [_flag("벡터 검색", hybrid, f"{rag_hybrid.QUERY_MODEL}, {rag_hybrid.EMBED_DIM}차원, 후보 상위 {rag_hybrid.N_CANDIDATES}" if hybrid
                        else f"키워드·규칙 점수만 사용 (임베딩 모델 {rag_hybrid.QUERY_MODEL} {rag_hybrid.EMBED_DIM}차원은 켤 때 사용)", "CH_RAG_HYBRID"),
                  _flag("리랭커", rr, rerank.model_name() if rr else "", "CH_RAG_RERANK"), _on(f"{rag_hybrid.PER_DOC}개", "문서당 청크"),
                  _on(f"벡터 유사도 상위 {int(rag_hybrid.VECTOR_SHARE * 100)}% 자리를 먼저 보장, 나머지는 키워드 {rag_hybrid.W_KEYWORD}·벡터 {rag_hybrid.W_VECTOR} 합산 점수 순", "합치는 규칙")],
         "subs": [{"name": "키워드·규칙 점수", "state": "on"}, {"name": "벡터 검색(정확 거리 정렬)", "state": "on" if hybrid else "off"},
                  {"name": "리랭커", "state": "on" if rr else "off"}]},
        {"no": 6, "name": "답 생성", "what": "근거(장부 값·문서)만 써서 답 문장을 씁니다. 숫자는 장부 키로만 쓰고 값은 코드가 채웁니다.",
         "tech": [_on(llm_mod.MODEL, "LLM"), _on("숫자는 장부 키로만", "규칙")], "subs": []},
        {"no": 7, "name": "검사", "what": "문장마다 숫자·키·금지 표현·결론/권유/가격 전망·개인 글 주소·근거 유무를 검사해 걸리면 제거하거나 다시 씁니다.",
         "tech": [_on(agent.VERIFIER_TEXT, "검사 항목"), _on("코드 검사(LLM 아님)", "방식")], "subs": []},
        {"no": 8, "name": "20거래일 전망", "what": "에이전트별 전망 방향과 과거 검증 판정을 규칙으로 계산합니다(LLM 이 만들지 않음).",
         "tech": [_on(outlook_mod.RULE_VERSION, "규칙 버전"), _on("규칙 계산, LLM 없음", "방식"), _on("기준선과 비교한 판정(우위/구별 안 됨/미검증)", "적중률")], "subs": []},
        {"no": 9, "name": "자연어 답 출력", "what": "사실·계산·예측·해석 표시와 근거 링크, 미확보 목록을 붙여 보여 줍니다. 종합 결론은 오케스트레이터(SW) 담당입니다.",
         "tech": [_on("사실·계산·예측·해석 태그 + 근거 키 링크 + 미확보·한계", "표시")], "subs": []},
    ]
    for s in steps:
        s["stat"] = _stat(out, s["no"])
    return {"steps": steps, "events": EVENT_STAGE}
