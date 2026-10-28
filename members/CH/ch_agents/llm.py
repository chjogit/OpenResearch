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

from .agents import AGENTS, MY_AGENTS, AgentData, fetch_agent_data
from .availability import AVAIL_SHORT, availability
from . import contract as contract_mod
from . import exposure as exposure_mod
from . import verify as verifier
from .glossary import terms_for
from .prompts import mode_guide
from .rag import PROMPT_RULE as RAG_RULE
from .rag import docs_for_prompt, docs_markdown
from .semantic import baseline_problems, direction_problems, flag_directions
from . import p01 as p01_mod
from . import p03 as p03_mod

MODEL = os.getenv("UPSTAGE_MODEL_NAME", "solar-pro4")

COMMON_RULES = """[절대 준수 원칙]
1. 숫자를 직접 쓰지 마십시오. 숫자가 필요하면 [숫자 장부]의 키를 중괄호로 쓰십시오. 예: "원/달러는 {M7}로 ..."
   기간 표현(예: 20일, 3개월, 1분기)도 장부 항목 이름에 있는 그대로만 쓰십시오.
2. 장부에 없는 키나 '무자료' 항목의 값을 만들지 마십시오. 무자료 항목은 '미확인'에 적으십시오.
3. '매수 추천', '매도 추천', '목표주가', '비중 확대', '비중 축소' 표현은 금지합니다.
4. 각 주장은 사실(데이터가 직접 보여줌)·해석(원인·의미 설명)·예측(앞으로) 중 하나로 구분하고,
   사실과 해석에는 근거 키를 1개 이상 붙이십시오.
5. 통계적 상관을 인과나 기업 노출로 표현하지 마십시오.
6. [코드 판정]은 규칙으로 계산된 결과입니다. 판정의 강도·방향 표현(상관 강함/보통/약함, 유의함/유의하지 않음,
   상회/하회, 가속/둔화, 개선/악화)을 바꾸지 말고 그대로 쓰십시오. 상관의 크기와 유의성은 서로 다른 말입니다.
   판정과 반대되는 주장을 하려면 근거 키를 대십시오.
7. 키 뒤에 단위나 수량 단어를 다시 붙이지 마십시오. 값에 이미 단위가 있습니다. 예: "{F18}개 분기"(X) → "{F18}"(O)
8. 항목 설명(※)에 '아님'으로 적힌 해석은 하지 마십시오. 예: 외국인 순매수일 평균 가격은 실제 매입 단가가 아닙니다.
9. "반대근거"에는 핵심진단과 반대 방향을 가리키는 근거나 하방 위험을 1~3개 쓰십시오. 사용자 성향과 상관없이 늘 씁니다.
10. [미확인 전제]의 항목(헤지 여부, 결제 시점, 판가 전가력 등)을 확인된 것처럼 쓰거나 가정하지 마십시오.
11. 수급(순매수) 기록만으로 매수·매도 의도, 세력, 내부 정보 보유를 추정하지 마십시오.
12. [코드 판정]의 '중복 신호 주의'로 묶인 신호(뉴스 논조·검색 관심·거래대금·집중 매매)는 같은 사건의 한 묶음입니다.
    여러 개의 독립 근거로 세거나 '두 신호가 함께 확인되어 더 강하다'고 쓰지 마십시오.
13. 감성 점수는 키워드 사전 기준선이며 학습 모델의 검증된 결과가 아닙니다. 긍정 문서가 많다는 것을 수익률 전망으로 쓰지 마십시오.
14. """ + RAG_RULE

