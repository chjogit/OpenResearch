"""페르소나 렌더러: 데이터 계약(r4-1.0~r4-1.2) 하나를 사용자 프로필에 맞춰 보여 줍니다. LLM 을 부르지 않습니다.

원칙
- 새 문장·새 숫자를 만들지 않습니다. 계약에 있는 문장(이미 Verifier 를 통과한 것)을 고르고 배치만 합니다.
- 성향은 순서만 바꿉니다. 방어는 하방 위험·반대 근거부터, 공격은 변화 신호부터. 반대 근거·하방 위험·
  미확인·일정은 어느 성향에서도 빠지지 않습니다 (DATA_CONTRACT 규칙 5).
- 숙련도는 설명의 깊이만 바꿉니다. L1 은 쉬운 제목·용어 풀이·근거표 접기, L2 는 사실/해석 구분과 보고서로 옮기는 법,
  L3 는 claimId·출처 태그·기준선 방법·Verifier 기록·전체 근거표.
- 그래서 `content_set(rendered)` (공통 구역의 항목 ID·문장 묶음)는 6개 프로필에서 모두 같아야 합니다.
"""
from __future__ import annotations

import re

from .availability import AVAIL_SHORT
from .glossary import terms_for
from .profile import Level, Stance, UserProfile

RENDER_VERSION = "1.0"

# 공통 구역: 모든 프로필에 같은 항목이 같은 문장으로 들어감 (순서·꾸밈만 다름)
COMMON = ("summary", "scope", "caveats", "signals", "exposure", "claims", "upside", "counter", "risks", "unverified",
          "nextChecks", "disclaimer")
ORDER = {
    Stance.DEFENSIVE: ("summary", "caveats", "scope", "risks", "counter", "unverified", "claims", "upside", "exposure",
                       "signals", "nextChecks"),
    Stance.AGGRESSIVE: ("summary", "caveats", "scope", "signals", "exposure", "claims", "upside", "counter", "risks",
                        "unverified", "nextChecks"),
}
TAIL = ("glossary", "method", "evidence", "disclaimer")

TITLES = {
    "summary": ("한눈에 보기", "핵심 요약", "핵심 진단"),
    "scope": ("이 답이 다루는 범위", "답한 것과 보류한 것", "과업 계약 (제작 기준)·상태 코드"),
    "caveats": ("읽기 전에 알아 둘 점", "해석 전 주의", "자료 주의 (시차·기준 시점·규모)"),
    "signals": ("최근 달라진 점", "변화 신호", "변화 신호 (코드 판정·이상 징후)"),
    "exposure": ("어떤 경제 변수에 영향을 받나", "거시 변수 노출", "거시 변수 노출 점검"),
    "claims": ("에이전트가 본 내용", "주요 주장", "주장"),
    "upside": ("좋게 볼 수 있는 점", "긍정 요인", "긍정 요인"),
    "counter": ("반대로 볼 수 있는 점", "반대 근거", "반대 근거"),
    "risks": ("나빠질 수 있는 점", "하방 위험", "하방 위험"),
    "unverified": ("아직 확인하지 못한 것", "미확인 항목", "미확인 (무자료·미확인 전제·판단 보류)"),
    "nextChecks": ("앞으로 볼 일정·점검", "다음 점검·일정", "다음 점검·일정"),
    "glossary": ("용어 풀이", "용어 풀이", "용어 풀이"),
    "method": ("", "", "방법·검증 기록"),
    "evidence": ("근거 자료", "인용한 근거", "근거 전체"),
    "disclaimer": ("", "", ""),
}
# L2: 보고서를 써 본 적 없는 투자자에게 각 구역을 보고서로 옮기는 법
HOW_TO = {
    "scope": "보고서 첫머리에 '이 보고서가 답하는 것/답하지 않는 것'으로 옮깁니다. 보류 사유도 그대로 적습니다.",
    "summary": "보고서 첫 문단에 그대로 쓰고, 뒤 구역에서 근거를 붙입니다.",
    "caveats": "결론보다 먼저 적어 독자가 자료의 한계를 알고 읽게 합니다.",
    "claims": "[사실]은 숫자로 확인된 것, [해석]은 그 숫자를 읽은 의견, [예측]은 앞으로의 가능성입니다. 보고서에서도 셋을 섞지 않습니다. "
              "문장 끝의 [출처: …] 를 그대로 옮기면 독자가 원자료를 찾을 수 있습니다.",
    "counter": "주장과 같은 무게로 적습니다. 반대 근거가 없는 보고서는 한쪽만 본 보고서입니다.",
    "risks": "어떤 조건에서 나빠지는지를 적습니다. 가격 전망이 아니라 조건입니다.",
    "unverified": "모른다는 것도 결과입니다. '확인하지 못함'으로 적고 추측으로 채우지 않습니다. "
                  "[수집 중]은 시간이 지나면 채워지고, [공시 없음]은 앞으로도 대용치로만 짐작할 수 있습니다.",
    "nextChecks": "보고서 끝 '다음에 볼 것'에 날짜와 함께 옮깁니다.",
}
L1_HINT = {
    "signals": "최근 평소와 달라진 점입니다. 중요한 것 몇 가지만 펼쳐 두고 나머지는 접어 두었습니다.",
    "scope": "숫자로 답할 수 없는 부분은 '보류'로 표시합니다. 보류는 오류가 아니라 근거가 부족하다는 뜻입니다.",
    "claims": "'확인된 사실'은 숫자로 확인한 것, '해석'과 '전망'은 그 숫자를 읽은 의견입니다.",
    "counter": "위 내용과 반대로 볼 수 있는 근거입니다. 함께 봐야 한쪽으로 치우치지 않습니다.",
    "unverified": "자료가 없거나 공시로 확인되지 않은 부분입니다. '수집 중'은 곧 채워지고, '공시 없음'은 회사가 밝히지 않는 내용입니다.",
}
TYPE_L1 = {"사실": "확인된 사실", "해석": "해석", "예측": "전망"}
CAVEAT_RE = re.compile(r"^(자료 시차|자료 지연|기준 시점 주의|규모 주의)")


