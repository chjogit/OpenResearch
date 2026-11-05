"""노드 기반 에이전트 3(거시)·4(수급)·6(투자심리·뉴스)의 실행 경로 (#25).

노드(N05~N08·N11·N12)가 낸 NodeResult 를 기존 서술·검증 경로(`llm.run_agent`)가 읽는 `AgentData` 로 바꿉니다.
- 노드 장부(ledger)를 하나의 `Facts` 로 합침: 키(L1·S1·T1·X1…)는 노드마다 접두어가 달라 겹치지 않음. 숫자는 노드가 계산한 값 그대로.
- 노드 진술(Finding)은 '코드 판정'으로 넘김: 문장 속 숫자 표기를 장부 키 `{K}` 로 바꿔 LLM 이 숫자를 옮겨 쓰지 않게 함.
- 충돌 구역(Conflict)은 평균 내지 않고 관점별로 나란히 판정 문장에 둠. 한계(limits)와 노드 실행·스킵 현황은 해석 가이드로.
- 옛 번호 대응(변환표): 옛 1(p01) → 3, 옛 3(p03) → 4·6. 번호 3 이 겹치므로 이름이 아니라 `AgentData.extra["node_agent"]` 로 구분.
"""
from __future__ import annotations

import re
from typing import Any

from .agents import AgentData, AgentSpec
from .availability import OUT_OF_SCOPE_ITEM, OUT_OF_SCOPE_TEXT
from .facts import Facts
from .sentiment_limit import SENT_LIMIT_TEXT

PLACEHOLDER = re.compile(r"\{([A-Z]\d+)\}")
LOOSE_NUMBER = re.compile(r"[+-]?\d+\.\d+%?|[+-]?\d{1,3}(?:,\d{3})+|[+-]?\d+%")   # 소수·천 단위·퍼센트 (일수·노드 번호 같은 정수는 제외)
DIRECTION_RULE = ("방향어 규칙: 장부 키 바로 뒤에 그 값의 방향어(순매수/순매도·증가/감소)를 쓰고, 한 문장에 부호가 다른 키를 나열하지 말 것. "
                  "음수인 '순매수 수량'은 '순매도'로 쓰고, 키 뒤 12자 안에 반대 방향어가 오지 않게 문장을 나눌 것")
GROUP = {"N05": "거시 노출", "N06": "시나리오", "N07": "유동성", "N08": "수급 전환", "N11": "사건 감성", "N12": "후속 반응"}
KIND_TEXT = {"base": "기본", "ext": "확장"}
# 프롬프트에 올리는 장부 크기 상한 (#31): 사건이 수백 개인 종목(셀트리온 462개)에서 장부가 930항목·10만 자가 되어 응답이 폭주했음.
# 진술문(판정 문장)이 가리키는 사건 항목만 남기고, 나머지 사건 항목은 노드 산출물(artifacts.events)에만 둠.
TRIM_LABEL = re.compile(r"^사건 E\d+")   # N11 사건별 항목(평균 감성·불확실성 표현 비율)

NODE_SPECS: dict[int, AgentSpec] = {}