OUTPUT_SCHEMA = """반드시 아래 JSON 하나만 출력하십시오 (설명·코드블록 없이):
{
  "핵심진단": "1~2문장",
  "주장": [{"문장": "...", "구분": "사실|해석|예측", "근거": ["키", "..."]}],
  "반대근거": [{"문장": "핵심진단과 반대 방향의 근거 또는 하방 위험", "구분": "사실|해석|예측", "근거": ["키"]}],
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
 "반대근거": [{"문장": "헤지 비율이 확인되지 않아 환율 영향이 실제보다 작을 수 있다.", "구분": "해석", "근거": ["X4"]}],
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
BANNED = ("매수 추천", "매도 추천", "목표주가", "목표 주가", "목표가", "비중 확대", "비중 축소")
# 투자 권유 문형만 금지 ('순매도하고' 같은 서술은 허용)
BANNED_RE = re.compile(r"(?<!순)(매수|매도)\s*(하세요|하십시오|하시길|를\s*권|를\s*추천|할\s*것을\s*권|가\s*바람직)")
COMMON_TERMS = {"52주"}  # 숫자가 들어 있지만 값이 아닌 용어
VALID_KINDS = {"사실", "해석", "예측"}
# 수급만으로 의도·정보 보유를 추정하는 표현 (R4 에이전트 3 제약). 바로 뒤에 부정('추정할 수 없다')이 오면 허용
INTENT_RE = re.compile(r"(매수|매도|매집)\s*의도|세력|작전|내부\s*정보|미리\s*알고|정보를\s*(알고|쥐고|가지고)|매집")
INTENT_NEG = re.compile(r"^[^.]{0,45}(추정(할|하지|해서는|은)|단정(할|하지)|알\s*수\s*없|확인(할|되지)|아님|아니|"
                        r"판단(은|을)?[^.]{0,15}(내리지|하지)\s*않)")
# 중복 신호를 독립 근거처럼 세는 표현 (R4 에이전트 3 제약)
INDEP_RE = re.compile(r"(두|세|2|3|여러|복수)\s*(가지|개)?\s*(의\s*)?(신호|근거|지표)[^.]{0,15}(뒷받침|확인|입증|강화)"
                      r"|독립(된|적인)?\s*(근거|신호)|이중으로\s*확인|동시에\s*(확인|뒷받침)|함께\s*(확인|뒷받침)"
                      r"|더욱\s*(강하|확실|분명)|신뢰도(가|를)\s*높")
SAME_RE = re.compile(r"같은\s*사건|중복|하나의\s*(사건|근거|묶음)|사건\s*묶음|독립(된|적인)?\s*(근거|신호)(가|로)?\s*(아니|보지|세지)")
CLAIM_FIELDS = ("주장", "반대근거")


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
    system = f"""당신은 OpenResearch의 [{spec.name}]입니다.
{spec.role}

{COMMON_RULES}

[반드시 다룰 점검 항목]
""" + "\n".join(f"- {c}" for c in spec.checklist) + f"""

[출력 모드]
{mode_guide(mode, data.agent_id)}

{OUTPUT_SCHEMA}

{EXAMPLE}"""
    docs = docs_for_prompt(data.docs)
    flags = "\n".join(f"- {x}" for x in f.flags) or "- (없음)"
    notes = "\n".join(f"- {x}" for x in f.notes) or "- (없음)"
    opts = data.extra.get("opts") or {}
    asked = []
    if opts.get("focus"):
        asked.append("관심 거시 변수: " + ", ".join(opts["focus"]))
    if opts.get("period"):
        asked.append(f"관찰 기간: {data.extra.get('obs_period', opts['period'])}거래일")
    if opts.get("scenario"):
        asked.append("시나리오: " + str(opts["scenario"]))
    if opts.get("question"):
        asked.append("질문: " + str(opts["question"]))
    user = f"""[대상] {data.company['name']} ({data.company['ticker']}) · 기준일 {data.as_of}
[사용자 입력] {' / '.join(asked) or '없음'}
[관측 기간] {data.period}

[숫자 장부] (값을 쓰려면 키를 중괄호로)
{f.for_prompt()}

[코드 판정] (규칙으로 계산된 결과, 중괄호 키 포함)
{flags}