def _item(ref: str, text: str, ev=None, **extra) -> dict:
    return {"ref": ref, "text": text, "evidenceIds": list(ev or []), **extra}


def _sections(c: dict) -> dict[str, list[dict]]:
    """계약 → 구역별 항목. 프로필과 무관 (공통 내용의 원천)."""
    s: dict[str, list[dict]] = {k: [] for k in COMMON}
    sm = c.get("summary") or {}
    if sm.get("text"):
        s["summary"].append(_item("summary", sm["text"], sm.get("evidenceIds")))
    px = c.get("p01") or c.get("p03")
    if px:  # 제작 기준 과업 계약: 세 줄 요약과 과업별 답함/보류 (r4-1.2)
        for k, v in (px.get("summary") or {}).items():
            s["scope"].append(_item(f"S:{k}", f"{k}: {v}"))
        state = {"answered": "답함", "held": "보류"}
        # 상태 코드 원문(MODEL_NOT_APPROVED 등)은 문장에 넣지 않고 L3 꾸밈으로만 보여 줌 (L1·L2 에 코드가 보이던 문제)
        reasons = {r.split(":")[0]: r.split(":", 1)[1].strip() for r in px.get("heldReasons") or [] if ":" in r}
        for name, t in (px.get("tasks") or {}).items():
            if t.get("state") not in state:
                continue
            codes = list(t.get("codes") or [])
            why = "; ".join(reasons.get(cd, cd) for cd in codes)
            note = why or t.get("note") or ""
            s["scope"].append(_item(f"T:{name}", f"{name}: {state[t['state']]}" + (f" — {note}" if note else ""),
                                    codes=codes))
        other = [c for c in px.get("statusCodes") or [] if not any(c in (t.get("codes") or [])
                                                                     for t in (px.get("tasks") or {}).values())]
        if other:
            s["scope"].append(_item("T:자료", "자료 상태: " + "; ".join(reasons.get(c, c) for c in other), codes=other))
    if str(c.get("status", "")).startswith("규칙 기반 대체"):
        s["caveats"].append(_item("status", f"LLM 문장 없이 코드 규칙으로 만든 요약입니다. 상태: {c['status']}"))
    for i, f in enumerate(c.get("codeFindings") or [], 1):
        key = "caveats" if CAVEAT_RE.match(f["text"]) else "signals"
        s[key].append(_item(f"F{i:02d}", f["text"], f.get("evidenceIds")))
    seen = {it["text"] for it in s["signals"]}
    for i, a in enumerate(c.get("anomalies") or [], 1):   # 코드 판정에 같은 문장이 있으면 한 번만 (기준선 표는 L3 방법 구역)
        if a["text"] not in seen:
            s["signals"].append(_item(f"A{i:02d}", a["text"], a.get("evidenceIds")))
    for e in c.get("exposure") or []:
        s["exposure"].append(_item(f"X:{e['variable']}", f"{e['variable']}: 노출 {e['level']}", e.get("evidenceIds"),
                                   basis=e.get("basis"), companySpecific=e.get("companySpecific"), focus=e.get("focus")))
    for cl in c.get("claims") or []:
        key = "claims" if cl["role"] == "main" else "counter"
        s[key].append(_item(cl["claimId"], cl["text"], cl.get("evidenceIds"), typeLabel=cl.get("typeLabel"),
                            sourceTags=cl.get("sourceTags") or []))
    for u in c.get("upsideFactors") or []:
        s["upside"].append(_item(u["upsideId"], u["text"], u.get("evidenceIds")))
    for r in c.get("downsideRisks") or []:
        s["risks"].append(_item(r["riskId"], r["text"], r.get("evidenceIds")))
    for i, u in enumerate(c.get("unverified") or [], 1):
        s["unverified"].append(_item(f"U{i:02d}", u["item"], u.get("evidenceIds"), reason=u.get("reason"),
                                     category=u.get("category"), status=u.get("status"),
                                     availability=u.get("availability")))
    for i, t in enumerate(c.get("nextChecks") or [], 1):
        s["nextChecks"].append(_item(f"N{i:02d}", t))
    s["disclaimer"].append(_item("disclaimer", c.get("disclaimer") or ""))
    return s


