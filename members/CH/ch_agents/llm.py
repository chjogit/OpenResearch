"""LLM 계층: 프롬프트 → JSON 출력 → 코드 검사 → (1회 수정 요청) → 검증 안 된 문장 제거 → 렌더링.

LLM이 실패하거나 형식을 못 맞추면 코드 판정(flags)으로 규칙 기반 대체 요약을 만듭니다.
최종 출력에는 장부에 없는 숫자가 남지 않습니다.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from .agents import AGENTS, AgentData, fetch_agent_data
from .glossary import terms_for

MODEL = os.getenv("UPSTAGE_MODEL_NAME", "solar-pro4")

COMMON_RULES = """[절대 준수 원칙]
1. 숫자를 직접 쓰지 마십시오. 숫자가 필요하면 [숫자 장부]의 키를 중괄호로 쓰십시오. 예: "원/달러는 {M7}로 ..."
   기간 표현(예: 20일, 3개월, 1분기)도 장부 항목 이름에 있는 그대로만 쓰십시오.
2. 장부에 없는 키나 '무자료' 항목의 값을 만들지 마십시오. 무자료 항목은 '미확인'에 적으십시오.
3. '매수 추천', '매도 추천', '목표주가', '비중 확대', '비중 축소' 표현은 금지합니다.
4. 각 주장은 사실(데이터가 직접 보여줌)·해석(원인·의미 설명)·예측(앞으로) 중 하나로 구분하고,
   사실과 해석에는 근거 키를 1개 이상 붙이십시오.
5. 통계적 상관을 인과나 기업 노출로 표현하지 마십시오.
6. [코드 판정]은 규칙으로 계산된 결과입니다. 판정의 강도·방향 표현(뚜렷한/약한, 상회/하회, 가속/둔화, 개선/악화)을
   바꾸지 말고 그대로 쓰십시오. 판정과 반대되는 주장을 하려면 근거 키를 대십시오.