[해석 가이드] (숫자 없음)
{notes}
{_extra_sections(data)}
[참고 문서] (DB에서 이 관점으로 검색한 공시·뉴스·여론. 정성 근거, 근거 키로 D번호 사용)
{docs}"""
    return system, user


TASK_STATE = {"answered": "답함", "held": "보류", "not_requested": "요청 없음"}


def _task_section(data: AgentData) -> list[str]:
    """제작 기준(P01·P03) 과업 계약. 답함 과업은 해당 장부 키로 답하고, 보류 과업은 미확인에 사유를 적게 합니다."""
    px = data.extra.get("p01") or data.extra.get("p03")
    if not px:
        return []
    out = ["", "[과업 계약] (제작 기준. '답함' 과업은 그 그룹의 장부 키로 반드시 다루고, '보류' 과업은 숫자 없이 "
                "미확인에 사유를 적을 것. 사용자 질문이 있으면 핵심진단 첫 문장이 질문에 답해야 함)"]
    groups = {"예측": "실적 예측(기준선)", "시나리오": "시나리오(공시 정적 환산)", "과거관계": "과거 관계(사건 연구)"}
    for name, t in (px["plan"].get("tasks") or {}).items():
        if t.get("state") == "not_requested":
            continue
        codes = ", ".join(t.get("codes") or [])
        g = f" · 장부 그룹 [{groups[name]}]" if name in groups and t.get("state") == "answered" else ""
        out.append(f"- {name}: {TASK_STATE.get(t.get('state'), t.get('state'))}{g}"
                   + (f" ({codes})" if codes else "") + (f" — {t['note']}" if t.get("note") else ""))
    return out


def _extra_sections(data: AgentData) -> str:
    """에이전트별 코드 표를 프롬프트에 넣습니다: 과업 계약, 1 미확인 전제, 3 기준선 비교."""
    out = _task_section(data)
    prem = data.extra.get("premises")
    if prem:
        out += ["", "[미확인 전제] (확인되지 않은 것은 가정하지 말 것)"]
        out += [f"- {p['item']}: {p['status']} — {p['detail']}" + (" " + " ".join("{" + k + "}" for k in p["keys"])
                                                                 if p["keys"] else "") for p in prem]
    base = data.extra.get("baseline")
    if base:
        out += ["", "[기준선 비교] (규칙·사전 기준선 대비 현재. 상태는 코드 판정)"]
        for b in base:
            ks = [f"{n} {{{b[k]}}}" for n, k in (("현재", "current"), ("기준선", "base"), ("비교", "measure")) if b.get(k)]
            out.append(f"- {b['signal']} ({b['method']}): " + ", ".join(ks) + f" → {b['status']}")
    return "\n".join(out)


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


def _opinion_keys(data: AgentData) -> set[str]:
    """개인 의견(블로그·카페·댓글) 문서의 D키. 이것만으로는 '사실' 주장의 근거가 될 수 없습니다."""
    return {f"D{i + 1}" for i, d in enumerate(data.docs) if "개인 의견" in str(d.get("kind", ""))}


def _texts(result: dict) -> list[str]:
    out = [str(result.get("핵심진단", "")), str(result.get("점수이유", ""))]
    for field in CLAIM_FIELDS:
        out += [str(c.get("문장", "")) for c in result.get(field) or [] if isinstance(c, dict)]
    for k in ("긍정요인", "리스크요인", "미확인", "다음점검", "스스로질문"):
        out += [str(x) for x in result.get(k) or []]
    return out


def label_terms(data: AgentData | None) -> set[str]:
    """장부 항목 이름에 들어 있는 숫자 표현(예: '52주 고점'의 '52주')은 값이 아니라 용어로 봅니다."""
    terms = set(COMMON_TERMS)
    if data is not None:
        for v in data.facts.items.values():
            terms.update(LOOSE_NUMBER.findall(v["label"]))
        # 사용자가 입력한 가정·질문 속 숫자(예: '환율 5% 상승, 금리 0.5%p 하락')는 값이 아니라 조건
        opts = (data.extra or {}).get("opts") or {}
        for k in ("scenario", "question"):
            terms.update(LOOSE_NUMBER.findall(str(opts.get(k) or "")))
    terms.update({t.lstrip("+-") for t in terms})   # '+5%' 라벨과 '5%' 문장을 같은 용어로
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
    intent = [m.group(0) for m in INTENT_RE.finditer(text) if not INTENT_NEG.search(text[m.end():m.end() + 60])]
    if intent:
        probs.append(f"수급만으로 의도·정보 보유 추정 {intent}")
    return probs


def duplicate_problems(text: str, refs, data: AgentData | None) -> list[str]:
    """'중복 신호 주의'로 묶인 신호 둘 이상을 근거로 들며 독립 근거처럼 세는 문장을 찾습니다."""
    if data is None:
        return []
    keys = set(PLACEHOLDER.findall(str(text))) | {str(k) for k in refs or []}
    out = []
    for c in data.extra.get("dup_clusters") or []:
        hit = [s for s, ks in (c.get("members") or {}).items() if keys & set(ks)]
        if len(hit) >= 2 and INDEP_RE.search(str(text)) and not SAME_RE.search(str(text)):
            out.append(f"중복 신호({'·'.join(hit)})를 독립 근거로 셈")
    return out


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
    dirs = flag_directions(data.facts)
    checks["방향"] = []
    checks["중복 신호"] = []
    counter = result.get("반대근거") or []
    if not isinstance(counter, list):
        checks["형식"].append("'반대근거'가 목록이 아님")
        counter = []
    for c in claims + counter:
        if isinstance(c, dict):
            refs = [str(k) for k in (c.get("근거") or [])]
            for p in duplicate_problems(str(c.get("문장", "")), refs, data):
                checks["중복 신호"].append(f"{p}: {str(c.get('문장'))[:60]}")
    for t in [str(result.get("핵심진단", ""))] + [str(x) for x in result.get("긍정요인") or []]:
        for p in duplicate_problems(t, None, data):
            checks["중복 신호"].append(f"{p}: {t[:60]}")
    baseline = data.extra.get("baseline")
    for c in claims + counter:   # 반대근거도 같은 기준으로 점검
        if isinstance(c, dict):
            refs = [str(k) for k in (c.get("근거") or [])]
            text = str(c.get("문장", ""))
            for p in direction_problems(text, data.facts, refs, dirs) + baseline_problems(text, refs, baseline):
                checks["방향"].append(f"{p}: {text[:60]}")
    for key in ("핵심진단", "긍정요인", "리스크요인"):
        vals = result.get(key) or []
        for t in [vals] if isinstance(vals, str) else vals:
            for p in direction_problems(str(t), data.facts, None, dirs) + baseline_problems(str(t), None, baseline):
                checks["방향"].append(f"{p}: {str(t)[:60]}")
    opinion = _opinion_keys(data)
    for c in claims + counter:
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
        elif c.get("구분") == "사실" and refs and set(refs) <= opinion:
            checks["근거"].append(f"개인 의견 문서만 근거인 사실 주장(해석으로 바꾸거나 근거 추가): {str(c.get('문장'))[:40]}")
    # 제작 기준(P01·P03): 참고용(tier=reference) 항목만으로 핵심 진단·주장을 세우지 않음 (반대근거는 허용)
    ref = {k for k, it in data.facts.items.items() if it.get("tier") == "reference"}
    if ref:
        for c in claims:
            if isinstance(c, dict):
                ks = [k for k in [str(x) for x in c.get("근거") or []] + PLACEHOLDER.findall(str(c.get("문장", "")))
                      if k in data.facts.items]
                if ks and set(ks) <= ref:
                    checks["근거"].append(f"참고용 항목만 근거인 주장(제작 기준 밖, 기준 항목 근거를 추가하거나 빼기): "
                                         f"{str(c.get('문장'))[:40]}")
        head = [k for k in PLACEHOLDER.findall(str(result.get("핵심진단", ""))) if k in data.facts.items]
        if head and set(head) <= ref:
            checks["근거"].append("핵심진단이 참고용 항목만 인용함 (제작 기준 항목을 중심으로)")
    return {k: v for k, v in checks.items() if v}


MAX_CLAIMS, MAX_COUNTER = 7, 3   # 프롬프트의 '주장 3~7개', '반대근거 1~3개'를 코드로도 지킴


def cap_claims(result: dict) -> tuple[dict, list[str]]:
    """주장·반대근거 개수 상한. 10/28 같은 입력으로 주장이 7개·20개로 달라졌는데, 상한이 프롬프트에만 있었습니다.
    LLM 이 쓴 순서(중요한 것부터)대로 앞에서 자르고, 자른 문장은 따로 돌려줍니다(검증 실패와 구분)."""
    out, trimmed = dict(result), []
    for field, cap in (("주장", MAX_CLAIMS), ("반대근거", MAX_COUNTER)):
        items = out.get(field) or []
        if len(items) > cap:
            trimmed += [str(c.get("문장", "")) for c in items[cap:] if isinstance(c, dict)]
            out[field] = items[:cap]
    return out, trimmed


def claim_stats(result: dict | None, vlog: list[dict], removed: list[str], trimmed: list[str]) -> dict:
    """품질 지표의 정의를 한 곳에 둡니다 (노트북 표가 '주장 6 · Verifier 통과 9'처럼 서로 다른 것을 세던 문제).

    - claims / counters: 최종 출력에 남은 주장·반대근거 수
    - verified_claims: Verifier 대조 기록 중 claimId 가 있고(주장·반대근거) 통과한 것
    - checked_sentences / passed_sentences: claimId 없는 문장(핵심진단·리스크요인 등)까지 포함한 전체 대조 수
    - removed / trimmed: 검증 실패로 뺀 문장 수 / 개수 상한으로 자른 문장 수"""
    res = result or {}
    return {
        "claims": len(res.get("주장") or []), "counters": len(res.get("반대근거") or []),
        "verified_claims": sum(1 for v in vlog if v.get("claimId") and v.get("ok")),
        "checked_sentences": len(vlog), "passed_sentences": sum(1 for v in vlog if v.get("ok")),
        "removed": len(removed), "trimmed": len(trimmed),
    }


def sanitize(result: dict, data: AgentData) -> tuple[dict, list[str]]:
    """검사를 통과하지 못한 문장을 빼서, 최종 출력에 검증 안 된 숫자·표현이 남지 않게 합니다."""
    valid, allowed = _valid_keys(data), label_terms(data)
    dirs = flag_directions(data.facts)

    def bad(t: str, refs=None) -> bool:
        return bool(sentence_problems(t, valid, allowed) or direction_problems(t, data.facts, refs, dirs)
                    or baseline_problems(t, refs, data.extra.get("baseline")) or duplicate_problems(t, refs, data))

    removed: list[str] = []
    opinion = _opinion_keys(data)
    out = dict(result)
    if bad(str(out.get("핵심진단", ""))):
        removed.append(str(out.get("핵심진단")))
        out["핵심진단"] = p01_mod.fallback_headline(data, "(검증되지 않은 숫자나 판정과 어긋난 표현이 있어 생략. 아래 주장을 참고)")
    for field in CLAIM_FIELDS:
        claims = []
        for c in out.get(field) or [] if isinstance(out.get(field), list) else []:
            if not isinstance(c, dict):
                continue
            refs = [str(k) for k in (c.get("근거") or []) if str(k) in valid]
            text = str(c.get("문장", ""))
            if bad(text, refs) or (c.get("구분") in ("사실", "해석") and not refs) \
                    or c.get("구분") not in VALID_KINDS or (c.get("구분") == "사실" and set(refs) <= opinion):
                removed.append(text)
                continue
            claims.append({"문장": text, "구분": c["구분"], "근거": refs})
        out[field] = claims
    for k in ("긍정요인", "리스크요인", "미확인", "다음점검", "스스로질문"):
        kept = []
        for x in out.get(k) or []:
            (removed if bad(str(x)) else kept).append(str(x))
        out[k] = kept
    if not (isinstance(out.get("자체점수"), int) and 1 <= out["자체점수"] <= 10):
        out["자체점수"] = None
    return out, removed


# ---------------------------------------------------------------- 규칙 기반 대체

NEGATIVE_RE = re.compile(r"악화|하회|순매도|높음|급증|지연|경고|주의|위험 회피|방향이 반대|엇갈림")

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
    used = {c["문장"] for c in claims}
    counter = [{"문장": fl, "구분": "사실", "근거": PLACEHOLDER.findall(fl)} for fl in f.flags
               if fl not in used and PLACEHOLDER.findall(fl) and NEGATIVE_RE.search(fl)][:3]
    return {
        "핵심진단": head,
        "주장": claims,
        "반대근거": counter,
        "긍정요인": [],
        "리스크요인": [c["문장"] for c in claims if c["문장"].startswith(("경고", "주의"))],
        "미확인": [f"{g['label']} ({g['reason']})" for g in f.gaps],
        "다음점검": list(dict.fromkeys([*(data.extra.get("next_checks") or []), *spec.next_checks])),
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


def _tables(data: AgentData) -> list[str]:
    """코드가 만든 표 (LLM 무관): 에이전트 1 노출 점검표, 에이전트 3 이상 징후·심리·수급 요약표."""
    r = lambda t: render(t, data)
    out: list[str] = []
    px = data.extra.get("p01")
    if px:
        out += ["", "**세 줄 요약 (제작 기준 P01 20.2)**", ""]
        out += [f"- {k}: {r(v)}" for k, v in (px.get("summary") or {}).items()]
        out += p01_mod.plan_md(px["plan"])
    rows = data.extra.get("exposure")
    if rows:
        out += ["", "**노출 점검표 (규칙 기반: 업종 기본값 → 통계 근거 → 재무 구조)**", "",
                exposure_mod.table_md(rows, r)]
    prem = data.extra.get("premises")
    if prem:
        out += ["", "**미확인 전제 (노출 등급은 아래 전제가 확인되지 않은 상태의 참고치)**", "",
                exposure_mod.premises_md(prem, r)]
    if data.agent_id == 3 and data.extra.get("p03"):
        p3 = data.extra["p03"]
        out += ["", "**세 줄 요약 (제작 기준 P03 20장)**", ""]
        out += [f"- {k}: {r(v)}" for k, v in (p3.get("summary") or {}).items()]
        out += p03_mod.plan_md(p3["plan"]) + p03_mod.event_md(p3.get("events") or [])
    if data.agent_id == 3:
        an = data.extra.get("anomalies") or []
        out += ["", "**이상 징후**", ""] + ([f"- {r(x)}" for x in an] or ["- 없음 (코드 기준에 걸린 항목 없음)"])
        base = data.extra.get("baseline") or []
        if base:
            out += ["", "**기준선 비교 (규칙·사전 기준선 대비 현재)**", "",
                    "| 신호 | 기준선 방식 | 현재 | 기준선 | 비교 | 상태 |", "| --- | --- | --- | --- | --- | --- |"]
            cell = lambda k: r("{" + k + "}") if k else "-"
            out += [f"| {b['signal']} | {b['method']} | {cell(b.get('current'))} | {cell(b.get('base'))} | "
                    f"{cell(b.get('measure'))} | {b['status']} |" for b in base]
        if data.extra.get("sentiment_model"):
            out += [f"- 감성 점수: {data.extra['sentiment_model']}"]
        for c in data.extra.get("dup_clusters") or []:
            out += ["", f"**중복 신호 주의 ({c['id']})**: {'·'.join(c['signals'])}은(는) 같은 사건을 반영할 수 있어 "
                        "하나의 사건 묶음으로 보고 독립 근거로 중복 계산하지 않습니다."]
    summary = data.extra.get("summary")
    if summary:
        P = data.extra.get("obs_period")
        out += ["", f"**심리·수급 요약표 (관찰 기간 {P}거래일)**", "", "| 계열 | 지표 | 값 | 코드 판정 |",
                "| --- | --- | --- | --- |"]
        for s in summary:
            out.append(f"| {s['group']} | {s['label']} | {r('{' + s['key'] + '}')} | {r(s['verdict']) or '-'} |")
    return out


def _claim_line(c: dict, data: AgentData, emap: dict[str, str]) -> str:
    tag = " ".join(f"[출처: {s}]" for s in c.get("출처") or [])
    refs = ", ".join(f"{emap.get(k, k)}·{k}" for k in c.get("근거") or []) or "-"
    cid = f"{c['claimId']} " if c.get("claimId") else ""
    return f"- {cid}[{c.get('구분')}] {render(c.get('문장', ''), data)} (근거: {refs})" + (f" {tag}" if tag else "")


def to_markdown(data: AgentData, result: dict, status: str, checks: dict, removed: list[str],
                mode: str = "expert", vlog: list[dict] | None = None, report_id: str | None = None) -> str:
    r = lambda t: render(t, data)
    f = data.facts
    emap = contract_mod.evidence_map(data)
    out = [f"- **상태**: {status}", f"- **관측 기간**: {data.period}"]
    if report_id:
        out.append(f"- **reportId**: `{report_id}` · 기준일 {data.as_of}")
    out.append(f"- **핵심 진단**: {r(result.get('핵심진단', ''))}")
    out += _tables(data)
    out += ["", "**주장과 근거** (claimId · 근거 ID·장부 키)", ""]
    out += [_claim_line(c, data, emap) for c in result.get("주장", [])]
    counter = result.get("반대근거") or []
    risks = result.get("리스크요인") or []
    if counter or risks:
        out += ["", "**반대 근거·하방 위험**", ""]
        out += [_claim_line(c, data, emap) for c in counter]
        out += [f"- (하방 위험) {r(x)}" for x in risks]
    for title, key in (("긍정 요인", "긍정요인"), ("미확인", "미확인"),
                       ("다음 점검", "다음점검"), ("스스로 확인해 볼 질문", "스스로질문")):
        items = result.get(key) or []
        if items:
            out += ["", f"**{title}**", ""] + [f"- {r(x)}" for x in items]
    score = result.get("자체점수")
    out += ["", f"**자체 점수**: {score if score is not None else '-'} / 10 · {r(result.get('점수이유', ''))}"]
    if f.flags:
        out += ["", "**코드 판정**", ""] + [f"- {r(x)}" for x in f.flags]
    out += ["", "**숫자 장부** (근거 ID = 장부 순서)", "", f.table_md(emap)]
    if f.gaps:
        out += ["", "**무자료**", ""] + [f"- {g['label']}: {g['reason']} [{AVAIL_SHORT[availability(g['label'], g['reason'])]}]"
                                         for g in f.gaps]
    if data.docs:
        out += ["", "**참고 문서 (DB 검색)**", ""] + docs_markdown(data.docs)
    elif data.extra.get("rag_error"):
        out += ["", f"- 참고 문서 검색 실패: {data.extra['rag_error'][:80]}"]
    if mode == "guide":
        terms = terms_for([v["label"] for v in f.items.values()] + f.flags)
        if terms:
            out += ["", "**용어 풀이**", ""] + [f"- **{t}**: {d}" for t, d in terms]
    if checks:
        out += ["", "**코드 검사 기록**: " + "; ".join(f"{k} {len(v)}건" for k, v in checks.items())]
    if removed:
        out += [f"- 검증되지 않아 최종 출력에서 뺀 문장 {len(removed)}개"]
    if vlog is not None:
        n_ok = sum(1 for v in vlog if v.get("ok"))
        bad = [v for v in vlog if not v.get("ok")]
        out += [f"- **Verifier (fact_source_verifier)**: 문장 {len(vlog)}개 수치 대조, 통과 {n_ok}개"
                + (f", 불일치 {len(bad)}개 제외 ({'; '.join(', '.join(v['unmatched']) for v in bad)[:120]})" if bad else "")
                + (f" · 제외된 주장 {', '.join(v['claimId'] for v in bad if v.get('claimId'))}"
                   if any(v.get("claimId") for v in bad) else "")]
    q = data.extra.get("quality")
    if q:
        out += ["", "**데이터 품질 주의**", ""] + [f"- {w['name']} ({w['api']}): {w['reason']}" for w in q]
    return "\n".join(out)


# ---------------------------------------------------------------- 실행

def run_agent(agent_id: int, ticker: str | None = None, mode: str = "expert", llm=None,
              data: AgentData | None = None, as_of: str | None = None, max_repair: int = 1,
              focus: list[str] | None = None, period: int | None = None, scenario: str | None = None,
              question: str | None = None) -> dict:
    """에이전트 하나를 실행해 팀 공통 출력 계약 dict 를 돌려줍니다.
    focus: 에이전트 1 관심 거시 변수(예: ["환율", "금리"]), period: 에이전트 3 관찰 기간(거래일). data 를 넘기면 무시됩니다."""
    if data is None:
        data = fetch_agent_data(agent_id, ticker, as_of, focus=focus, period=period, scenario=scenario,
                                question=question)
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
    vlog: list[dict] = []
    trimmed: list[str] = []
    if result is None:
        err = next((a["error"] for a in attempts if "error" in a), None)
        result, vlog, _ = verifier.apply(fallback_result(data), data)
        status = "규칙 기반 대체" + (f" (LLM 호출 실패: {err.split(':')[0]})" if err else " (JSON 형식 아님)")
    else:
        result, removed = sanitize(result, data)
        result, trimmed = cap_claims(result)
        if result["주장"]:  # 두 번째 관문: 팀 공용 fact_source_verifier 로 수치 1:1 대조 + 출처 태그
            result, vlog, vremoved = verifier.apply(result, data)
            removed += vremoved
        if not result["주장"]:
            result, vlog, _ = verifier.apply(fallback_result(data), data)
            status = "규칙 기반 대체"
        else:
            checks = attempts[best_at]["checks"]
            status = "완료" + (" (수정 1회)" if best_at > 0 else "") + (" (일부 문장 제외)" if removed else "")
    facts = data.facts
    out = {
        "agent_id": agent_id, "agent_name": data.name, "status": status, "period": data.period,
        "as_of": data.as_of, "result": result, "facts": facts.items, "gaps": facts.gaps, "flags": facts.flags,
        "checks": checks, "removed": removed, "attempts": attempts, "seconds": round(time.monotonic() - t0, 1),
        "claim_stats": claim_stats(result, vlog, removed, trimmed),
        "source": "Neon " + ", ".join(sorted({v["source"].split(" (")[0] for v in facts.items.values()}
                                             | ({"rag.document·core.disclosure"} if data.docs else set()))),
        "docs": data.docs, "verification": vlog,
        "exposure": data.extra.get("exposure"), "anomalies": data.extra.get("anomalies"),
        "quality": data.extra.get("quality"), "premises": data.extra.get("premises"),
        "baseline": data.extra.get("baseline"), "dup_clusters": data.extra.get("dup_clusters"),
    }
    # 데이터 계약 (R4 3장): reportId·claimId·evidenceId·사실/해석/예측·반대 근거·미확인·기준일/공개시각·출처 태그
    out["contract"] = contract_mod.build(out, data, mode)
    out["report_id"] = out["contract"]["reportId"]
    out["analysis"] = to_markdown(data, result, status, checks, removed, mode, vlog, out["report_id"])
    return out


def run_my_agents(ticker: str, mode: str = "expert", agent_ids=MY_AGENTS, as_of: str | None = None,
                  llm=None, focus: list[str] | None = None, period: int | None = None) -> list[dict]:
    """CH 담당 관점을 한 번에 실행해 오케스트레이터에 넘길 리스트를 돌려줍니다.
    focus: 에이전트 1 관심 거시 변수(예: ["환율", "금리"]), period: 에이전트 3 관찰 기간(거래일)."""
    from . import db

    co = db.company(ticker)
    return [run_agent(a, mode=mode, llm=llm, data=fetch_agent_data(a, ticker, as_of, co=co, focus=focus, period=period))
            for a in agent_ids]