def _specs() -> dict[int, AgentSpec]:
    if NODE_SPECS:
        return NODE_SPECS
    from . import flow_nodes, macro_nodes, sentiment_nodes

    NODE_SPECS.update({
        3: AgentSpec(
            3, "에이전트 3 거시경제·정책 (Macro & Policy)", macro_nodes,
            role=("금리·환율·유가·물가 등 거시 지표를 발표 시점 규칙(Point-in-Time) 안에서 읽고, 이 기업이 어떤 거시 변수에 노출되는지를 "
                  "회사 공시(사실)와 외부 추정을 나눠 보여 줍니다. 확장 노드는 사용자가 준 시나리오를 회사 공시 민감도로 환산한 값만 냅니다. "
                  "거시 변수가 실적 예측을 개선한다고 쓰지 않습니다."),
            checklist=[
                "노출 경로별 등급과 근거가 공시 사실인지 외부 추정인지 구분해 전달 (근거 없는 등급은 결론으로 쓰지 않음)",
                "발표·수정 이력 미보관 등 Point-in-Time 한계와 공표 전이라 뺀 관측",
                "시나리오가 있으면 공시 민감도 환산값과 같은 크기의 반대 조건을 나란히, 환산 보류 사유 그대로",
                "미확인 전제(헤지·결제 시점·판가 전가력)는 가정하지 않고 상태 그대로",
                "달러 화폐성 순자산이 음수(순부채)면 '환율 상승 → 환산 손실, 하락 → 환산 이익'으로 쓰고, 순자산 부호와 환율 방향을 한 문장에 섞지 말고 따로 쓸 것",
                "상충하는 신호는 평균 내지 않고 관점별로 나란히",
                "반대 근거·하방 위험 1~3개. 주장은 7개 이하",
            ],
            next_checks=["다음 한국은행 금리 결정과 원/달러 방향", "다음 달 관세청 수출 통계", "미국 물가 발표"]),
        4: AgentSpec(
            4, "에이전트 4 수급 (Flow & Liquidity)", flow_nodes,
            role=("거래대금·회전율·비유동성 등 유동성 지표와, 외국인·기관·개인의 누적 순매수와 주체 간 전환·가격 불일치를 보여 줍니다. "
                  "투자자별 자료가 없으면 거래량으로 대신 해석하지 않고 무자료로 둡니다. 순매수 기록만으로 매수 의도나 정보 보유를 "
                  "추정하지 않으며, 전환 확률은 표본·걷기 검증을 통과할 때만 말합니다."),
            checklist=[
                "유동성: 거래대금 5·20·60일, 회전율, 급증·급감과 시장 대비 위치",
                "수급: 주체별 5·20·60일 누적과 연속 일수, 주체 간 전환(handover)",
                "가격과 수급이 엇갈리는 구간은 평균 내지 않고 충돌로 나란히",
                "수급이 시세보다 늦으면 판정을 무자료로 두고 그 사실을 알림",
                "전환 확률이 생략됐다면 그 이유(표본·검증 미통과)를 그대로 전달",
                "반대 근거·하방 위험 1~3개. 주장은 7개 이하",
            ],
            next_checks=["외국인 순매수 방향 전환 여부(5일 기준)", "거래대금 급증 지속 여부", "대차잔고 추이"]),
        6: AgentSpec(
            6, "에이전트 6 투자심리·뉴스 (Sentiment & News)", sentiment_nodes,
            role=("유사·중복 기사를 한 사건으로 묶어, 사건별 기대·우려와 불확실성 표현을 근거 원문 문장과 함께 보여 줍니다. 감성 점수는 "
                  f"{SENT_LIMIT_TEXT}입니다. 확장 노드는 사건 뒤 t+1·t+3·t+5 초과수익과 추가 예측력 검증을 보이고, "
                  "검증 요건을 통과하지 못하면 감성 기반 추론을 하지 않고 이유를 말합니다."),
            checklist=[
                "사건별 감성·불확실성과 근거 문장 (근거 없는 점수는 쓰지 않음)",
                "대상 기업이 아닌 문서를 분리한 건수, 분류가 엇갈린 사건은 평균 내지 않고 나란히",
                "게시 시각이 날짜 단위라 장중·장후를 구분하지 못한다는 한계와, 블로그·카페의 부수 언급 가능성",
                "감성 점수는 사전 기준선이라는 한계. 긍정 문서가 많다는 것과 수익률은 별개",
                "후속 반응 표(CAR)는 과거 관계이며 예측이 아님, 추론이 생략됐다면 그 이유",
                "기사에 증권사 목표주가 언급이 있어도 '목표주가'라는 단어는 쓰지 말고 '증권사 전망 관련 언급'으로 쓸 것(사건 설명에도 동일, 구체 수치는 쓰지 않음)",
                "반대 근거·하방 위험 1~3개. 주장은 7개 이하",
            ],
            next_checks=["다음 실적 발표 전후 논조 변화", "검색 관심도 급변", "사람 라벨 평가 완료 여부"]),
    })
    return NODE_SPECS


def spec_for(agent_no: int) -> AgentSpec:
    return _specs()[agent_no]


# ---------------------------------------------------------------- 실행