7. 키 뒤에 단위나 수량 단어를 다시 붙이지 마십시오. 값에 이미 단위가 있습니다. 예: "{F18}개 분기"(X) → "{F18}"(O)
8. 항목 설명(※)에 '아님'으로 적힌 해석은 하지 마십시오. 예: 외국인 순매수일 평균 가격은 실제 매입 단가가 아닙니다."""

OUTPUT_SCHEMA = """반드시 아래 JSON 하나만 출력하십시오 (설명·코드블록 없이):
{
  "핵심진단": "1~2문장",
  "주장": [{"문장": "...", "구분": "사실|해석|예측", "근거": ["키", "..."]}],
  "긍정요인": ["..."],
  "리스크요인": ["..."],
  "미확인": ["판단에 필요하지만 데이터가 없는 것"],
  "다음점검": ["다음에 확인할 지표와 시점"],
  "자체점수": 1~10 정수 (이 관점에서 판단에 쓸 수 있는 근거가 얼마나 충분한지),
  "점수이유": "..."
}
주장은 3~7개로 쓰십시오."""

EXAMPLE = """[출력 예시 — 형식만 참고, 키와 내용은 실제 장부를 쓰십시오]
{"핵심진단": "환율은 {X3} 기준 원화 강세 국면이고, 주가와의 동조성은 약합니다.",
 "주장": [{"문장": "원/달러가 3개월 동안 {X4} 변했다.", "구분": "사실", "근거": ["X4"]},
          {"문장": "원화 강세는 수출 대금의 원화 환산액을 줄이는 방향이지만 달러 비용 비중은 확인되지 않았다.", "구분": "해석", "근거": ["X4"]}],
 "긍정요인": ["..."], "리스크요인": ["..."], "미확인": ["기업의 달러 비용 비중"], "다음점검": ["..."],
 "자체점수": 6, "점수이유": "거시 변화는 충분하나 기업 노출 데이터가 없음"}"""

MODE_GUIDE = {
    "expert": "전문가 모드: 핵심 지표와 인과 경로 위주로 간결하게 쓰십시오.",
    "guide": ("입문자 모드: 문장을 짧고 쉽게 쓰고, 전문 용어가 처음 나오면 괄호로 풀이하십시오. "
              "'왜 이 지표를 보는지'를 주장 하나 이상에 담으십시오. "
              "JSON에 \"스스로질문\": [\"독자가 이 관점에서 스스로 확인해 볼 질문\" 2~3개]를 추가하십시오."),
}

PLACEHOLDER = re.compile(r"\{([A-Z]\d+)\}")
KEY = re.compile(r"^[A-Z]\d+$")
# 숫자와 단위가 붙어 있을 때만 '숫자'로 봄 ('2025 주주환원' 같은 띄어쓴 표현은 제외)
LOOSE_NUMBER = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?(?:%p|%|원|배|조|억|달러|bp|주|백분위)")
BANNED = ("매수 추천", "매도 추천", "목표주가", "비중 확대", "비중 축소")
# 투자 권유 문형만 금지 ('순매도하고' 같은 서술은 허용)
BANNED_RE = re.compile(r"(?<!순)(매수|매도)\s*(하세요|하십시오|하시길|를\s*권|를\s*추천|할\s*것을\s*권|가\s*바람직)")
COMMON_TERMS = {"52주"}  # 숫자가 들어 있지만 값이 아닌 용어
VALID_KINDS = {"사실", "해석", "예측"}


def get_llm(temperature: float = 0.0):
    from langchain_upstage import ChatUpstage

    return ChatUpstage(model=MODEL, temperature=temperature)


# JSON 출력 모드: 지원하면 형식 오류가 줄어듦. 매개변수 오류가 나면 이번 실행 동안 끄고 일반 호출로 진행
_JSON_MODE = {"on": os.getenv("CH_JSON_MODE", "on") == "on"}


def _is_param_error(e: Exception) -> bool:
    msg = f"{type(e).__name__} {e}".lower()
    return any(w in msg for w in ("response_format", "unsupported", "not supported", "invalid parameter",
                                  "badrequest", "400", "unexpected keyword"))


def invoke(model, msgs):
    """LLM 호출. JSON 모드를 먼저 시도하고, 지원하지 않으면 일반 호출로 바꿉니다."""
    if _JSON_MODE["on"] and hasattr(model, "bind"):
        try:
            return model.bind(response_format={"type": "json_object"}).invoke(msgs)
        except Exception as e:
            if not _is_param_error(e):
                raise
            _JSON_MODE["on"] = False
    return model.invoke(msgs)


# ---------------------------------------------------------------- 프롬프트

def build_messages(data: AgentData, mode: str = "expert") -> tuple[str, str]:
    spec = AGENTS[data.agent_id]
    f = data.facts
    system = f"""당신은 OpenResearch의 [A{data.agent_id}: {spec.name}]입니다.
{spec.role}

{COMMON_RULES}

[반드시 다룰 점검 항목]
""" + "\n".join(f"- {c}" for c in spec.checklist) + f"""

[출력 모드] {MODE_GUIDE[mode]}

{OUTPUT_SCHEMA}

{EXAMPLE}"""
    docs = "\n".join(f"- D{i + 1}: {d['published']} {d['title']}" for i, d in enumerate(data.docs)) or "- (없음)"
    flags = "\n".join(f"- {x}" for x in f.flags) or "- (없음)"
    notes = "\n".join(f"- {x}" for x in f.notes) or "- (없음)"
    user = f"""[대상] {data.company['name']} ({data.company['ticker']}) · 기준일 {data.as_of}
[관측 기간] {data.period}

[숫자 장부] (값을 쓰려면 키를 중괄호로)
{f.for_prompt()}

[코드 판정] (규칙으로 계산된 결과, 중괄호 키 포함)
{flags}

[해석 가이드] (숫자 없음)
{notes}