L1_SIGNALS = 3
SIGNAL_PRIORITY = ("이상 징후", "거시 이상", "금리 이벤트 임박", "과거 관계", "중복 신호", "엇갈림", "분기 자료 검토")


def _signal_rank(it: dict) -> tuple:
    """입문자에게 먼저 보일 변화 신호: 이상 징후·임박 일정 → 국면 판정 → 나머지 (같은 순위는 원래 순서)."""
    t = it["text"]
    for i, word in enumerate(SIGNAL_PRIORITY):
        if t.startswith(word) or word in t[:20]:
            return (i,)
    return (len(SIGNAL_PRIORITY) + ("국면" not in t),)


def _line(sec: str, it: dict, lv: Level) -> str:
    ev = ", ".join(it["evidenceIds"])
    if it["ref"].endswith("-none"):                       # '확인하지 못함' 안내는 꾸밈 없이
        return f"- {it['text']}"
    if sec in ("claims", "counter"):
        t = it.get("typeLabel") or "해석"
        if lv == Level.L1:
            return f"- ({TYPE_L1.get(t, t)}) {it['text']}"
        if lv == Level.L2:  # 보고서에 그대로 붙일 출처 문구를 함께 (10-29 페르소나 점검 A2)
            tags = " ".join(it.get("sourceTags") or [])
            return f"- [{t}] {it['text']}" + (f" {tags}" if tags else "") + (f" _(근거 {ev})_" if ev else "")
        tags = " ".join(it.get("sourceTags") or [])
        return f"- `{it['ref']}` [{t}] {it['text']}" + (f" — {ev}" if ev else "") + (f" {tags}" if tags else "")
    if sec == "unverified":
        av = AVAIL_SHORT.get(it.get("availability") or "", "") if it.get("availability") != "unclassified" else ""
        if lv == Level.L1:
            return f"- {it['text']}" + (f" _({av})_" if av else "")
        why = f": {it['reason']}" if it.get("reason") else ""
        if lv == Level.L2:
            return f"- {it['text']}{why}" + (f" **[{av}]**" if av else "")
        return (f"- `{it['ref']}` [{it.get('category')}·{it.get('status')}"
                + (f"·{it['availability']}" if it.get("availability") else "") + f"] {it['text']}{why}"
                + (f" — {ev}" if ev else ""))
    if sec == "exposure":
        if lv == Level.L1:
            return f"- {it['text']}"
        basis = f" ({it['basis']})" if it.get("basis") else ""
        mark = " · 회사 공시 기반" if it.get("companySpecific") else " · 주가 통계 기반"
        return f"- {it['text']}{basis}" + (mark if lv == Level.L3 else "") + (f" — {ev}" if lv == Level.L3 and ev else "")
    if sec == "scope" and lv == Level.L3 and it.get("codes"):
        return f"- `{it['ref']}` {it['text']} — `{'`, `'.join(it['codes'])}`"
    if lv == Level.L3 and it["ref"] not in ("summary", "status", "disclaimer"):
        return f"- `{it['ref']}` {it['text']}" + (f" — {ev}" if ev else "")
    if lv == Level.L2 and ev and sec not in ("summary",):
        return f"- {it['text']} _(근거 {ev})_"
    return f"- {it['text']}"


