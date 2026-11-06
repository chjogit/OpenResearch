"""미확보·미확인 목록 정리(#62): 중복 합치기 · 성격별 묶음 · 내부 코드 한국어화. 에이전트 계약·질의응답·시연이 같은 규칙을 쓴다(한 곳).

묶음(GROUPS): 미확보(실제로 없는 자료) · 범위 밖(공개·무로그인 출처 없음) · 수집 중(기간이 짧음) · 기준일 차이(수집이 시세보다 늦음) ·
한계(방법의 한계) / 처리 기록(처리 통계 — 목록에서 빼고 0건 조각은 버림).
같은 주제(같은 노드·같은 대상)는 한 줄로 합치고, 출처는 '노드 점검'·'에이전트 판단' 표시로만 남긴다.
"""
from __future__ import annotations

import re

GROUPS = {"missing": "미확보", "out_of_scope": "범위 밖", "collecting": "수집 중", "date_diff": "기준일 차이", "limit": "한계"}
PROCESSING = "processing"
NODE_CHECK, AGENT_JUDGE = "노드 점검", "에이전트 판단"

# ---- 내부 코드 → 한국어 용어표 (#48 용어표를 한 곳으로: 시연·질의응답·계약 모두 사용)
NODE_KO = {"N05": "거시 데이터 점검", "N06": "거시 해석", "N07": "수급 데이터 점검", "N08": "수급 해석",
           "N11": "심리·뉴스 데이터 점검", "N12": "심리·뉴스 해석"}
PHRASE_KO = (("확장 노드 입력 요건 미충족", "추가 분석에 필요한 자료 부족"), ("D1 사후 탐색 등급", "사후 탐색 단계(검증 전)"),
             ("(Point-in-Time)", ""), ("Point-in-Time", "시점별 이력"), ("CAR", "사건 뒤 주가 반응(초과수익)"))
_L, _R = r"(?<![A-Za-z0-9_])", r"(?![A-Za-z0-9_])"   # 한글 조사('E10에서')가 붙어도 코드 경계로 인식


def ko_text(t: str) -> str:
    """내부 코드(N05 등)·약어(CAR)·사건/근거 번호를 사람이 읽는 말로. 원 코드는 화면의 title 이나 표 ID 칸에만 남음."""
    for a, b in PHRASE_KO:
        t = re.sub(rf"{_L}{re.escape(a)}{_R}" if a.isascii() else re.escape(a), b, t)
    t = re.sub(rf"{_L}N(05|06|07|08|11|12){_R}", lambda m: NODE_KO[f"N{m.group(1)}"], t)
    t = re.sub(r"사건 E0*\d+(?:\s*(?:[·,、]|과|와)\s*E0*\d+)*", lambda m: "사건 " + re.sub(r"E0*(\d+)", r"\1", m.group(0)[3:]), t)
    t = re.sub(r"근거 E0*(\d+)", r"근거 \1", t)
    t = re.sub(rf"{_L}E0*(\d+){_R}", r"근거 \1", t)
    return strip_keys(t)


KEY = r"(?<![A-Za-z0-9])(?!Q[1-4](?![0-9])|H[12](?![0-9]))[A-Z]\d{1,5}(?![0-9])"
KEY_LIST_RE = re.compile(rf"[（(]?\s*{KEY}(?:\s*[·,、/]\s*{KEY})*\s*[)）]?")


def strip_keys(t: str) -> str:
    """장부 내부 키('T1056·T1057')와 그 나열을 지운다. 값·설명은 항목 이름·사유에 이미 있다."""
    t = KEY_LIST_RE.sub("", t)
    t = re.sub(r"[（(]\s*[)）]", "", t)
    return re.sub(r"\s{2,}", " ", t).strip(" ,·")


# ---- 분류: 처음 맞는 주제 규칙 (정규식, 표시 이름, 묶음). 이름이 None 이면 원래 항목 이름을 정리해 쓴다.
TOPICS = (
    (re.compile(r"호가\s*잔량"), "호가 잔량", "out_of_scope"),
    (re.compile(r"세부\s*(투자\s*)?주체"), "세부 투자 주체(금융투자·투신·연기금)", "out_of_scope"),
    (re.compile(r"(투자자별\s*)?수급.{0,12}(늦|마지막)|(늦|마지막).{0,12}수급|\d{4}-\d\d-\d\d\s*투자자별\s*수급"), None, "date_diff"),
    (re.compile(r"블로그\s*감성\s*변화"), "블로그 감성 변화", "collecting"),
    (re.compile(r"카페\s*감성\s*변화"), "카페 감성 변화", "collecting"),
    (re.compile(r"유튜브.{0,6}감성\s*변화"), "유튜브 댓글 감성 변화", "collecting"),
    (re.compile(r"거시지표.{0,6}(발표|수정).{0,4}이력|Point-in-Time"), "거시지표 발표·수정 이력", "missing"),
    (re.compile(r"감성\s*판정\s*한계|정확도\s*\d"), "감성 판정 정확도", "limit"),
    (re.compile(r"^(긍정|부정)(·위험)?\s*요인$"), None, "limit"),
)
STAT_RE = re.compile(r"문서\s*\d+건")
GENERIC_REASON = re.compile(r"LLM\s*이?\s*근거\s*부족으로\s*보고|N\d\d\s*미충족\s*항목|에이전트가\s*판단에\s*필요하다고\s*본\s*미확인\s*항목|"
                            r"무자료|미충족\s*항목")