[참고 뉴스 제목] (정성 근거, 근거 키로 D번호 사용 가능)
{docs}"""
    return system, user


# ---------------------------------------------------------------- 파싱·검사

EXPECTED_KEYS = {"핵심진단", "주장", "빠진논점", "수정제안"}


def _json_objects(t: str):
    """문자열 안의 짝이 맞는 {...} 구간을 앞에서부터 차례로 돌려줍니다 (따옴표 안의 괄호는 무시)."""
    i = 0
    while (start := t.find("{", i)) >= 0:
        depth, in_str, esc = 0, False, False
        for j in range(start, len(t)):
            ch = t[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yield t[start:j + 1]
                    break
        i = start + 1


def parse_json(text: str) -> dict | None:
    """LLM 출력에서 JSON 객체를 찾습니다. 기대 키가 있는 객체를 먼저, 없으면 가장 큰 객체를 고릅니다."""
    t = re.sub(r"<(think|thinking|reasoning)>.*?</\1>", "", text or "", flags=re.DOTALL)  # 추론 블록 제거
    t = re.sub(r"```(?:json)?", "", t)
    found = []
    for seg in _json_objects(t):
        try:
            obj = json.loads(seg)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            if EXPECTED_KEYS & set(obj):
                return obj
            found.append(obj)
    return max(found, key=lambda o: len(json.dumps(o)), default=None)


BARE_KEY = re.compile(r"(?<![A-Za-z0-9{])[\[(]?([MFSD]\d{1,3})[\])]?(?![A-Za-z0-9}])")


def normalize_keys(obj, valid: set[str]):
    """문장 안의 'M7', '[M7]', '(M7)' 처럼 쓴 장부 키를 '{M7}'로 맞춥니다. 장부에 있는 키만 바꿉니다."""
    if isinstance(obj, str):
        return BARE_KEY.sub(lambda m: "{" + m.group(1) + "}" if m.group(1) in valid else m.group(0), obj)
    if isinstance(obj, list):
        return [normalize_keys(x, valid) for x in obj]
    if isinstance(obj, dict):
        return {k: (v if k == "근거" else normalize_keys(v, valid)) for k, v in obj.items()}
    return obj


def _valid_keys(data: AgentData) -> set[str]:
    return set(data.facts.items) | {f"D{i + 1}" for i in range(len(data.docs))}


def _texts(result: dict) -> list[str]:
    out = [str(result.get("핵심진단", "")), str(result.get("점수이유", ""))]
    out += [str(c.get("문장", "")) for c in result.get("주장", []) if isinstance(c, dict)]
    for k in ("긍정요인", "리스크요인", "미확인", "다음점검", "스스로질문"):
        out += [str(x) for x in result.get(k) or []]
    return out


def label_terms(data: AgentData | None) -> set[str]:
    """장부 항목 이름에 들어 있는 숫자 표현(예: '52주 고점'의 '52주')은 값이 아니라 용어로 봅니다."""
    terms = set(COMMON_TERMS)
    if data is not None:
        for v in data.facts.items.values():
            terms.update(LOOSE_NUMBER.findall(v["label"]))
    return terms


def sentence_problems(text: str, valid: set[str], allowed: set[str] | None = None) -> list[str]:
    probs = []
    bad = [k for k in PLACEHOLDER.findall(text) if k not in valid]
    if bad:
        probs.append(f"없는 키 {bad}")
    loose = [x for x in LOOSE_NUMBER.findall(PLACEHOLDER.sub("", text)) if x not in (allowed or COMMON_TERMS)]
    if loose:
        probs.append(f"키 밖 숫자 {loose}")
    banned = [w for w in BANNED if w in text] + [m.group(0) for m in BANNED_RE.finditer(text)]
    if banned:
        probs.append(f"금지 표현 {banned}")
    return probs


def auto_keys(obj, data: AgentData):
    """LLM이 장부 값을 글자 그대로 옮겨 쓴 경우(예: '8.36배') 그 값의 키로 바꿉니다.
    값이 장부 표기와 정확히 같을 때만 바꾸므로, 결과는 여전히 DB 값만 인용합니다."""
    table: dict[str, str] = {}
    for k, v in data.facts.items.items():
        if v["unit"] != "doc" and v["text"] != "무자료" and re.search(r"\d", v["text"]):
            table.setdefault(v["text"], k)
    if not table:
        return obj
    pat = re.compile(r"(?<![\d.,{])(" + "|".join(re.escape(t) for t in sorted(table, key=len, reverse=True))
                     + r")(?![\d])")

    def walk(x):
        if isinstance(x, str):
            return pat.sub(lambda m: "{" + table[m.group(1)] + "}", x)
        if isinstance(x, list):
            return [walk(y) for y in x]
        if isinstance(x, dict):
            return {k: (v if k == "근거" else walk(v)) for k, v in x.items()}
        return x

    return walk(obj)


def check_output(result: dict, data: AgentData) -> dict[str, list[str]]:
    valid, allowed = _valid_keys(data), label_terms(data)
    checks: dict[str, list[str]] = {"형식": [], "문장": [], "근거": []}
    for field in ("핵심진단", "주장", "자체점수"):
        if field not in result:
            checks["형식"].append(f"'{field}' 없음")
    claims = result.get("주장")
    if not isinstance(claims, list) or not claims:
        checks["형식"].append("'주장'이 비었거나 목록이 아님")
        claims = []
    score = result.get("자체점수")
    if not (isinstance(score, int) and 1 <= score <= 10):
        checks["형식"].append(f"'자체점수'가 1~10 정수가 아님 ({score!r})")
    for text in _texts(result):
        for p in sentence_problems(text, valid, allowed):
            checks["문장"].append(f"{p}: {text[:60]}")
    for c in claims:
        if not isinstance(c, dict):
            checks["형식"].append("주장 항목이 객체가 아님")
            continue
        if c.get("구분") not in VALID_KINDS:
            checks["형식"].append(f"구분 값 오류: {c.get('구분')!r}")
        refs = [str(k) for k in (c.get("근거") or [])]
        bad = [k for k in refs if not KEY.match(k) or k not in valid]
        if bad:
            checks["근거"].append(f"근거 키 오류 {bad}: {str(c.get('문장'))[:40]}")
        if c.get("구분") in ("사실", "해석") and not [k for k in refs if k in valid]:
            checks["근거"].append(f"근거 없는 {c.get('구분')}: {str(c.get('문장'))[:40]}")
    return {k: v for k, v in checks.items() if v}


def sanitize(result: dict, data: AgentData) -> tuple[dict, list[str]]:
    """검사를 통과하지 못한 문장을 빼서, 최종 출력에 검증 안 된 숫자·표현이 남지 않게 합니다."""
    valid, allowed = _valid_keys(data), label_terms(data)
    removed: list[str] = []
    out = dict(result)
    if sentence_problems(str(out.get("핵심진단", "")), valid, allowed):
        removed.append(str(out.get("핵심진단")))
        out["핵심진단"] = "(검증되지 않은 숫자가 있어 생략. 아래 주장을 참고)"
    claims = []
    for c in out.get("주장") or []:
        if not isinstance(c, dict):
            continue
        refs = [str(k) for k in (c.get("근거") or []) if str(k) in valid]
        text = str(c.get("문장", ""))
        if sentence_problems(text, valid, allowed) or (c.get("구분") in ("사실", "해석") and not refs) \
                or c.get("구분") not in VALID_KINDS:
            removed.append(text)
            continue
        claims.append({"문장": text, "구분": c["구분"], "근거": refs})
    out["주장"] = claims
    for k in ("긍정요인", "리스크요인", "미확인", "다음점검", "스스로질문"):
        kept = []
        for x in out.get(k) or []:
            (removed if sentence_problems(str(x), valid, allowed) else kept).append(str(x))
        out[k] = kept
    if not (isinstance(out.get("자체점수"), int) and 1 <= out["자체점수"] <= 10):
        out["자체점수"] = None
    return out, removed


# ---------------------------------------------------------------- 규칙 기반 대체

def fallback_result(data: AgentData) -> dict:
    f = data.facts
    spec = AGENTS[data.agent_id]
    claims = [{"문장": fl, "구분": "사실", "근거": PLACEHOLDER.findall(fl)} for fl in f.flags]
    claims = [c for c in claims if c["근거"]]
    seen_groups = set()
    for k, v in f.items.items():  # 판정이 적으면 그룹별 대표 숫자를 사실로 덧붙임
        if len(claims) >= 6:
            break
        if v["group"] and v["group"] not in seen_groups and v["unit"] != "doc":
            seen_groups.add(v["group"])
            claims.append({"문장": f"{v['label']}: {{{k}}}", "구분": "사실", "근거": [k]})
    head = " / ".join(c["문장"] for c in claims[:2]) or "규칙 판정 결과가 없습니다."
    return {
        "핵심진단": head,
        "주장": claims,
        "긍정요인": [],
        "리스크요인": [c["문장"] for c in claims if c["문장"].startswith(("경고", "주의"))],
        "미확인": [f"{g['label']} ({g['reason']})" for g in f.gaps],
        "다음점검": list(spec.next_checks),
        "자체점수": None,
        "점수이유": "LLM 없이 코드 판정만으로 만든 요약",
    }


# ---------------------------------------------------------------- 렌더링

def render(text: Any, data: AgentData) -> str:
    items = data.facts.items

    def sub(m):
        k = m.group(1)
        if k in items:
            return f"**{items[k]['text']}**`[{k}]`"
        if k.startswith("D") and k[1:].isdigit() and int(k[1:]) <= len(data.docs):
            return f"`[{k}]`"
        return f"⟨없는 키 {k}⟩"

    out = PLACEHOLDER.sub(sub, str(text))
    # LLM이 키 뒤에 단위를 한 번 더 쓴 경우 (예: '6개[F18]개', '260,349원[S19]원') 중복을 지움
    return DUP_UNIT.sub(r"\1", out)


DUP_UNIT = re.compile(r"(\*\*[^*]*?(개|일|배|원|주|%p|%)\*\*`\[[A-Z]\d+\]`)\2")


def to_markdown(data: AgentData, result: dict, status: str, checks: dict, removed: list[str],
                mode: str = "expert") -> str:
    r = lambda t: render(t, data)
    f = data.facts
    out = [f"- **상태**: {status}", f"- **관측 기간**: {data.period}",
           f"- **핵심 진단**: {r(result.get('핵심진단', ''))}", "", "**주장과 근거**", ""]
    for c in result.get("주장", []):
        out.append(f"- [{c.get('구분')}] {r(c.get('문장', ''))} (근거: {', '.join(c.get('근거') or []) or '-'})")
    for title, key in (("긍정 요인", "긍정요인"), ("리스크 요인", "리스크요인"), ("미확인", "미확인"),
                       ("다음 점검", "다음점검"), ("스스로 확인해 볼 질문", "스스로질문")):
        items = result.get(key) or []
        if items:
            out += ["", f"**{title}**", ""] + [f"- {r(x)}" for x in items]
    score = result.get("자체점수")
    out += ["", f"**자체 점수**: {score if score is not None else '-'} / 10 · {r(result.get('점수이유', ''))}"]
    if f.flags:
        out += ["", "**코드 판정**", ""] + [f"- {r(x)}" for x in f.flags]
    out += ["", "**숫자 장부**", "", f.table_md()]
    if f.gaps:
        out += ["", "**무자료**", ""] + [f"- {g['label']}: {g['reason']}" for g in f.gaps]
    if data.docs:
        out += ["", "**참고 뉴스(제목)**", ""] + [f"- D{i + 1} · {d['published']} · {d['title']}"
                                             for i, d in enumerate(data.docs)]
    if mode == "guide":
        terms = terms_for([v["label"] for v in f.items.values()] + f.flags)
        if terms:
            out += ["", "**용어 풀이**", ""] + [f"- **{t}**: {d}" for t, d in terms]
    if checks:
        out += ["", "**코드 검사 기록**: " + "; ".join(f"{k} {len(v)}건" for k, v in checks.items())]
    if removed:
        out += [f"- 검증되지 않아 최종 출력에서 뺀 문장 {len(removed)}개"]
    return "\n".join(out)


# ---------------------------------------------------------------- 실행

def run_agent(agent_id: int, ticker: str | None = None, mode: str = "expert", llm=None,
              data: AgentData | None = None, as_of: str | None = None, max_repair: int = 1) -> dict:
    """에이전트 하나를 실행해 팀 공통 출력 계약 dict 를 돌려줍니다."""
    if data is None:
        data = fetch_agent_data(agent_id, ticker, as_of)
    system, user = build_messages(data, mode)
    attempts: list[dict] = []
    result, checks, status, best_at, best_n = None, {}, "실패", -1, None
    t0 = time.monotonic()
    try:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        model = llm or get_llm()
        msgs = [SystemMessage(content=system), HumanMessage(content=user)]
        for attempt in range(max_repair + 1):
            raw = invoke(model, msgs).content
            parsed = parse_json(raw)
            if parsed is not None:
                parsed = auto_keys(normalize_keys(parsed, _valid_keys(data)), data)
            checks = check_output(parsed, data) if parsed is not None else {"형식": ["JSON 아님"]}
            attempts.append({"raw": raw, "checks": checks})
            n_prob = sum(len(v) for v in checks.values())
            if parsed is not None and (best_n is None or n_prob <= best_n):  # 문제가 더 적은 출력을 채택
                result, best_at, best_n = parsed, attempt, n_prob
            if not checks or attempt == max_repair:
                break
            problems = "\n".join(f"- {k}: {x}" for k, v in checks.items() for x in v[:8])
            msgs += [AIMessage(content=raw), HumanMessage(content=(
                "출력에 아래 문제가 있습니다. 같은 장부만 써서 고친 JSON 하나만 다시 출력하십시오.\n" + problems))]
    except Exception as e:  # noqa: BLE001  호출 실패도 결과로 남김
        attempts.append({"error": f"{type(e).__name__}: {e}"})
    removed: list[str] = []
    if result is None:
        err = next((a["error"] for a in attempts if "error" in a), None)
        result = fallback_result(data)
        status = "규칙 기반 대체" + (f" (LLM 호출 실패: {err.split(':')[0]})" if err else " (JSON 형식 아님)")
    else:
        result, removed = sanitize(result, data)
        if not result["주장"]:
            result, status = fallback_result(data), "규칙 기반 대체"
        else:
            checks = attempts[best_at]["checks"]
            status = "완료" + (" (수정 1회)" if best_at > 0 else "") + (" (일부 문장 제외)" if removed else "")
    md = to_markdown(data, result, status, checks, removed, mode)
    facts = data.facts
    return {
        "agent_id": agent_id, "agent_name": data.name, "status": status, "period": data.period,
        "as_of": data.as_of, "result": result, "facts": facts.items, "gaps": facts.gaps, "flags": facts.flags,
        "checks": checks, "removed": removed, "attempts": attempts, "seconds": round(time.monotonic() - t0, 1),
        "analysis": md,
        "source": "Neon " + ", ".join(sorted({v["source"].split(" (")[0] for v in facts.items.values()})),
    }


def run_my_agents(ticker: str, mode: str = "expert", agent_ids=(1, 2, 4), as_of: str | None = None,
                  llm=None) -> list[dict]:
    """CH 담당 관점을 한 번에 실행해 오케스트레이터에 넘길 리스트를 돌려줍니다."""
    from . import db

    co = db.company(ticker)
    return [run_agent(a, mode=mode, llm=llm, data=fetch_agent_data(a, ticker, as_of, co=co)) for a in agent_ids]