def _glossary(secs: dict[str, list[dict]]) -> list[str]:
    texts = [it["text"] for k in COMMON for it in secs[k]]
    return [f"- **{t}**: {d}" for t, d in terms_for(texts)]


def _method(c: dict) -> list[str]:
    out = []
    v = c.get("verification") or {}
    out.append(f"- 수치 대조: `{v.get('checker')}` · 대조 {v.get('checked')}건 중 통과 {v.get('passed')}건 · "
               f"형식·수치 검사에서 뺀 문장 {v.get('removedSentences')}건")
    for b in c.get("baseline") or []:
        out.append(f"- 기준선 `{b['signal']}`: {b['method']} / {b['rule']} → {b['status']}")
    for p in c.get("premises") or []:
        out.append(f"- 전제 `{p['item']}` [{p['status']}]: {p['detail']}")
    for d in c.get("duplicateSignals") or []:
        out.append(f"- 중복 신호 `{d['clusterId']}`: {', '.join(d['signals'])} — {d['rule']}")
    px = c.get("p01") or c.get("p03")
    if px:
        out.append(f"- 제작 기준: {px.get('standard')} · 정책 `{px.get('policy')}` · 상태 코드 {', '.join(px.get('statusCodes') or []) or '없음'}")
        if px.get("tiers"):
            out.append(f"- 근거 등급: 기준 부합 {px['tiers'].get('core')}개 · 참고용 {px['tiers'].get('reference')}개")
        for r in px.get("eventStudy") or []:
            if r.get("status") == "ok":
                base = f", 모든 거래일 기준선 {r['base_median']:+.2f}%p" if r.get("base_median") is not None else ""
                out.append(f"- 사건 연구 `{r['scope']} {r['who']} {r['signal']} {r['h']}일`: 사건 {r['n']}건·신호일 "
                           f"{r['independent']}개, 초과수익률 중앙값 {r['median']:+.2f}%p{base} (과거 관계, 투자 신호 아님)")
    if c.get("sentimentModel"):
        out.append(f"- 감성 점수: {c['sentimentModel']}")
    for q in c.get("dataQuality") or []:
        out.append(f"- 수집 품질: {q if isinstance(q, str) else q.get('text', q)}")
    return out


def _evidence(c: dict, lv: Level) -> list[str]:
    rows = [e for e in c.get("evidence") or [] if lv == Level.L3 or e.get("cited")]
    if not rows:
        return []
    if lv == Level.L3:
        head = ["| 근거 | 항목 | 값 | 기준일 | 공개시각 | 구분 | 출처 | 인용 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        body = [f"| {e['evidenceId']} | {e.get('label') or ''} | {e.get('display') or ''} | {e.get('dataDate') or '-'} | "
                f"{e.get('publishedAt') or '-'} | {e.get('valueType') or ''} | {e.get('source') or ''} | "
                f"{'○' if e.get('cited') else ''} |" for e in rows]
    else:
        head = ["| 근거 | 항목 | 값 | 기준일 |", "| --- | --- | --- | --- |"]
        body = [f"| {e['evidenceId']} | {e.get('label') or ''} | {e.get('display') or ''} | {e.get('dataDate') or '-'} |"
                for e in rows]
    return head + body