LAST_DATE_RE = re.compile(r"마지막\s*(?:집계\s*)?(\d{4})-(\d\d)-(\d\d)")
BALANCE = {"긍정 요인": "긍정 요인 — 확인된 문장 없음", "부정·위험 요인": "부정·위험 요인 — 확인된 문장 없음"}


def tidy(unverified: list[dict]) -> list[dict]:
    """계약 unverified[] 정리(#62): 용어 한국어화 · 같은 주제 합치기(근거 ID 합침) · 묶음(group)·출처(sources) 표시. 항목 이름·사유는 한국어화만 하고 이름을 바꾸지 않는다."""
    out: list[dict] = []
    seen: dict[tuple, dict] = {}
    for u in unverified:
        item, reason = ko_text(str(u.get("item", ""))), ko_text(str(u.get("reason", "")))
        cl = classify(item, reason)
        group = cl["group"] if cl else PROCESSING
        topic = re.sub(r"\s+", "", cl["topic"] if cl else item)
        key = (group, topic)
        if key in seen:
            dup = seen[key]
            dup["evidenceIds"] = list(dict.fromkeys(dup["evidenceIds"] + list(u.get("evidenceIds") or [])))
            src = cl["source"] if cl else NODE_CHECK
            if src not in dup["sources"]:
                dup["sources"] = sorted([*dup["sources"], src], key=[NODE_CHECK, AGENT_JUDGE].index)
            continue
        row = {**u, "item": item, "reason": reason, "group": group, "groupLabel": GROUPS.get(group, "처리 기록"),
               "sources": [cl["source"] if cl else NODE_CHECK]}
        seen[key] = row
        out.append(row)
    return out


def split_stat(item: str) -> tuple[str, list[str]]:
    """'…문서 0건, …문서 43건' 같은 처리 통계 문장을 (빠진 자료 문구, 처리 기록 조각) 으로. 0건 조각은 버림."""
    if not STAT_RE.search(item) or any(rx.search(item) for rx, _, _ in TOPICS):      # 주제 항목('블로그 감성 변화(문서 N건·5일뿐)')은 통계가 아니다
        return item, []
    frags = re.split(r"[,，]|\s및\s|\s그리고\s", item)
    return "", list(dict.fromkeys(_canon(c) for c in frags if STAT_RE.search(c) and not re.search(r"(?<!\d)0건", c)))


# 같은 통계가 다른 말로 적힌 것을 한 문장으로 (미충족 꼬리표는 뗌)
CANON = ((re.compile(r"근거 문장.{0,12}(?:붙이지|미부착).{0,18}문서\s*(\d+)건"), "근거 문장을 붙이지 못해 점수를 내지 않은 문서 {n}건"),
         (re.compile(r"대상 기업 아님.{0,10}문서\s*(\d+)건"), "대상 기업 아님으로 분리한 문서 {n}건"))


def _canon(frag: str) -> str:
    frag = re.sub(r"\s*[（(][^()（）]*미충족[^()（）]*[)）]", "", frag).strip()
    for rx, tpl in CANON:
        m = rx.search(frag)
        if m:
            return tpl.format(n=m.group(1))
    return frag


def _source(reason: str) -> str:
    return AGENT_JUDGE if re.search(r"LLM\s*이?\s*근거\s*부족|에이전트가\s*판단", reason or "") else NODE_CHECK


def _detail_of(label: str, reason: str) -> str:
    """항목 이름 속 괄호·콜론 뒤 설명 + 일반 문구가 아닌 사유 중 가장 긴 것."""
    cands = [m.strip(" ,") for m in re.findall(r"[（(]([^()（）]+)[)）]", label)]
    if ":" in label:
        cands.append(label.split(":", 1)[1].strip())
    if reason and not GENERIC_REASON.search(reason):
        cands.append(reason.strip())
    return max(cands, key=len, default="")