def run_nodes(agent_no: int, ticker: str, as_of: str, extension: bool = False, scenario: str | None = None,
              focus: list[str] | None = None, co: dict | None = None, inputs: dict | None = None,
              validated: bool = False) -> dict:
    """에이전트 번호(3·4·6)에 맞는 노드 실행 함수를 부름. inputs 를 주면 DB 를 읽지 않음(재현·테스트)."""
    from . import flow_nodes, macro_nodes, sentiment_nodes

    if agent_no == 3:
        return macro_nodes.run_macro_agent(ticker, as_of, extension=extension, scenario=scenario, focus=focus,
                                           inputs=inputs, co=co)
    if agent_no == 4:
        return flow_nodes.run_flow_agent(ticker, as_of, extension=extension, inputs=inputs)
    if agent_no == 6:
        return sentiment_nodes.run_sentiment_agent(ticker, as_of, extension=extension, inputs=inputs, validated=validated)
    raise KeyError(f"노드 에이전트 번호는 3·4·6 입니다: {agent_no}")


def _to_placeholders(text: str, links: list[str], items: dict[str, dict]) -> str:
    """진술 속 숫자 표기를 연결된 장부 키 `{K}` 로 바꿈(키마다 첫 번째 일치만, 표기가 긴 것부터)."""
    out = text
    for k in sorted((k for k in links if k in items), key=lambda k: -len(items[k]["text"])):
        shown = items[k]["text"]
        if shown and shown in out:
            out = out.replace(shown, "{" + k + "}", 1)
    return out


def _mask_loose_numbers(text: str) -> str:
    """진술 속 장부 키 밖 숫자(예: Brier 0.265)를 가림. 남겨 두면 LLM 이 그대로 옮겨 써서 '키 밖 숫자' 로 문장이 지워짐."""
    parts = re.split(r"(\{[A-Z]\d+(?:,\s*[A-Z]\d+)*\}|" + re.escape(SENT_LIMIT_TEXT) + ")", text)   # 고정 한계 문구는 그대로 둠(#47)
    return "".join(p if p.startswith("{") or p == SENT_LIMIT_TEXT else LOOSE_NUMBER.sub("(수치는 노드 산출물 참조)", p) for p in parts)


def merge_facts(report: dict) -> tuple[Facts, list[str]]:
    """노드 결과들을 하나의 Facts 로 합침. 반환: (장부, 충돌 구역 문장 목록)."""
    f = Facts("N")
    conflicts: list[str] = []
    for nid, res in report["results"].items():
        led = (res.artifacts or {}).get("ledger") or {}
        for k, v in led.items():
            f.items[k] = {"label": v["label"], "value": v["value"], "unit": v["unit"], "text": v["text"],
                          "as_of": v.get("as_of"), "source": v.get("source") or "", "kind": v.get("kind") or "계산",
                          "note": v.get("note") or "", "group": v.get("group") or GROUP.get(nid, nid)}
        f.gaps += [g for g in (res.artifacts or {}).get("gaps") or [] if g not in f.gaps]
    for nid, res in report["results"].items():
        for fd in res.findings:
            text = _mask_loose_numbers(_to_placeholders(fd.text, fd.evidence_links, f.items))
            if fd.kind == "note" or not fd.evidence_links:
                f.notes.append(text)
            else:
                f.flags.append(text)
        for c in res.conflicts:
            views = " ↔ ".join(f"({v.tag}) " + _mask_loose_numbers(_to_placeholders(v.text, v.evidence_links, f.items)) for v in c.views)
            conflicts.append(f"관점별 충돌 [{nid}] {c.topic}: {views} — 평균 내거나 하나로 합치지 말고 둘 다 전달")
        for lim in (res.artifacts or {}).get("limits") or []:
            if lim not in f.notes:
                f.notes.append(f"한계({nid}): {_mask_loose_numbers(lim)}")
        for m in res.missing_items:
            reason = OUT_OF_SCOPE_TEXT if OUT_OF_SCOPE_ITEM.search(m) else f"{nid} 미충족 항목"
            f.gaps.append({"label": m, "reason": reason}) if not any(g["label"] == m for g in f.gaps) else None
    f.flags += conflicts
    f.notes.append(DIRECTION_RULE)
    f.trimmed_items = trim_ledger(f)
    return f, conflicts