def render(contract: dict, profile: UserProfile | dict | None = None) -> dict:
    """계약 하나 → 프로필별 화면. 돌려주는 값: {reportId, userProfile, renderVersion, sections, markdown}"""
    p = profile if isinstance(profile, UserProfile) else UserProfile.from_dict(profile)
    lv, li = p.level, int(p.level.value[1]) - 1
    secs = _sections(contract)
    if not secs["counter"]:
        secs["counter"].append(_item("counter-none", "검증을 통과한 반대 근거가 없습니다 (반대 근거를 확인하지 못함)."))
    if not secs["risks"]:
        secs["risks"].append(_item("risks-none", "검증을 통과한 하방 위험이 없습니다 (하방 위험을 확인하지 못함)."))

    sections = []
    for sid in ORDER[p.stance]:
        if secs[sid]:
            sections.append({"id": sid, "title": TITLES[sid][li], "items": secs[sid]})
    if lv != Level.L3:
        gl = _glossary(secs)
        if gl:
            sections.append({"id": "glossary", "title": TITLES["glossary"][li], "lines": gl})
    if lv == Level.L3:
        sections.append({"id": "method", "title": TITLES["method"][li], "lines": _method(contract)})
    ev = _evidence(contract, lv)
    if ev:
        sections.append({"id": "evidence", "title": TITLES["evidence"][li], "lines": ev})
    sections.append({"id": "disclaimer", "title": "", "items": secs["disclaimer"]})

    tgt = contract.get("target") or {}
    agent = contract.get("agent") or {}
    md = [f"### {agent.get('name', '')} · {tgt.get('name', '')}({tgt.get('ticker', '')}) · 기준 {contract.get('asOf')}",
          "", f"보기: **{p.label}** · 상태 {contract.get('status')} · reportId `{contract.get('reportId')}`", ""]
    for s in sections:
        sid = s["id"]
        if sid == "disclaimer":
            md += ["---", f"_{s['items'][0]['text']}_"]
            continue
        md.append(f"**{s['title']}**")
        hint = (HOW_TO if lv == Level.L2 else L1_HINT if lv == Level.L1 else {}).get(sid)
        if hint:
            md.append(f"> {hint}")
        md.append("")
        if sid == "evidence" and lv == Level.L1:
            md += ["<details><summary>근거 자료 보기</summary>", "", *s["lines"], "", "</details>", ""]
            continue
        if sid == "signals" and lv == Level.L1 and len(s["items"]) > L1_SIGNALS:
            # 입문자 첫 화면에 변화 신호가 16~17개 나오던 문제: 중요한 3개만 펼치고 나머지는 접음 (내용은 그대로)
            items = sorted(s["items"], key=_signal_rank)
            md += [_line(sid, it, lv) for it in items[:L1_SIGNALS]]
            md += ["", f"<details><summary>나머지 변화 신호 {len(items) - L1_SIGNALS}개 보기</summary>", "",
                   *[_line(sid, it, lv) for it in items[L1_SIGNALS:]], "", "</details>", ""]
            continue
        md += s["lines"] if "lines" in s else [_line(sid, it, lv) for it in s["items"]]
        md.append("")
    return {"reportId": contract.get("reportId"), "userProfile": p.to_dict(), "renderVersion": RENDER_VERSION,
            "sections": sections, "markdown": "\n".join(md)}


def content_set(rendered: dict) -> set[tuple]:
    """프로필과 무관해야 하는 내용: 공통 구역의 (구역, 항목 ID, 문장, 근거 ID)."""
    return {(s["id"], it["ref"], it["text"], tuple(it["evidenceIds"]))
            for s in rendered["sections"] if s["id"] in COMMON for it in s.get("items") or []}


def render_all(contract: dict) -> dict[str, dict]:
    """6개 프로필 모두. 키는 'L1-defensive' 형식."""
    from .profile import ALL_PROFILES

    return {f"{p.level.value}-{p.stance.value}": render(contract, p) for p in ALL_PROFILES}