def _plain_label(label: str) -> str:
    base = re.split(r"[（(:]", label, 1)[0].strip()
    base = re.sub(r"\s*변수$", "", base)               # '관세·통상정책 변수' = '관세·통상정책' (같은 주제)
    return base or label.strip()


def classify(label: str, reason: str = "") -> dict | None:
    """항목 하나 → {'topic','group','label','detail','source'}. 처리 통계 조각만 있으면 None (처리 기록으로 빠짐)."""
    label = ko_text(label or "").strip()
    reason = ko_text(reason or "").strip()
    if not label or not split_stat(label)[0]:
        return None
    detail = _detail_of(label, reason)
    for rx, name, group in TOPICS:
        if rx.search(label):
            if group == "date_diff":
                m = LAST_DATE_RE.findall(f"{label} {reason}")
                last = m[-1] if m else None
                name = f"수급은 {int(last[1])}/{int(last[2])} 기준" if last else "수급은 마지막 수집일 기준"
                detail = "수집이 시세보다 하루 늦어 마지막으로 수집된 날짜 기준 자료를 사용"
                return {"topic": "수급기준일", "group": group, "label": name, "detail": detail, "source": _source(reason)}
            name = name or BALANCE.get(_plain_label(label)) or _plain_label(label)
            return {"topic": name, "group": group, "label": name, "detail": detail, "source": _source(reason)}
    text = f"{label} {reason}"
    group = ("out_of_scope" if re.search(r"범위\s*밖|공개·무로그인", text) else
             "collecting" if re.search(r"기간\s*짧|\d+일뿐|수집\s*중", text) else
             "limit" if re.search(r"한계|정확도", text) else "missing")
    name = _plain_label(label)
    return {"topic": re.sub(r"\s+", "", name), "group": group, "label": name, "detail": detail, "source": _source(reason)}


def organize(gaps: list[dict]) -> tuple[list[dict], list[str]]:
    """[{'label','reason'}] → (묶음 순서로 정리한 항목, 처리 기록 조각).
    항목: {'group','groupLabel','label','detail','reason','sources'}. 같은 주제는 하나로(출처 합침), 0건 통계는 버림."""
    merged: dict[tuple, dict] = {}
    proc: list[str] = []
    for g in gaps:
        label, reason = str(g.get("label") or g.get("item") or ""), str(g.get("reason") or "")
        rest, st = split_stat(ko_text(label))
        proc += st
        if not rest:
            continue
        c = classify(label, reason)
        if c is None:
            continue
        key = (c["group"], re.sub(r"\s+", "", c["topic"]))
        cur = merged.get(key)
        if cur is None:
            merged[key] = {"group": c["group"], "groupLabel": GROUPS[c["group"]], "label": c["label"], "detail": c["detail"], "sources": [c["source"]]}
        else:
            cur["detail"] = max([cur["detail"], c["detail"]], key=len)
            if c["group"] == "date_diff" and "마지막 수집일" in cur["label"]:      # 날짜가 있는 쪽 이름을 쓴다
                cur["label"] = c["label"]
            if c["source"] not in cur["sources"]:
                cur["sources"].append(c["source"])
    order = list(GROUPS)
    items = sorted(merged.values(), key=lambda x: order.index(x["group"]))
    for it in items:
        it["sources"].sort(key=[NODE_CHECK, AGENT_JUDGE].index)
        it["reason"] = it["detail"] or it["groupLabel"]
    return items, list(dict.fromkeys(proc))


RAW_CODE_RE = re.compile(rf"{KEY}|{_L}N(05|06|07|08|11|12){_R}|{_L}CAR{_R}|{_L}D1 사후|Point-in-Time|확장 노드 입력 요건 미충족|{_L}E\d+{_R}")


def gap_problems(items: list[dict]) -> list[str]:
    """저장 전 검사: 같은 항목 중복 · 날것 내부 코드 · 0건 처리 통계 · 미확보 목록에 섞인 한계 항목."""
    bad, seen = [], set()
    for it in items:
        key = (it.get("group"), re.sub(r"\s+", "", it.get("label", "")))
        text = f"{it.get('label', '')} {it.get('detail', '')} {it.get('reason', '')}"
        if key in seen:
            bad.append(f"중복: {it.get('label')}")
        seen.add(key)
        if RAW_CODE_RE.search(text):
            bad.append(f"내부 코드: {text[:40]}")
        if re.search(r"(?<!\d)0건", it.get("label", "")):
            bad.append(f"0건 항목: {it.get('label')}")
        if it.get("group") == "missing" and (STAT_RE.search(it.get("label", "")) or re.search(r"한계|정확도\s*\d", it.get("label", ""))):
            bad.append(f"미확보에 섞인 처리 통계·한계: {it.get('label')}")
    return bad