def trim_ledger(f: Facts) -> int:
    """판정·한계 문장에서 쓰지 않는 사건 항목('사건 E#' 항목)을 장부에서 뺌. 반환: 뺀 항목 수."""
    used = {k for t in [*f.flags, *f.notes] for k in PLACEHOLDER.findall(t)}
    drop = [k for k, v in f.items.items() if TRIM_LABEL.match(v["label"]) and k not in used]
    for k in drop:
        del f.items[k]
    return len(drop)


def docs_from_report(report: dict, limit: int = 12) -> list[dict]:
    """에이전트 6 의 근거 문장 문서를 참고 문서(D번호) 형태로. 다른 에이전트는 문서 없음."""
    res = report["results"].get("N11")
    if not res:
        return []
    docs, seen = [], set()
    for ev in (res.artifacts or {}).get("events") or []:
        for e in ev["evidence"]:
            if e["doc_id"] in seen:
                continue
            seen.add(e["doc_id"])
            docs.append({"id": f"D{len(docs) + 1}", "title": e["sentence"][:80], "summary": e["sentence"], "source": e["source"],
                         "published": e["date"], "url": e.get("url"), "doc_id": e["doc_id"], "chunk_id": e.get("chunk_id")})
            if len(docs) >= limit:
                return docs
    return docs


def outlook_for(agent_no: int, facts: Facts, as_of: str, ticker: str, co: dict | None, inputs: dict | None,
                validated: bool, fetch: bool = True) -> dict:
    """20거래일 전망 결론 (#54). 서술용 노드 실행 결과는 바꾸지 않고, 규칙에 필요한 장부가 없을 때만 확장 노드를 따로 돌려 가져옴
    (에이전트 4 의 순매수 강도는 확장 노드 N08 의 값). 장부만으로 정해지므로 같은 기준일이면 같은 결론."""
    from . import outlook

    items = facts.items
    if fetch and agent_no == 4 and not any(v.get("label", "").endswith("순매수 강도(거래대금 대비)") for v in items.values()):
        try:
            items = {**merge_facts(run_nodes(4, ticker, as_of, True, None, None, co, inputs, validated))[0].items, **items}
        except Exception:  # noqa: BLE001 — 전망 계산 실패가 서술 경로를 막지 않게 함. 결론은 '근거 부족'
            items = facts.items
    return outlook.compute(agent_no, items, as_of)


def build_data(agent_no: int, ticker: str, as_of: str | None = None, extension: bool = False, scenario: str | None = None,
               focus: list[str] | None = None, co: dict | None = None, inputs: dict | None = None,
               report: dict | None = None, validated: bool = False) -> AgentData:
    from . import db
    from .agents import normalize_as_of

    as_of = normalize_as_of(as_of)
    co = co or (db.company(ticker) if inputs is None else {"ticker": ticker, "name": ticker})
    report_given = report
    report = report or run_nodes(agent_no, ticker, as_of, extension, scenario, focus, co, inputs, validated)
    facts, conflicts = merge_facts(report)
    outlook_data = outlook_for(agent_no, facts, as_of, ticker, co, inputs, validated, fetch=inputs is not None or report_given is None)
    opts: dict[str, Any] = {k: v for k, v in {"extension": extension or None, "scenario": scenario, "focus": focus}.items() if v}
    extra = {"node_agent": True, "node_report": report, "opts": opts, "conflicts": conflicts,
             "next_checks": [], "freshness": None, "outlook": outlook_data}
    return AgentData(agent_no, spec_for(agent_no).name, co, as_of, facts, docs_from_report(report), "노드 실행", extra,
                     spec=spec_for(agent_no))


def legacy_to_nodes(old_agent_id: int, ticker: str, as_of: str | None = None, **kw) -> list[AgentData]:
    """옛 에이전트 번호(1 거시, 3 투자심리·수급)의 호출을 변환표(p01→3, p03→4·6)로 새 에이전트에 넘김."""
    from .nodes import legacy_agent_nos

    return [build_data(no, ticker, as_of, **kw) for no in legacy_agent_nos(old_agent_id)]
